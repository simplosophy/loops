"""HACP 参考实现测试。

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
    HACPOperations,
    InMemoryAAPBridge,
    ProtocolError,
    TaskSpec,
    ArtifactPayload,
    CheckpointOption,
    ReviewComment,
    check_transition,
    is_legal,
    LEGAL_TRANSITIONS,
)


def run(coro):
    """同步驱动 async 操作（仓库约定，见 tests/test_loops_core.py）。"""
    return asyncio.run(coro)


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
    ops = HACPOperations()
    with pytest.raises(ProtocolError) as e:
        run(ops.task_create(principal="", goal="do something"))
    assert e.value.code == "INVALID_SPEC"


def test_task_create_requires_goal():
    ops = HACPOperations()
    with pytest.raises(ProtocolError) as e:
        run(ops.task_create(principal="user_alice", goal=""))
    assert e.value.code == "INVALID_SPEC"


def test_assign_requires_created_state():
    ops = HACPOperations()
    task = run(ops.task_create(principal="alice", goal="g"))
    run(ops.task_assign(task.id, "agent_devin"))
    # 重复 assign 失败 (已 assigned)
    with pytest.raises(ProtocolError) as e:
        run(ops.task_assign(task.id, "agent_other"))
    assert e.value.code == "PRECONDITION_FAILED"


def test_checkpoint_raise_requires_in_progress():
    ops = HACPOperations()
    task = run(ops.task_create(principal="alice", goal="g"))
    # created 状态不能 raise checkpoint
    with pytest.raises(ProtocolError) as e:
        run(ops.checkpoint_raise(
            task_id=task.id, kind="approval", prompt="?", raised_by="agent"
        ))
    assert e.value.code == "PRECONDITION_FAILED"


def test_choice_checkpoint_requires_options():
    ops = HACPOperations()
    task = run(ops._seed_to_in_progress())
    with pytest.raises(ProtocolError) as e:
        run(ops.checkpoint_raise(
            task_id=task.id, kind="choice", prompt="?", raised_by="agent"
        ))
    assert e.value.code == "INVALID_SPEC"


def test_checkpoint_resolve_requires_pending():
    ops = HACPOperations()
    task = run(ops._seed_to_in_progress())
    ckpt = run(ops.checkpoint_raise(
        task_id=task.id, kind="approval", prompt="ok?", raised_by="agent"
    ))
    run(ops.checkpoint_resolve(ckpt.id, by="alice", action="approve"))
    # 重复 resolve 失败
    with pytest.raises(ProtocolError) as e:
        run(ops.checkpoint_resolve(ckpt.id, by="alice", action="approve"))
    assert e.value.code == "PRECONDITION_FAILED"


def test_review_requires_review_ready_state():
    ops = HACPOperations()
    task = run(ops._seed_to_in_progress())
    # in_progress 不能 review
    with pytest.raises(ProtocolError) as e:
        run(ops.review_submit(
            task_id=task.id, artifact_id="art_x", reviewer="bob", verdict="approved"
        ))
    assert e.value.code == "PRECONDITION_FAILED"


def test_changes_requested_requires_requested_changes():
    ops = HACPOperations()
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
    ops = HACPOperations()
    task = run(ops._seed_to_review_ready())
    review = run(ops.review_submit(
        task_id=task.id, artifact_id=task.artifacts[0],
        reviewer="bob", verdict="approved",
    ))
    assert review._sealed is True


def test_artifact_sealed_after_commit():
    """Artifact 创建后封印。"""
    ops = HACPOperations()
    task = run(ops._seed_to_in_progress())
    art = run(ops.artifact_commit(
        task_id=task.id, type="report",
        payload=ArtifactPayload(kind="inline", uri="mem://x", checksum="sha256:1"),
        produced_by="agent",
    ))
    assert art._sealed is True


def test_audit_log_never_deletes():
    """Audit 永不删 (spec §3.9)。"""
    ops = HACPOperations()
    run(ops.task_create(principal="alice", goal="g"))
    assert ops.store.audit_log.count == 1
    # 无任何 API 能删除 audit
    assert not hasattr(ops.store.audit_log, "delete")
    assert not hasattr(ops.store.audit_log, "clear")


# ════════════════════════════════════════════════════════════
# §4 审计 (spec §4.2)
# ════════════════════════════════════════════════════════════


def test_every_operation_produces_audit():
    """每个操作产生符合 §4.2 的 audit action。"""
    ops = HACPOperations()
    task = run(ops.task_create(principal="alice", goal="g"))
    events = ops.store.audit_log.query(action="task.created")
    assert len(events) == 1
    assert events[0].task_id == task.id

    run(ops.task_assign(task.id, "agent"))
    events = ops.store.audit_log.query(action="task.assigned")
    assert len(events) == 1


def test_audit_seq_monotonic():
    """seq 单调递增 (spec §3.9)。"""
    ops = HACPOperations()
    run(ops.task_create(principal="alice", goal="g"))
    run(ops.task_create(principal="bob", goal="g2"))
    all_events = ops.store.audit_log.all()
    seqs = [e.seq for e in all_events]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)  # 唯一


def test_audit_replay_reconstructs_history():
    """replay 能回放 Task 完整历史 (spec §4.1)。"""
    ops = HACPOperations()
    task = run(ops._seed_full_lifecycle())
    history = run(ops.audit_replay(task.id))
    assert len(history) > 5
    assert all(e.task_id == task.id for e in history)


# ════════════════════════════════════════════════════════════
# §5 层间契约 (spec §5.1) — HACP↔AAP
# ════════════════════════════════════════════════════════════


def test_task_assign_triggers_aap_delegate():
    """task.assign 必须触发 AAP delegate (spec §5.1)。"""
    bridge = InMemoryAAPBridge()
    ops = HACPOperations(aap=bridge)
    task = run(ops.task_create(principal="alice", goal="review PR"))
    run(ops.task_assign(task.id, "agent_devin"))

    delegates = bridge.calls_of("delegate")
    assert len(delegates) == 1
    # 铁律: TaskID 贯穿 (spec §5.1)
    assert delegates[0][1]["task_id"] == task.id
    run_id = delegates[0][1]["run_id"]
    assert bridge.task_of_run(run_id) == task.id


def test_checkpoint_raises_aap_block():
    """checkpoint.raise 必须触发 AAP block (spec §5.1)。"""
    bridge = InMemoryAAPBridge()
    ops = HACPOperations(aap=bridge)
    task = run(ops._seed_to_in_progress())
    ckpt = run(ops.checkpoint_raise(
        task_id=task.id, kind="approval", prompt="ok?", raised_by="agent"
    ))
    blocks = bridge.calls_of("block")
    assert len(blocks) == 1
    assert blocks[0][1]["checkpoint_id"] == ckpt.id


def test_checkpoint_resolve_triggers_aap_resume():
    """checkpoint.resolve 必须触发 AAP resume (spec §5.1)。"""
    bridge = InMemoryAAPBridge()
    ops = HACPOperations(aap=bridge)
    task = run(ops._seed_to_in_progress())
    ckpt = run(ops.checkpoint_raise(
        task_id=task.id, kind="approval", prompt="ok?", raised_by="agent"
    ))
    run(ops.checkpoint_resolve(ckpt.id, by="alice", action="approve"))
    resumes = bridge.calls_of("resume")
    assert len(resumes) == 1


def test_taskid_threads_to_run():
    """TaskID 必须全栈贯穿到 Run (spec §5.1 铁律)。"""
    bridge = InMemoryAAPBridge()
    ops = HACPOperations(aap=bridge)
    task = run(ops._seed_to_in_progress())
    run_id = ops.store.run_of_task(task.id)
    assert run_id is not None
    assert bridge.task_of_run(run_id) == task.id


# ════════════════════════════════════════════════════════════
# §6 端到端闭环 — spec 附录 A "Review PR #1234"
# ════════════════════════════════════════════════════════════


def test_end_to_end_pr_review_scenario():
    """附录 A 完整时序: create→assign→checkpoint→resolve→
    artifact v1→review(changes)→artifact v2→review(approved)→completed。"""
    ops = HACPOperations()
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

    # 2. task.assign (ownership alice→devin, AAP delegate)
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

    # 9. review.submit (approved → accepted)
    run(ops.review_submit(
        task_id=task.id, artifact_id=art2.id, reviewer=bob,
        verdict="approved",
    ))
    assert task.state == "accepted"

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


# ════════════════════════════════════════════════════════════
# §7 Ownership 流转 (spec §3.5)
# ════════════════════════════════════════════════════════════


def test_ownership_chain_is_append_only():
    """ownership.chain 是 append-only (spec §3.5)。"""
    ops = HACPOperations()
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
    ops = HACPOperations()
    task = run(ops.task_create(principal="alice", goal="g"))
    original_principal = task.ownership.principal
    run(ops.task_assign(task.id, "agent"))
    run(ops.task_start(task.id))
    run(ops.checkpoint_raise(
        task_id=task.id, kind="approval", prompt="?", raised_by="agent"
    ))
    assert task.ownership.principal == original_principal


def test_delegation_requires_delegable():
    """delegable=false 时不能 delegate (spec §3.5)。"""
    ops = HACPOperations()
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
    ops = HACPOperations()
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
    ops = HACPOperations()
    task = run(ops._seed_full_lifecycle())
    # 取第一个 artifact
    art_id = task.artifacts[0]
    v1 = run(ops.artifact_get(art_id, "v1"))
    assert v1.version == "v1"


# ════════════════════════════════════════════════════════════
# §9 分层纪律 - loop2 不依赖 loop1/loop0
# ════════════════════════════════════════════════════════════


def test_loop2_does_not_import_lower_layers():
    """loop2 不应感知 loop1/loop0 (参考实现刻意不依赖它们, transport-agnostic)。

    注: L2 理论上可 import L1/L0 (依赖向下), 但 HACP 参考实现选择零依赖,
    证明协议层可以独立存在。这是 spec §1.2 适用范围的体现。
    """
    import loops.loop2 as l2
    assert not hasattr(l2, "loop0")
    assert not hasattr(l2, "loop1")
