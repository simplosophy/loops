from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .adapters import AgentAdapter, FakeAgentAdapter
from .objects import (
    Artifact,
    ArtifactPayload,
    ArtifactProvenance,
    ArtifactRef,
    Checkpoint,
    CheckpointOption,
    CheckpointResolution,
    Evidence,
    InputRef,
    Ledger,
    LedgerEntry,
    Ownership,
    Review,
    ReviewComment,
    Task,
    TaskSpec,
)
from .state_machine import check_transition
from .store import HumanLoopStore
from .types import (
    CheckpointKind,
    CheckpointResolutionAction,
    ProtocolError,
    ReviewVerdict,
    TaskState,
)
from ._ids import gen_review_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ════════════════════════════════════════════════════════════
# HLP 协议操作 (spec §4)
#
# 每个操作遵循统一结构：
#   1. 前置条件校验 (spec §4.3) → 失败抛 ProtocolError
#   2. 状态转移 (spec §3.3)
#   3. audit 记录 (spec §4.2)
#   4. 层间契约调用 (spec §5.1, 如涉及 agent adapter)
#
# 全部操作都是 async——为未来 transport 留口子 (spec §7.1)。
# ════════════════════════════════════════════════════════════


@dataclass
class HumanLoopOperations:
    """HLP 协议操作入口 (spec §4.1, 共 21 个)。

    持有 store + audit + agent adapter，是协议层的 facade。
    上层 (transport/CLI) 调用这里；本类不感知 transport。
    """

    store: HumanLoopStore = field(default_factory=HumanLoopStore)
    adapter: AgentAdapter = field(default_factory=FakeAgentAdapter)

    # ────────────────── Task (spec §4.1) ──────────────────

    async def task_create(
        self,
        *,
        principal: str,
        goal: str,
        type: str = "",
        acceptance_criteria: tuple[str, ...] = (),
        inputs: tuple[InputRef, ...] = (),
    ) -> Task:
        """task.create (spec §4.1)。state=created."""
        if not principal:
            raise ProtocolError("INVALID_SPEC", "principal is required")
        self._require_human_actor(principal, "principal")
        if not goal:
            raise ProtocolError("INVALID_SPEC", "goal is required")

        spec = TaskSpec(
            goal=goal,
            acceptance_criteria=acceptance_criteria,
            inputs=inputs,
        )
        task = Task(
            type=type,
            spec=spec,
            ownership=Ownership(principal=principal, assignee=principal),
            state="created",
        )
        self.store.put_task(task)
        self._audit(
            actor=principal,
            action="task.created",
            subject=("task", task.id),
            task_id=task.id,
        )
        return task

    async def task_assign(
        self,
        task_id: str,
        agent_id: str,
        *,
        capability: str = "",
        input: dict[str, Any] | None = None,
    ) -> Task:
        """task.assign (spec §4.1)。created→assigned，ownership 转 agent。"""
        task = self.store._get_task_for_update(task_id)
        self._require_state(task, "created")

        run_id = await self.adapter.delegate(
            task_id=task_id,
            agent_id=agent_id,
            capability=capability,
            input=input or {"goal": task.spec.goal},
        )

        # ownership 转移 (spec §3.5)
        task.ownership = task.ownership.transfer(agent_id, via="assign")
        # 状态转移
        check_transition(task.state, "assigned")
        task.state = "assigned"
        self._audit(
            actor=task.ownership.principal,
            action="task.assigned",
            subject=("task", task.id),
            task_id=task.id,
            after={"assignee": agent_id},
        )
        self.store.bind_run(task_id, run_id)
        return task

    async def task_start(self, task_id: str) -> Task:
        """agent 开始执行：assigned→in_progress。

        spec §3.3 隐含转移（agent runtime 启动）。非 spec §4.1 显式操作，
        但状态机需要它。参考实现暴露此方法。
        """
        task = self.store._get_task_for_update(task_id)
        self._require_state(task, "assigned")
        check_transition(task.state, "in_progress")
        task.state = "in_progress"
        self._audit(
            actor=task.ownership.assignee,
            action="task.started",
            subject=("task", task.id),
            task_id=task_id,
        )
        return task

    async def task_cancel(self, task_id: str, by: str) -> Task:
        """task.cancel (spec §4.1)。→completed (中止)。"""
        task = self.store._get_task_for_update(task_id)
        if task.state in ("completed", "rejected"):
            raise ProtocolError(
                "PRECONDITION_FAILED",
                f"cannot cancel terminal task in state {task.state!r}",
            )
        run_id = self.store.run_of_task(task_id)
        if run_id is not None:
            await self.adapter.cancel(run_id, f"cancelled by {by}")
        check_transition(task.state, "completed")
        task.state = "completed"
        self._audit(
            actor=by,
            action="task.cancelled",
            subject=("task", task.id),
            task_id=task_id,
        )
        return task

    async def task_get(self, task_id: str) -> Task:
        """task.get (spec §4.1)。"""
        return self.store.get_task(task_id)

    async def task_list(self) -> list[Task]:
        """task.list (spec §4.1)。"""
        return self.store.list_tasks()

    # ────────────────── Checkpoint (spec §4.1) ──────────────────

    async def checkpoint_raise(
        self,
        *,
        task_id: str,
        kind: CheckpointKind,
        prompt: str,
        options: tuple[CheckpointOption, ...] = (),
        context: tuple[Evidence, ...] = (),
        raised_by: str,
    ) -> Checkpoint:
        """checkpoint.raise (spec §4.1)。in_progress→blocked。"""
        task = self.store._get_task_for_update(task_id)
        self._require_state(task, "in_progress")
        if kind == "choice" and not options:
            raise ProtocolError("INVALID_SPEC", "choice checkpoint requires options")

        ckpt = Checkpoint(
            task_id=task_id,
            kind=kind,
            prompt=prompt,
            options=options,
            context=context,
            state="pending",
        )
        ckpt_raised_by = raised_by
        run_id = self.store.run_of_task(task_id)
        if run_id is not None:
            await self.adapter.block(run_id, ckpt.id, prompt)

        self.store.put_checkpoint(ckpt)
        task.checkpoints.append(ckpt.id)

        # 状态联动 (spec §3.4)
        check_transition(task.state, "blocked")
        task.state = "blocked"
        # ownership 回退到 principal (spec §2.1)
        task.ownership = task.ownership.transfer(
            task.ownership.principal, via="checkpoint"
        )

        self._audit(
            actor=ckpt_raised_by,
            action="task.checkpoint.raised",
            subject=("checkpoint", ckpt.id),
            task_id=task_id,
        )
        return ckpt

    async def checkpoint_resolve(
        self,
        ckpt_id: str,
        *,
        by: str,
        action: CheckpointResolutionAction,
        choice: str | None = None,
        input: str | None = None,
        reassign_to: str | None = None,
        comment: str | None = None,
    ) -> Checkpoint:
        """checkpoint.resolve (spec §4.1)。blocked→in_progress (approve/provide)
        或 blocked→completed (reject)。"""
        ckpt = self.store._get_checkpoint_for_update(ckpt_id)
        if ckpt.state != "pending":
            raise ProtocolError(
                "PRECONDITION_FAILED",
                f"cannot resolve checkpoint in state {ckpt.state!r}",
            )
        task = self.store._get_task_for_update(ckpt.task_id)
        self._require_state(task, "blocked")
        self._require_human_actor(by, "checkpoint resolver")
        self._validate_checkpoint_resolution(
            ckpt,
            action=action,
            choice=choice,
            input=input,
            reassign_to=reassign_to,
        )

        resolution = CheckpointResolution(
            by=by,
            action=action,
            choice=choice,
            input=input,
            reassign_to=reassign_to,
            comment=comment,
        )
        resume_payload = self._resolution_payload(resolution)
        run_id = self.store.run_of_task(task.id)
        if run_id is not None:
            await self.adapter.resume(run_id, resume_payload)

        ckpt.resolution = resolution
        ckpt.state = "resolved"

        # action 决定 task 去向 (spec §3.4)
        if action == "reject":
            check_transition(task.state, "completed")
            task.state = "completed"
        else:  # approve / choose / provide / reassign
            check_transition(task.state, "in_progress")
            task.state = "in_progress"
            # ownership 回 agent
            target_agent = reassign_to or self._last_assignee_before(
                task,
                to=task.ownership.principal,
                via="checkpoint",
            )
            if target_agent is not None and task.ownership.assignee != target_agent:
                task.ownership = task.ownership.transfer(target_agent, via="approve")

        self._audit(
            actor=by,
            action="task.checkpoint.resolved",
            subject=("checkpoint", ckpt.id),
            task_id=task.id,
            after=resume_payload,
        )
        return ckpt

    async def checkpoint_expire(self, ckpt_id: str) -> Checkpoint:
        """checkpoint.expire (spec §4.1, §7.2)。超时自动失效。"""
        ckpt = self.store._get_checkpoint_for_update(ckpt_id)
        if ckpt.state != "pending":
            raise ProtocolError(
                "PRECONDITION_FAILED",
                f"cannot expire checkpoint in state {ckpt.state!r}",
            )
        ckpt.state = "expired"
        task = self.store._get_task_for_update(ckpt.task_id)
        # 超时后 task 保持 blocked (spec §7.2 开放议题，参考实现选纯挂起)
        self._audit(
            actor="system",
            action="task.checkpoint.expired",
            subject=("checkpoint", ckpt.id),
            task_id=task.id,
        )
        return ckpt

    # ────────────────── Ownership (spec §4.1) ──────────────────

    async def ownership_transfer(
        self,
        task_id: str,
        to: str,
        via: str,
        *,
        actor: str = "system",
    ) -> Task:
        """ownership.transfer (spec §4.1, §3.5)。内部转移 assignee。"""
        task = self.store._get_task_for_update(task_id)
        if task.is_terminal:
            raise ProtocolError(
                "PRECONDITION_FAILED",
                "cannot transfer ownership of terminal task",
            )
        run_id = self.store.run_of_task(task_id)
        new_run_id: str | None = None
        if via == "handoff" and run_id is not None and to != task.ownership.assignee:
            new_run_id = await self.adapter.handoff(
                run_id,
                to,
                {
                    "task_id": task.id,
                    "from": task.ownership.assignee,
                    "to": to,
                    "via": via,
                },
            )
        task.ownership = task.ownership.transfer(to, via=via)  # type: ignore[arg-type]
        if new_run_id is not None:
            self.store.bind_run(task_id, new_run_id)
        self._audit(
            actor=actor,
            action="ownership.transferred",
            subject=("task", task.id),
            task_id=task.id,
            after={"assignee": to, "via": via},
        )
        return task

    async def ownership_delegate(
        self,
        task_id: str,
        to_agent: str,
        *,
        actor: str,
    ) -> Task:
        """ownership.delegate (spec §4.1, §3.5)。agent 向下委派，需 delegable。"""
        task = self.store._get_task_for_update(task_id)
        if not task.ownership.delegable:
            raise ProtocolError(
                "PRECONDITION_FAILED",
                "task is not delegable (ownership.delegable=false)",
            )
        if task.is_terminal:
            raise ProtocolError(
                "PRECONDITION_FAILED",
                "cannot delegate terminal task",
            )
        parent_run = self.store.run_of_task(task_id)
        run_id = await self.adapter.delegate(
            task_id=task_id,
            agent_id=to_agent,
            capability="",
            input={"goal": task.spec.goal},
            parent_run=parent_run,
        )
        # 链式委派：记录到 chain (spec §7.3)
        task.ownership = task.ownership.transfer(to_agent, via="assign")
        self.store.bind_run(task_id, run_id)
        self._audit(
            actor=actor,
            action="ownership.delegated",
            subject=("task", task.id),
            task_id=task.id,
            after={"delegatee": to_agent},
        )
        return task

    # ────────────────── Review (spec §4.1) ──────────────────

    async def review_submit(
        self,
        *,
        task_id: str,
        artifact_id: str,
        reviewer: str,
        verdict: ReviewVerdict,
        comments: tuple[ReviewComment, ...] = (),
        requested_changes: tuple[str, ...] = (),
    ) -> Review:
        """review.submit (spec §4.1, §3.6)。

        - review_ready/under_review → accepted (approved)
        - review_ready/under_review → in_progress (changes_requested, 返工)
        - review_ready/under_review → rejected (rejected)
        """
        task = self.store._get_task_for_update(task_id)
        if task.state not in ("review_ready", "under_review"):
            raise ProtocolError(
                "PRECONDITION_FAILED",
                f"cannot review task in state {task.state!r}",
            )
        if verdict == "changes_requested" and not requested_changes:
            raise ProtocolError(
                "INVALID_SPEC",
                "changes_requested verdict requires requested_changes",
            )
        self._require_human_actor(reviewer, "reviewer")
        if artifact_id not in task.artifacts:
            raise ProtocolError(
                "PRECONDITION_FAILED",
                f"artifact {artifact_id} is not an output of task {task_id}",
            )
        # 确保 artifact 存在
        self.store.get_artifact(artifact_id)

        review = Review(
            id=gen_review_id(),
            task_id=task_id,
            artifact_id=artifact_id,
            reviewer=reviewer,
            verdict=verdict,
            comments=comments,
            requested_changes=requested_changes,
        ).seal()
        self.store.put_review(review)

        # 状态联动 (spec §3.6): 先 review_ready→under_review, 再按 verdict 转
        if task.state == "review_ready":
            check_transition(task.state, "under_review")
            task.state = "under_review"

        if verdict == "approved":
            check_transition(task.state, "accepted")
            task.state = "accepted"
            check_transition(task.state, "completed")
            task.state = "completed"
        elif verdict == "changes_requested":
            check_transition(task.state, "in_progress")
            task.state = "in_progress"
            target_agent = self._last_assignee_before(
                task,
                to=task.ownership.principal,
                via="handoff",
            )
            if target_agent is not None and task.ownership.assignee != target_agent:
                task.ownership = task.ownership.transfer(target_agent, via="reject")
        else:  # rejected
            check_transition(task.state, "rejected")
            task.state = "rejected"

        self._audit(
            actor=reviewer,
            action="review.submitted",
            subject=("review", review.id),
            task_id=task_id,
            after={"verdict": verdict},
        )
        if verdict == "approved":
            self._audit(
                actor="system",
                action="task.completed",
                subject=("task", task.id),
                task_id=task_id,
                after={"review_id": review.id},
            )
        return review

    async def review_comment(
        self,
        review_id: str,
        comment: ReviewComment,
        *,
        by: str,
    ) -> Review:
        """review.comment (spec §4.1)。追加批注。

        注意：spec §2.3 说 Review 提交后不可变——这里"追加批注"指
        产生新记录而非改原 review。参考实现存新 Review。
        """
        original = self.store._get_review_for_update(review_id)
        new_review = Review(
            id=gen_review_id(),
            task_id=original.task_id,
            artifact_id=original.artifact_id,
            reviewer=by,
            verdict=original.verdict,
            comments=(comment,),
            at=_now(),
        ).seal()
        self.store.put_review(new_review)
        self._audit(
            actor=by,
            action="review.commented",
            subject=("review", new_review.id),
            task_id=original.task_id,
        )
        return new_review

    # ────────────────── Artifact (spec §4.1) ──────────────────

    async def artifact_commit(
        self,
        *,
        task_id: str,
        type: str,
        payload: ArtifactPayload,
        produced_by: str,
        parent_version: str | None = None,
    ) -> Artifact:
        """artifact.commit (spec §4.1, §3.7)。

        in_progress→review_ready (首次交付) 或
        under_review→in_progress 不在此处理（review 状态机管）。
        参考：in_progress 状态下 commit 触发 review_ready。
        """
        task = self.store._get_task_for_update(task_id)
        # spec §4.3: artifact.commit 要求 in_progress 或返工态
        if task.state not in ("in_progress",):
            raise ProtocolError(
                "PRECONDITION_FAILED",
                f"cannot commit artifact in task state {task.state!r}",
            )

        # 版本号：该 task 产出的 artifact 数 +1 (spec §3.7)
        version = f"v{len(task.artifacts) + 1}"

        art = Artifact(
            type=type,
            provenance=ArtifactProvenance(produced_by=task_id),
            version=version,
            parent_version=parent_version,
            payload=payload,
        ).seal()
        self.store.put_artifact(art)
        task.artifacts.append(art.id)

        # 首次交付触发 review_ready (spec §3.3)
        check_transition(task.state, "review_ready")
        task.state = "review_ready"
        if task.ownership.assignee != task.ownership.principal:
            task.ownership = task.ownership.transfer(task.ownership.principal, via="handoff")

        self._audit(
            actor=produced_by,
            action="artifact.committed",
            subject=("artifact", art.id),
            task_id=task_id,
            after={"version": version},
        )
        return art

    async def artifact_get(self, art_id: str, version: str | None = None) -> Artifact:
        """artifact.get (spec §4.1)。"""
        return self.store.get_artifact(art_id, version)

    async def artifact_reference(
        self,
        art_id: str,
        *,
        by_task: str,
        as_: str = "input",
    ) -> Artifact:
        """artifact.reference (spec §4.1)。被 Task 引用为输入。"""
        art = self.store.get_artifact(art_id)
        self.store.add_artifact_reference(art.id, ArtifactRef(task_id=by_task, as_=as_))
        self._audit(
            actor=by_task,
            action="artifact.referenced",
            subject=("artifact", art.id),
            task_id=by_task,
        )
        return art

    # ────────────────── Ledger (spec §4.1) ──────────────────

    async def ledger_read(self, scope: str, key: str) -> Any | None:
        """ledger.read (spec §4.1, §3.8)。"""
        ledger = self.store._find_ledger_by_scope_for_update(scope)
        if ledger is None:
            return None
        return ledger.read(key)

    async def ledger_write(
        self,
        scope: str,
        key: str,
        value: Any,
        *,
        by: str,
    ) -> LedgerEntry:
        """ledger.write (spec §4.1, §3.8)。append-only + audit。"""
        ledger = self.store.get_or_create_ledger(scope)
        entry = ledger.write(key, value, by=by)
        self._audit(
            actor=by,
            action="ledger.written",
            subject=("ledger", ledger.id),
            task_id=by,
            after={"key": key, "scope": scope},
        )
        return entry

    async def ledger_history(self, scope: str, key: str) -> list[LedgerEntry]:
        """ledger.history (spec §4.1)。"""
        ledger = self.store._find_ledger_by_scope_for_update(scope)
        if ledger is None:
            return []
        return ledger.history(key)

    # ────────────────── Audit (spec §4.1, 无写操作) ──────────────────

    async def audit_query(
        self,
        *,
        task_id: str | None = None,
        actor: str | None = None,
        action: str | None = None,
    ) -> list:
        """audit.query (spec §4.1)。"""
        return self.store.audit_log.query(task_id=task_id, actor=actor, action=action)

    async def audit_replay(self, task_id: str) -> list:
        """audit.replay (spec §4.1)。回放某 Task 完整历史。"""
        return self.store.audit_log.replay(task_id)

    # ────────────────── 内部辅助 ──────────────────

    def _require_state(self, task: Task, expected: TaskState) -> None:
        """前置条件：要求 task 处于某状态 (spec §4.3)。"""
        if task.state != expected:
            raise ProtocolError(
                "PRECONDITION_FAILED",
                f"task {task.id} expected state {expected!r}, got {task.state!r}",
            )

    def _audit(
        self,
        *,
        actor: str,
        action: str,
        subject: tuple[str, str] = ("", ""),
        task_id: str | None = None,
        before: Any = None,
        after: Any = None,
    ) -> None:
        """统一 audit 记录 (spec §4.2)。"""
        self.store.audit_log.append(
            actor=actor,
            action=action,
            subject=subject,
            task_id=task_id,
            before=before,
            after=after,
        )

    @staticmethod
    def _is_human(actor: str) -> bool:
        return bool(actor) and not actor.startswith("agent_")

    @staticmethod
    def _is_agent(actor: str) -> bool:
        return actor.startswith("agent_")

    def _require_human_actor(self, actor: str, role: str) -> None:
        if not self._is_human(actor):
            raise ProtocolError("UNAUTHORIZED", f"{role} must be a human actor")

    def _validate_checkpoint_resolution(
        self,
        ckpt: Checkpoint,
        *,
        action: CheckpointResolutionAction,
        choice: str | None,
        input: str | None,
        reassign_to: str | None,
    ) -> None:
        if action == "choose":
            option_ids = {option.id for option in ckpt.options}
            if not choice or choice not in option_ids:
                raise ProtocolError(
                    "INVALID_SPEC",
                    "choose resolution requires a choice from checkpoint options",
                )
        elif action == "provide":
            if not input:
                raise ProtocolError(
                    "INVALID_SPEC",
                    "provide resolution requires input",
                )
        elif action == "reassign":
            if not reassign_to or not self._is_agent(reassign_to):
                raise ProtocolError(
                    "INVALID_SPEC",
                    "reassign resolution requires an agent assignee",
                )

    @staticmethod
    def _resolution_payload(resolution: CheckpointResolution) -> dict[str, Any]:
        return {
            "by": resolution.by,
            "action": resolution.action,
            "choice": resolution.choice,
            "input": resolution.input,
            "reassign_to": resolution.reassign_to,
            "comment": resolution.comment,
        }

    @staticmethod
    def _last_assignee_before(
        task: Task,
        *,
        to: str,
        via: str,
    ) -> str | None:
        for transfer in reversed(task.ownership.chain):
            if transfer.to == to and transfer.via == via:
                return transfer.from_
        return None

    # ────────────────── 测试/演示辅助 (非 spec 操作) ──────────────────

    async def _seed_to_in_progress(self) -> Task:
        """快速构造一个 in_progress 的 task, 供测试用。"""
        task = await self.task_create(principal="alice", goal="test goal")
        await self.task_assign(task.id, "agent_test")
        await self.task_start(task.id)
        return task

    async def _seed_to_review_ready(self) -> Task:
        """快速构造一个 review_ready 的 task (已交付 artifact v1)。"""
        task = await self._seed_to_in_progress()
        await self.artifact_commit(
            task_id=task.id,
            type="report",
            payload=ArtifactPayload(kind="inline", uri="mem://v1", checksum="sha256:1"),
            produced_by="agent",
        )
        return task

    async def _seed_full_lifecycle(self) -> Task:
        """构造一个走完完整闭环的 task (供 audit/版本测试)。"""
        task = await self._seed_to_review_ready()
        await self.review_submit(
            task_id=task.id,
            artifact_id=task.artifacts[0],
            reviewer="bob",
            verdict="changes_requested",
            requested_changes=("fix it",),
        )
        await self.artifact_commit(
            task_id=task.id,
            type="report",
            payload=ArtifactPayload(kind="inline", uri="mem://v2", checksum="sha256:2"),
            produced_by="agent",
        )
        await self.review_submit(
            task_id=task.id,
            artifact_id=task.artifacts[1],
            reviewer="bob",
            verdict="approved",
        )
        return task
