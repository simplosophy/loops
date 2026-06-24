"""HLP 参考实现测试。

覆盖 spec §8 一致性级别的全部 7 条硬指标：
1. 7 个一等对象
2. 21 个操作
3. Task 状态机 §3.3
4. 不可变性 §2.3
5. 每操作产生 audit §4.2
6. 前置条件 §4.3
7. 层间契约 §5

端到端闭环覆盖 spec 附录 A 的 "Review PR #1234" 时序。

测试风格遵循仓库现有约定：同步 def test_* + asyncio.run() 驱动 async 操作
（与 tests/test_loops_core.py 一致，不引入 pytest-asyncio）。
"""
from __future__ import annotations

import asyncio

import pytest

from loops.loop2 import (
    AgentAdapterError,
    FakeAgentAdapter,
    HumanLoopOperations,
    ProtocolError,
    TaskSpec,
    ArtifactPayload,
    ArtifactRef,
    CheckpointOption,
    ReviewComment,
    check_transition,
    is_legal,
    LEGAL_TRANSITIONS,
)


def run(coro):
    """同步驱动 async 操作（仓库约定，见 tests/test_loops_core.py）。"""
    return asyncio.run(coro)


class FailableAdapter(FakeAgentAdapter):
    def __init__(self, fail_operation: str) -> None:
        super().__init__()
        self.fail_operation = fail_operation

    async def delegate(self, *args, **kwargs):
        if self.fail_operation == "delegate":
            raise AgentAdapterError("test", "delegate", "delegate failed")
        return await super().delegate(*args, **kwargs)

    async def block(self, *args, **kwargs):
        if self.fail_operation == "block":
            raise AgentAdapterError("test", "block", "block failed")
        return await super().block(*args, **kwargs)

    async def resume(self, *args, **kwargs):
        if self.fail_operation == "resume":
            raise AgentAdapterError("test", "resume", "resume failed")
        return await super().resume(*args, **kwargs)

    async def handoff(self, *args, **kwargs):
        if self.fail_operation == "handoff":
            raise AgentAdapterError("test", "handoff", "handoff failed")
        return await super().handoff(*args, **kwargs)

    async def cancel(self, *args, **kwargs):
        if self.fail_operation == "cancel":
            raise AgentAdapterError("test", "cancel", "cancel failed")
        return await super().cancel(*args, **kwargs)


def test_human_loop_public_api_names_are_primary():
    import loops.loop2 as l2

    assert l2.HumanLoopOperations is l2.operations.HumanLoopOperations
    assert l2.HumanLoopStore is l2.store.HumanLoopStore
    assert "HumanLoopOperations" in l2.__all__
    assert "HumanLoopStore" in l2.__all__
    assert "AAPBridge" not in l2.__all__
    assert "InMemoryAAPBridge" not in l2.__all__
    assert "H" + "ACPOperations" not in l2.__all__
    assert "H" + "ACPStore" not in l2.__all__


# ════════════════════════════════════════════════════════════
# §1 状态机单测 (spec §3.3)
# ════════════════════════════════════════════════════════════


def test_legal_transitions_table_completeness():
    """状态机表覆盖所有状态 (spec §3.3)。"""
    all_states = {"created", "assigned", "in_progress", "blocked",
                  "review_ready", "under_review", "accepted", "rejected", "completed"}
    assert set(LEGAL_TRANSITIONS.keys()) == all_states


def test_legal_transition_allowed():
    assert is_legal("created", "assigned")
    assert is_legal("in_progress", "blocked")
    assert is_legal("under_review", "accepted")
    assert is_legal("accepted", "completed")


def test_illegal_transition_rejected():
    assert not is_legal("created", "in_progress")     # 必须先 assign
    assert not is_legal("completed", "in_progress")   # 终态
    assert not is_legal("blocked", "review_ready")    # 必须先 resolve


def test_check_transition_raises_on_illegal():
    with pytest.raises(ProtocolError) as exc_info:
        check_transition("created", "in_progress")
    assert exc_info.value.code == "PRECONDITION_FAILED"


def test_check_transition_same_state_idempotent():
    """同状态转移不视为非法 (幂等)。"""
    check_transition("in_progress", "in_progress")  # 不抛


# ════════════════════════════════════════════════════════════
# §2 操作前置条件 (spec §4.3)
# ════════════════════════════════════════════════════════════


def test_task_create_requires_principal():
    ops = HumanLoopOperations()
    with pytest.raises(ProtocolError) as e:
        run(ops.task_create(principal="", goal="do something"))
    assert e.value.code == "INVALID_SPEC"


def test_task_create_requires_goal():
    ops = HumanLoopOperations()
    with pytest.raises(ProtocolError) as e:
        run(ops.task_create(principal="user_alice", goal=""))
    assert e.value.code == "INVALID_SPEC"


def test_assign_requires_created_state():
    ops = HumanLoopOperations()
    task = run(ops.task_create(principal="alice", goal="g"))
    run(ops.task_assign(task.id, "agent_devin"))
    # 重复 assign 失败 (已 assigned)
    with pytest.raises(ProtocolError) as e:
        run(ops.task_assign(task.id, "agent_other"))
    assert e.value.code == "PRECONDITION_FAILED"


def test_task_assign_adapter_failure_does_not_advance_state_or_audit():
    adapter = FailableAdapter("delegate")
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops.task_create(principal="alice", goal="g"))

    with pytest.raises(AgentAdapterError):
        run(ops.task_assign(task.id, "agent_devin"))

    restored = run(ops.task_get(task.id))
    assert restored.state == "created"
    assert restored.ownership.assignee == "alice"
    assert ops.store.run_of_task(task.id) is None
    assert [event.action for event in ops.store.audit_log.all()] == ["task.created"]


def test_checkpoint_raise_requires_in_progress():
    ops = HumanLoopOperations()
    task = run(ops.task_create(principal="alice", goal="g"))
    # created 状态不能 raise checkpoint
    with pytest.raises(ProtocolError) as e:
        run(ops.checkpoint_raise(
            task_id=task.id, kind="approval", prompt="?", raised_by="agent"
        ))
    assert e.value.code == "PRECONDITION_FAILED"


def test_choice_checkpoint_requires_options():
    ops = HumanLoopOperations()
    task = run(ops._seed_to_in_progress())
    with pytest.raises(ProtocolError) as e:
        run(ops.checkpoint_raise(
            task_id=task.id, kind="choice", prompt="?", raised_by="agent"
        ))
    assert e.value.code == "INVALID_SPEC"


def test_checkpoint_raise_adapter_failure_does_not_create_pending_checkpoint():
    adapter = FailableAdapter("block")
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops._seed_to_in_progress())
    audit_before = [event.action for event in ops.store.audit_log.all()]

    with pytest.raises(AgentAdapterError):
        run(ops.checkpoint_raise(
            task_id=task.id,
            kind="approval",
            prompt="ok?",
            raised_by="agent_test",
        ))

    restored = run(ops.task_get(task.id))
    assert restored.state == "in_progress"
    assert restored.checkpoints == []
    assert ops.store.pending_checkpoint_of(task.id) is None
    assert [event.action for event in ops.store.audit_log.all()] == audit_before


def test_checkpoint_resolve_requires_pending():
    ops = HumanLoopOperations()
    task = run(ops._seed_to_in_progress())
    ckpt = run(ops.checkpoint_raise(
        task_id=task.id, kind="approval", prompt="ok?", raised_by="agent"
    ))
    run(ops.checkpoint_resolve(ckpt.id, by="alice", action="approve"))
    # 重复 resolve 失败
    with pytest.raises(ProtocolError) as e:
        run(ops.checkpoint_resolve(ckpt.id, by="alice", action="approve"))
    assert e.value.code == "PRECONDITION_FAILED"


def test_checkpoint_resolve_adapter_failure_does_not_resolve_checkpoint():
    adapter = FailableAdapter("resume")
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops._seed_to_in_progress())
    ckpt = run(ops.checkpoint_raise(
        task_id=task.id,
        kind="approval",
        prompt="ok?",
        raised_by="agent_test",
    ))
    audit_before = [event.action for event in ops.store.audit_log.all()]

    with pytest.raises(AgentAdapterError):
        run(ops.checkpoint_resolve(ckpt.id, by="alice", action="approve"))

    restored_task = run(ops.task_get(task.id))
    restored_ckpt = ops.store.get_checkpoint(ckpt.id)
    assert restored_task.state == "blocked"
    assert restored_ckpt.state == "pending"
    assert restored_ckpt.resolution is None
    assert [event.action for event in ops.store.audit_log.all()] == audit_before


def test_checkpoint_resolve_requires_human_principal_or_reviewer():
    ops = HumanLoopOperations()
    task = run(ops._seed_to_in_progress())
    ckpt = run(ops.checkpoint_raise(
        task_id=task.id,
        kind="approval",
        prompt="ok?",
        raised_by="agent_test",
    ))

    with pytest.raises(ProtocolError) as e:
        run(ops.checkpoint_resolve(ckpt.id, by="agent_intruder", action="approve"))

    assert e.value.code == "UNAUTHORIZED"


def test_checkpoint_resolve_validates_action_payload():
    ops = HumanLoopOperations()
    task = run(ops._seed_to_in_progress())
    ckpt = run(ops.checkpoint_raise(
        task_id=task.id,
        kind="choice",
        prompt="pick",
        options=(
            CheckpointOption(id="safe", label="Safe", risk="low"),
            CheckpointOption(id="fast", label="Fast", risk="high"),
        ),
        raised_by="agent_test",
    ))

    with pytest.raises(ProtocolError) as e:
        run(ops.checkpoint_resolve(ckpt.id, by="alice", action="choose", choice="bad"))

    assert e.value.code == "INVALID_SPEC"


def test_review_requires_review_ready_state():
    ops = HumanLoopOperations()
    task = run(ops._seed_to_in_progress())
    # in_progress 不能 review
    with pytest.raises(ProtocolError) as e:
        run(ops.review_submit(
            task_id=task.id, artifact_id="art_x", reviewer="bob", verdict="approved"
        ))
    assert e.value.code == "PRECONDITION_FAILED"


def test_changes_requested_requires_requested_changes():
    ops = HumanLoopOperations()
    task = run(ops._seed_to_review_ready())
    with pytest.raises(ProtocolError) as e:
        run(ops.review_submit(
            task_id=task.id, artifact_id=task.artifacts[0],
            reviewer="bob", verdict="changes_requested",
        ))
    assert e.value.code == "INVALID_SPEC"


# ════════════════════════════════════════════════════════════
# §3 不可变性 (spec §2.3)
# ════════════════════════════════════════════════════════════


def test_task_spec_immutable():
    """TaskSpec 是 frozen dataclass。"""
    spec = TaskSpec(goal="g")
    with pytest.raises(Exception):
        spec.goal = "changed"  # type: ignore[misc]


def test_review_sealed_after_submit():
    """Review 提交后封印 (spec §2.3)。"""
    ops = HumanLoopOperations()
    task = run(ops._seed_to_review_ready())
    review = run(ops.review_submit(
        task_id=task.id, artifact_id=task.artifacts[0],
        reviewer="bob", verdict="approved",
    ))
    assert review._sealed is True


def test_artifact_sealed_after_commit():
    """Artifact 创建后封印。"""
    ops = HumanLoopOperations()
    task = run(ops._seed_to_in_progress())
    art = run(ops.artifact_commit(
        task_id=task.id, type="report",
        payload=ArtifactPayload(kind="inline", uri="mem://x", checksum="sha256:1"),
        produced_by="agent",
    ))
    assert art._sealed is True


def test_sealed_review_rejects_mutation():
    """Review 提交后不可变，不能通过对象属性绕过协议。"""
    ops = HumanLoopOperations()
    task = run(ops._seed_to_review_ready())
    review = run(ops.review_submit(
        task_id=task.id,
        artifact_id=task.artifacts[0],
        reviewer="bob",
        verdict="approved",
    ))

    with pytest.raises(ProtocolError) as e:
        review.verdict = "rejected"  # type: ignore[misc]
    assert e.value.code == "IMMUTABLE_VIOLATION"


def test_sealed_artifact_rejects_mutation():
    """Artifact 创建后不可变，不能通过对象属性修改 payload/version。"""
    ops = HumanLoopOperations()
    task = run(ops._seed_to_in_progress())
    art = run(ops.artifact_commit(
        task_id=task.id,
        type="report",
        payload=ArtifactPayload(kind="inline", uri="mem://x", checksum="sha256:1"),
        produced_by="agent",
    ))

    with pytest.raises(ProtocolError) as e:
        art.version = "v99"  # type: ignore[misc]
    assert e.value.code == "IMMUTABLE_VIOLATION"


def test_artifact_reference_does_not_mutate_sealed_artifact():
    """artifact.reference 记录引用关系，但不能修改已封印 Artifact 本体。"""
    ops = HumanLoopOperations()
    task = run(ops._seed_to_review_ready())
    art = run(ops.artifact_get(task.artifacts[0]))
    original_references = art.references

    run(ops.artifact_reference(art.id, by_task=task.id, as_="input"))

    assert art.references == original_references
    assert ops.store.artifact_references(art.id) == [
        ArtifactRef(task_id=task.id, as_="input")
    ]


def test_audit_log_never_deletes():
    """Audit 永不删 (spec §3.9)。"""
    ops = HumanLoopOperations()
    run(ops.task_create(principal="alice", goal="g"))
    assert ops.store.audit_log.count == 1
    # 无任何 API 能删除 audit
    assert not hasattr(ops.store.audit_log, "delete")
    assert not hasattr(ops.store.audit_log, "clear")


# ════════════════════════════════════════════════════════════
# §4 审计 (spec §4.2)
# ════════════════════════════════════════════════════════════


def test_every_mutating_operation_produces_audit():
    """每个会改变协议状态的操作都产生 audit action。"""
    ops = HumanLoopOperations()

    task = run(ops.task_create(principal="alice", goal="g"))
    run(ops.task_assign(task.id, "agent"))
    run(ops.task_start(task.id))
    ckpt = run(ops.checkpoint_raise(
        task_id=task.id,
        kind="approval",
        prompt="ok?",
        raised_by="agent",
    ))
    run(ops.checkpoint_resolve(ckpt.id, by="alice", action="approve"))
    art = run(ops.artifact_commit(
        task_id=task.id,
        type="report",
        payload=ArtifactPayload(kind="inline", uri="mem://v1", checksum="sha256:1"),
        produced_by="agent",
    ))
    review = run(ops.review_submit(
        task_id=task.id,
        artifact_id=art.id,
        reviewer="bob",
        verdict="changes_requested",
        requested_changes=("fix",),
    ))
    run(ops.review_comment(
        review.id,
        ReviewComment(anchor="line:1", body="extra"),
        by="bob",
    ))
    run(ops.artifact_reference(art.id, by_task=task.id, as_="input"))
    run(ops.ledger_write("project:p", "status", "draft", by=task.id))

    expiring_task = run(ops._seed_to_in_progress())
    expiring_ckpt = run(ops.checkpoint_raise(
        task_id=expiring_task.id,
        kind="approval",
        prompt="expire?",
        raised_by="agent",
    ))
    run(ops.checkpoint_expire(expiring_ckpt.id))

    delegated_task = run(ops.task_create(principal="alice", goal="delegate"))
    run(ops.ownership_transfer(delegated_task.id, "agent1", "handoff"))
    run(ops.ownership_delegate(delegated_task.id, "agent2", actor="agent1"))

    cancelled_task = run(ops.task_create(principal="alice", goal="cancel"))
    run(ops.task_cancel(cancelled_task.id, by="alice"))

    actions = {event.action for event in ops.store.audit_log.all()}
    assert {
        "task.created",
        "task.assigned",
        "task.started",
        "task.checkpoint.raised",
        "task.checkpoint.resolved",
        "task.checkpoint.expired",
        "ownership.transferred",
        "ownership.delegated",
        "review.submitted",
        "review.commented",
        "artifact.committed",
        "artifact.referenced",
        "ledger.written",
        "task.cancelled",
    }.issubset(actions)


def test_audit_seq_monotonic():
    """seq 单调递增 (spec §3.9)。"""
    ops = HumanLoopOperations()
    run(ops.task_create(principal="alice", goal="g"))
    run(ops.task_create(principal="bob", goal="g2"))
    all_events = ops.store.audit_log.all()
    seqs = [e.seq for e in all_events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)  # 唯一


def test_audit_replay_reconstructs_history():
    """replay 能回放 Task 完整历史 (spec §4.1)。"""
    ops = HumanLoopOperations()
    task = run(ops._seed_full_lifecycle())
    history = run(ops.audit_replay(task.id))
    assert len(history) > 5
    assert all(e.task_id == task.id for e in history)


# ════════════════════════════════════════════════════════════
# §5 层间契约 (spec §5.1) — HLP↔agent adapter
# ════════════════════════════════════════════════════════════


def test_task_assign_triggers_adapter_delegate():
    """task.assign 必须触发 agent adapter delegate (spec §5.1)。"""
    adapter = FakeAgentAdapter()
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops.task_create(principal="alice", goal="review PR"))
    run(ops.task_assign(task.id, "agent_devin"))

    delegates = adapter.calls_of("delegate")
    assert len(delegates) == 1
    # 铁律: TaskID 贯穿 (spec §5.1)
    assert delegates[0][1]["task_id"] == task.id
    run_id = delegates[0][1]["run_id"]
    assert adapter.task_of_run(run_id) == task.id


def test_checkpoint_raises_adapter_block():
    """checkpoint.raise 必须触发 agent adapter block (spec §5.1)。"""
    adapter = FakeAgentAdapter()
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops._seed_to_in_progress())
    ckpt = run(ops.checkpoint_raise(
        task_id=task.id, kind="approval", prompt="ok?", raised_by="agent"
    ))
    blocks = adapter.calls_of("block")
    assert len(blocks) == 1
    assert blocks[0][1]["checkpoint_id"] == ckpt.id


def test_checkpoint_resolve_triggers_adapter_resume():
    """checkpoint.resolve 必须触发 agent adapter resume (spec §5.1)。"""
    adapter = FakeAgentAdapter()
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops._seed_to_in_progress())
    ckpt = run(ops.checkpoint_raise(
        task_id=task.id, kind="approval", prompt="ok?", raised_by="agent"
    ))
    run(ops.checkpoint_resolve(ckpt.id, by="alice", action="approve"))
    resumes = adapter.calls_of("resume")
    assert len(resumes) == 1


def test_checkpoint_resolve_passes_full_resolution_payload_to_adapter():
    """resume payload 必须包含完整 resolution，而不只传 action/choice。"""
    adapter = FakeAgentAdapter()
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops._seed_to_in_progress())
    ckpt = run(ops.checkpoint_raise(
        task_id=task.id, kind="input", prompt="Need details", raised_by="agent"
    ))

    run(ops.checkpoint_resolve(
        ckpt.id,
        by="alice",
        action="provide",
        input="Use the conservative rollout plan.",
        comment="Keep blast radius small.",
    ))

    resumes = adapter.calls_of("resume")
    assert resumes[-1][1]["resolution"] == {
        "by": "alice",
        "action": "provide",
        "choice": None,
        "input": "Use the conservative rollout plan.",
        "reassign_to": None,
        "comment": "Keep blast radius small.",
    }


def test_checkpoint_resolve_returns_ownership_to_blocked_agent():
    """checkpoint.resolve 后 Task 回到 in_progress，ownership 也必须回到原 agent。"""
    ops = HumanLoopOperations()
    task = run(ops._seed_to_in_progress())
    agent = task.ownership.assignee

    ckpt = run(ops.checkpoint_raise(
        task_id=task.id, kind="approval", prompt="ok?", raised_by=agent
    ))
    assert task.state == "blocked"
    assert task.ownership.assignee == task.ownership.principal

    run(ops.checkpoint_resolve(ckpt.id, by=task.ownership.principal, action="approve"))

    assert task.state == "in_progress"
    assert task.ownership.assignee == agent
    assert task.ownership.chain[-1].from_ == task.ownership.principal
    assert task.ownership.chain[-1].to == agent
    assert task.ownership.chain[-1].via == "approve"


def test_taskid_threads_to_run():
    """TaskID 必须全栈贯穿到 Run (spec §5.1 铁律)。"""
    adapter = FakeAgentAdapter()
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops._seed_to_in_progress())
    run_id = ops.store.run_of_task(task.id)
    assert run_id is not None
    assert adapter.task_of_run(run_id) == task.id


def test_task_cancel_calls_adapter_before_completing_task():
    adapter = FailableAdapter("cancel")
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops._seed_to_in_progress())

    with pytest.raises(AgentAdapterError):
        run(ops.task_cancel(task.id, by="alice"))

    restored = run(ops.task_get(task.id))
    assert restored.state == "in_progress"
    assert not adapter.calls_of("cancel")


def test_ownership_transfer_handoff_updates_active_run_binding():
    adapter = FakeAgentAdapter()
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops._seed_to_in_progress())
    original_run = ops.store.run_of_task(task.id)

    run(ops.ownership_transfer(
        task.id,
        "agent_writer",
        "handoff",
        actor="agent_test",
    ))

    new_run = ops.store.run_of_task(task.id)
    assert original_run is not None
    assert new_run is not None
    assert new_run != original_run
    assert adapter.calls_of("handoff")[-1][1]["from_run"] == original_run
    assert adapter.task_of_run(new_run) == task.id


# ════════════════════════════════════════════════════════════
# §6 端到端闭环 — spec 附录 A "Review PR #1234"
# ════════════════════════════════════════════════════════════


def test_end_to_end_pr_review_scenario():
    """附录 A 完整时序: create→assign→checkpoint→resolve→
    artifact v1→review(changes)→artifact v2→review(approved)→completed。"""
    ops = HumanLoopOperations()
    alice = "user_alice"
    devin = "agent_devin"
    bob = "user_bob"

    # 1. task.create
    task = run(ops.task_create(
        principal=alice,
        goal="Review PR #1234 for security issues",
        type="code-review",
        acceptance_criteria=("All reviewer comments resolved",),
    ))
    assert task.state == "created"
    assert task.ownership.principal == alice
    assert task.ownership.assignee == alice

    # 2. task.assign (ownership alice→devin, adapter delegate)
    run(ops.task_assign(task.id, devin))
    assert task.state == "assigned"
    assert task.ownership.assignee == devin

    # 3. agent 开始执行
    run(ops.task_start(task.id))
    assert task.state == "in_progress"

    # 4. checkpoint.raise (agent 发现风险)
    ckpt = run(ops.checkpoint_raise(
        task_id=task.id,
        kind="choice",
        prompt="删 3 条旧索引，确认执行吗？",
        options=(
            CheckpointOption(id="a", label="删 A、B", risk="medium"),
            CheckpointOption(id="b", label="保留，只删 C", risk="low"),
        ),
        raised_by=devin,
    ))
    assert task.state == "blocked"
    assert task.ownership.assignee == alice  # 回退到 principal

    # 5. checkpoint.resolve (alice 选 b)
    run(ops.checkpoint_resolve(
        ckpt.id, by=alice, action="choose", choice="b",
        comment="保险起见保留 A、B",
    ))
    assert task.state == "in_progress"

    # 6. artifact.commit v1 → review_ready
    art1 = run(ops.artifact_commit(
        task_id=task.id, type="report",
        payload=ArtifactPayload(kind="inline", uri="mem://v1", checksum="sha256:1"),
        produced_by=devin,
    ))
    assert art1.version == "v1"
    assert task.state == "review_ready"

    # 7. review.submit (changes_requested → 返工)
    run(ops.review_submit(
        task_id=task.id, artifact_id=art1.id, reviewer=bob,
        verdict="changes_requested",
        comments=(ReviewComment(anchor="line:42", severity="blocker", body="null 检查"),),
        requested_changes=("修复 null 检查",),
    ))
    assert task.state == "in_progress"

    # 8. artifact.commit v2
    art2 = run(ops.artifact_commit(
        task_id=task.id, type="report",
        payload=ArtifactPayload(kind="inline", uri="mem://v2", checksum="sha256:2"),
        produced_by=devin,
    ))
    assert art2.version == "v2"
    assert task.state == "review_ready"

    # 9. review.submit (approved → accepted → completed)
    run(ops.review_submit(
        task_id=task.id, artifact_id=art2.id, reviewer=bob,
        verdict="approved",
    ))
    task = run(ops.task_get(task.id))
    assert task.state == "completed"

    # 10. ledger.write (沉淀"PR#1234 已通过")
    entry = run(ops.ledger_write(
        scope="project:web-revamp",
        key="pr.1234.status",
        value="approved",
        by=task.id,
    ))
    assert entry.value == "approved"

    # 11. audit replay 验证全程可回放
    history = run(ops.audit_replay(task.id))
    actions = [e.action for e in history]
    assert "task.created" in actions
    assert "task.assigned" in actions
    assert "task.checkpoint.raised" in actions
    assert "task.checkpoint.resolved" in actions
    assert "artifact.committed" in actions
    assert "review.submitted" in actions
    assert "ledger.written" in actions


def test_approved_review_auto_completes_task_and_audits_completion():
    ops = HumanLoopOperations()
    task = run(ops._seed_to_review_ready())

    run(ops.review_submit(
        task_id=task.id,
        artifact_id=task.artifacts[0],
        reviewer="bob",
        verdict="approved",
    ))

    restored = run(ops.task_get(task.id))
    history = run(ops.audit_replay(task.id))
    assert restored.state == "completed"
    assert [event.action for event in history][-2:] == [
        "review.submitted",
        "task.completed",
    ]


# ════════════════════════════════════════════════════════════
# §7 Ownership 流转 (spec §3.5)
# ════════════════════════════════════════════════════════════


def test_ownership_chain_is_append_only():
    """ownership.chain 是 append-only (spec §3.5)。"""
    ops = HumanLoopOperations()
    task = run(ops.task_create(principal="alice", goal="g"))
    run(ops.task_assign(task.id, "agent"))
    chain_after_assign = task.ownership.chain
    assert len(chain_after_assign) == 1
    assert chain_after_assign[0].via == "assign"

    run(ops.task_start(task.id))
    run(ops.checkpoint_raise(
        task_id=task.id, kind="approval", prompt="?", raised_by="agent"
    ))
    chain_after_ckpt = task.ownership.chain
    assert len(chain_after_ckpt) == 2
    assert chain_after_ckpt[1].via == "checkpoint"


def test_ownership_principal_never_changes():
    """principal 永不变 (spec §2.1)。"""
    ops = HumanLoopOperations()
    task = run(ops.task_create(principal="alice", goal="g"))
    original_principal = task.ownership.principal
    run(ops.task_assign(task.id, "agent"))
    run(ops.task_start(task.id))
    run(ops.checkpoint_raise(
        task_id=task.id, kind="approval", prompt="?", raised_by="agent"
    ))
    assert task.ownership.principal == original_principal


def test_artifact_commit_moves_ownership_to_principal_for_review():
    """review_ready 是人侧状态，artifact.commit 后 assignee 应回到 principal。"""
    ops = HumanLoopOperations()
    task = run(ops._seed_to_in_progress())
    agent = task.ownership.assignee

    run(ops.artifact_commit(
        task_id=task.id,
        type="report",
        payload=ArtifactPayload(kind="inline", uri="mem://v1", checksum="sha256:1"),
        produced_by=agent,
    ))

    assert task.state == "review_ready"
    assert task.ownership.assignee == task.ownership.principal


def test_review_changes_requested_returns_ownership_to_agent():
    """changes_requested 后 Task 回到 in_progress，assignee 应回到交付 agent。"""
    ops = HumanLoopOperations()
    task = run(ops._seed_to_review_ready())
    agent = task.ownership.chain[-1].from_

    run(ops.review_submit(
        task_id=task.id,
        artifact_id=task.artifacts[0],
        reviewer="bob",
        verdict="changes_requested",
        requested_changes=("fix",),
    ))

    assert task.state == "in_progress"
    assert task.ownership.assignee == agent


def test_delegation_requires_delegable():
    """delegable=false 时不能 delegate (spec §3.5)。"""
    ops = HumanLoopOperations()
    task = run(ops.task_create(principal="alice", goal="g"))
    task.ownership.delegable = False
    run(ops.task_assign(task.id, "agent1"))
    with pytest.raises(ProtocolError) as e:
        run(ops.ownership_delegate(task.id, "agent2", actor="agent1"))
    assert e.value.code == "PRECONDITION_FAILED"


# ════════════════════════════════════════════════════════════
# §8 Artifact 版本链 (spec §3.7)
# ════════════════════════════════════════════════════════════


def test_artifact_versions_increment():
    ops = HumanLoopOperations()
    task = run(ops._seed_to_review_ready())
    # review changes → in_progress → 再 commit
    run(ops.review_submit(
        task_id=task.id, artifact_id=task.artifacts[0],
        reviewer="bob", verdict="changes_requested",
        requested_changes=("fix",),
    ))
    art2 = run(ops.artifact_commit(
        task_id=task.id, type="report",
        payload=ArtifactPayload(kind="inline", uri="mem://v2", checksum="sha256:2"),
        produced_by="agent",
    ))
    assert art2.version == "v2"


def test_artifact_get_by_version():
    ops = HumanLoopOperations()
    task = run(ops._seed_full_lifecycle())
    # 取第一个 artifact
    art_id = task.artifacts[0]
    v1 = run(ops.artifact_get(art_id, "v1"))
    assert v1.version == "v1"


def test_ledger_history_is_append_only():
    """Ledger 对同 key 多次写入保留完整历史，read 使用 last-write-wins。"""
    ops = HumanLoopOperations()
    task = run(ops.task_create(principal="alice", goal="g"))

    first = run(ops.ledger_write("project:p", "status", "draft", by=task.id))
    second = run(ops.ledger_write("project:p", "status", "approved", by=task.id))

    assert run(ops.ledger_read("project:p", "status")) == "approved"
    assert run(ops.ledger_history("project:p", "status")) == [first, second]


# ════════════════════════════════════════════════════════════
# §9 分层纪律 - HLP 不依赖内置 harness
# ════════════════════════════════════════════════════════════


def test_loop2_does_not_import_lower_layers():
    """HLP 参考实现不应感知自研下层 runtime。

    注: HLP 只通过 adapter 接入外部 harness，证明协议层可以独立存在。
    这是 spec §1.2 适用范围的体现。
    """
    import loops.loop2 as l2
    assert not hasattr(l2, "loop0")
    assert not hasattr(l2, "loop1")
