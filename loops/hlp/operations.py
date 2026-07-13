from __future__ import annotations

import hashlib
import inspect
import json
from copy import deepcopy
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from typing import Any

from .adapters import AgentAdapter, FakeAgentAdapter
from .objects import (
    Artifact,
    ArtifactPayload,
    ArtifactProvenance,
    ArtifactRef,
    AdapterOperationContext,
    AdapterOutboxRecord,
    Checkpoint,
    CheckpointOption,
    CheckpointResolution,
    Evidence,
    IdempotencyRecord,
    InputRef,
    Ledger,
    LedgerEntry,
    Ownership,
    ProposedAction,
    Review,
    ReviewComment,
    SteeringAmendment,
    Task,
    TaskSpec,
)
from .state_machine import check_transition
from .store import HumanLoopStore
from .types import (
    CheckpointKind,
    CheckpointResolutionAction,
    ProtocolError,
    ReviewKind,
    ReviewVerdict,
    SteeringIntent,
    TaskState,
)
from ._ids import gen_review_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class _TaskOperationReplay:
    result: Any


@dataclass(frozen=True)
class _TaskOperationContext:
    key: str | None
    operation: str
    fingerprint: str
    revision_before: int
    audit_seq_before: int
    operation_id: str


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
    """HLP 协议操作入口 (spec §4.1, 共 23 个)。

    持有 store + audit + agent adapter，是协议层的 facade。
    上层 (transport/CLI) 调用这里；本类不感知 transport。
    """

    store: HumanLoopStore = field(default_factory=HumanLoopStore)
    adapter: AgentAdapter = field(default_factory=FakeAgentAdapter)
    last_operation_replayed: bool = field(default=False, init=False)
    last_operation_id: str | None = field(default=None, init=False)

    # ────────────────── Task (spec §4.1) ──────────────────

    async def task_create(
        self,
        *,
        principal: str,
        goal: str,
        type: str = "",
        acceptance_criteria: tuple[str, ...] = (),
        inputs: tuple[InputRef, ...] = (),
        constraints: Any = None,
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
            constraints=constraints,
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
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Task:
        """task.assign (spec §4.1)。created→assigned，ownership 转 agent。"""
        task = self.store._get_task_for_update(task_id)
        delegate_input = input or {"goal": task.spec.goal}
        idempotency = self._begin_task_operation(
            task,
            "task.assign",
            {
                "agent_id": agent_id,
                "capability": capability,
                "input": delegate_input,
            },
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        if isinstance(idempotency, _TaskOperationReplay):
            return idempotency.result
        self._require_state(task, "created")
        adapter_request = {
            "adapter_action": "delegate",
            "task_id": task_id,
            "agent_id": agent_id,
            "capability": capability,
            "input": _jsonable(delegate_input),
            "parent_run": None,
        }
        adapter_context = self._adapter_context(task, idempotency)
        outbox_request = self._prepare_adapter_outbox(
            adapter_context,
            adapter_request,
        )

        run_id = await self._call_adapter_with_context(
            self.adapter.delegate,
            context=adapter_context,
            task_id=outbox_request["task_id"],
            agent_id=outbox_request["agent_id"],
            capability=outbox_request["capability"],
            input=outbox_request["input"],
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
        self._commit_task_operation(task, idempotency, task, adapter_result=run_id)
        return task

    async def task_start(
        self,
        task_id: str,
        *,
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Task:
        """task.start (spec §4.1)：agent 开始执行，assigned→in_progress。"""
        task = self.store._get_task_for_update(task_id)
        idempotency = self._begin_task_operation(
            task,
            "task.start",
            {},
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        if isinstance(idempotency, _TaskOperationReplay):
            return idempotency.result
        self._require_state(task, "assigned")
        check_transition(task.state, "in_progress")
        task.state = "in_progress"
        self._audit(
            actor=task.ownership.assignee,
            action="task.started",
            subject=("task", task.id),
            task_id=task_id,
        )
        self._commit_task_operation(task, idempotency, task)
        return task

    async def task_cancel(
        self,
        task_id: str,
        by: str,
        *,
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Task:
        """task.cancel (spec §4.1)。→completed (中止)。"""
        task = self.store._get_task_for_update(task_id)
        idempotency = self._begin_task_operation(
            task,
            "task.cancel",
            {"by": by},
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        if isinstance(idempotency, _TaskOperationReplay):
            return idempotency.result
        if task.state in ("completed", "rejected"):
            raise ProtocolError(
                "PRECONDITION_FAILED",
                f"cannot cancel terminal task in state {task.state!r}",
            )
        run_id = self.store.run_of_task(task_id)
        adapter_context: AdapterOperationContext | None = None
        if run_id is not None:
            adapter_request = {
                "adapter_action": "cancel",
                "run_id": run_id,
                "reason": f"cancelled by {by}",
            }
            adapter_context = self._adapter_context(task, idempotency)
            outbox_request = self._prepare_adapter_outbox(
                adapter_context,
                adapter_request,
            )
            await self._call_adapter_with_context(
                self.adapter.cancel,
                outbox_request["run_id"],
                outbox_request["reason"],
                context=adapter_context,
            )
        if task.ownership.assignee != task.ownership.principal:
            task.ownership = task.ownership.transfer(
                task.ownership.principal,
                via="reject",
            )
        check_transition(task.state, "completed")
        task.state = "completed"
        self._audit(
            actor=by,
            action="task.cancelled",
            subject=("task", task.id),
            task_id=task_id,
        )
        self._commit_task_operation(task, idempotency, task)
        return task

    async def task_amend(
        self,
        task_id: str,
        *,
        by: str,
        text: str,
        intent: SteeringIntent = "clarify",
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
        promotion_provenance: dict | None = None,
    ) -> Task:
        """task.amend (HLP 0.2.0)：append steering without changing spec/state.

        ``promotion_provenance`` is optional HLP-realtime intent provenance
        (appendix C) for audit only; it does not alter Task.state.
        """
        task = self.store._get_task_for_update(task_id)
        state_before = task.state
        idempotency = self._begin_task_operation(
            task,
            "task.amend",
            {
                "by": by,
                "text": text,
                "intent": intent,
            },
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        if isinstance(idempotency, _TaskOperationReplay):
            return idempotency.result
        if task.state not in ("in_progress", "blocked"):
            raise ProtocolError(
                "PRECONDITION_FAILED",
                f"cannot amend task in state {task.state!r}",
            )
        self._require_principal(task, by, "task amendment")
        if not text:
            raise ProtocolError("INVALID_SPEC", "amendment text is required")

        amendment = SteeringAmendment(text=text, intent=intent, by=by)
        run_id = self.store.run_of_task(task_id)
        if run_id is not None:
            adapter_context = self._adapter_context(task, idempotency)
            outbox_request = self._prepare_adapter_outbox(
                adapter_context,
                {
                    "adapter_action": "steer",
                    "run_id": run_id,
                    "amendment": _jsonable(amendment),
                },
            )
            amendment_payload = outbox_request["amendment"]
            amendment = _steering_amendment_from_outbox(amendment_payload)
            await self._call_adapter_with_context(
                self.adapter.steer,
                run_id,
                amendment_payload,
                context=adapter_context,
            )
        task.steering_log = (*task.steering_log, amendment)
        # D1: soft promotion path must not change Task.state (amend never does).
        if task.state != state_before:
            raise ProtocolError(
                "PRECONDITION_FAILED",
                "task.amend must not change Task.state",
                details={"before": state_before, "after": task.state},
            )
        after: dict = {"text": text, "intent": intent, "state": task.state}
        if promotion_provenance is not None:
            after["promotion"] = promotion_provenance
        self._audit(
            actor=by,
            action="task.amended",
            subject=("task", task.id),
            task_id=task.id,
            after=after,
        )
        self._commit_task_operation(task, idempotency, task)
        return task

    async def task_get(self, task_id: str) -> Task:
        """task.get (spec §4.1)。"""
        return self.store.get_task(task_id)

    async def task_list(self) -> list[Task]:
        """task.list (spec §4.1)。"""
        return self.store.list_tasks()

    async def task_interrupt(
        self,
        task_id: str,
        *,
        by: str,
        prompt: str,
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Checkpoint:
        """task.interrupt (HLP 0.2.0)：human-initiated pause."""
        task = self.store._get_task_for_update(task_id)
        idempotency = self._begin_task_operation(
            task,
            "task.interrupt",
            {
                "by": by,
                "prompt": prompt,
            },
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        if isinstance(idempotency, _TaskOperationReplay):
            return idempotency.result
        self._require_state(task, "in_progress")
        self._require_principal(task, by, "task interrupt")
        if not prompt:
            raise ProtocolError("INVALID_SPEC", "interrupt prompt is required")

        ckpt = Checkpoint(
            task_id=task_id,
            kind="interrupt",
            prompt=prompt,
            state="pending",
            raised_by="human",
        )
        run_id = self.store.run_of_task(task_id)
        if run_id is not None:
            adapter_context = self._adapter_context(task, idempotency)
            outbox_request = self._prepare_adapter_outbox(
                adapter_context,
                {
                    "adapter_action": "block",
                    "run_id": run_id,
                    "checkpoint_id": ckpt.id,
                    "reason": prompt,
                },
            )
            ckpt.id = str(outbox_request["checkpoint_id"])
            await self._call_adapter_with_context(
                self.adapter.block,
                run_id,
                ckpt.id,
                outbox_request["reason"],
                context=adapter_context,
            )

        self.store.put_checkpoint(ckpt)
        task.checkpoints.append(ckpt.id)
        check_transition(task.state, "blocked")
        task.state = "blocked"
        if task.ownership.assignee != task.ownership.principal:
            task.ownership = task.ownership.transfer(
                task.ownership.principal,
                via="checkpoint",
            )
        self._audit(
            actor=by,
            action="task.interrupted",
            subject=("task", task.id),
            task_id=task_id,
        )
        self._audit(
            actor="system",
            action="task.checkpoint.raised",
            subject=("checkpoint", ckpt.id),
            task_id=task_id,
        )
        self._commit_task_operation(task, idempotency, ckpt)
        return ckpt

    # ────────────────── Checkpoint (spec §4.1) ──────────────────

    async def checkpoint_raise(
        self,
        *,
        task_id: str,
        kind: CheckpointKind,
        prompt: str,
        options: tuple[CheckpointOption, ...] = (),
        proposed_actions: tuple[ProposedAction, ...] = (),
        context: tuple[Evidence, ...] = (),
        raised_by: str,
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Checkpoint:
        """checkpoint.raise (spec §4.1)。in_progress→blocked。"""
        task = self.store._get_task_for_update(task_id)
        idempotency = self._begin_task_operation(
            task,
            "checkpoint.raise",
            {
                "kind": kind,
                "prompt": prompt,
                "options": options,
                "proposed_actions": proposed_actions,
                "context": context,
                "raised_by": raised_by,
            },
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        if isinstance(idempotency, _TaskOperationReplay):
            return idempotency.result
        self._require_state(task, "in_progress")
        if kind == "interrupt":
            raise ProtocolError(
                "INVALID_SPEC",
                "interrupt checkpoint must be raised through task.interrupt",
            )
        if kind == "choice" and not options:
            raise ProtocolError("INVALID_SPEC", "choice checkpoint requires options")

        ckpt = Checkpoint(
            task_id=task_id,
            kind=kind,
            prompt=prompt,
            options=options,
            proposed_actions=proposed_actions,
            context=context,
            state="pending",
            raised_by="agent",
        )
        ckpt_raised_by = raised_by
        run_id = self.store.run_of_task(task_id)
        adapter_context: AdapterOperationContext | None = None
        if run_id is not None:
            adapter_context = self._adapter_context(task, idempotency)
            outbox_request = self._prepare_adapter_outbox(
                adapter_context,
                {
                    "adapter_action": "block",
                    "run_id": run_id,
                    "checkpoint_id": ckpt.id,
                    "reason": prompt,
                },
            )
            ckpt.id = str(outbox_request["checkpoint_id"])
            await self._call_adapter_with_context(
                self.adapter.block,
                run_id,
                ckpt.id,
                outbox_request["reason"],
                context=adapter_context,
            )

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
        self._commit_task_operation(task, idempotency, ckpt)
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
        approved_actions: tuple[str, ...] = (),
        denied_actions: tuple[str, ...] = (),
        state_patch: dict[str, Any] | None = None,
        edited_artifact_ref: dict[str, str] | None = None,
        comment: str | None = None,
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Checkpoint:
        """checkpoint.resolve (spec §4.1)。blocked→in_progress (approve/provide)
        或 blocked→completed (reject)。"""
        ckpt = self.store._get_checkpoint_for_update(ckpt_id)
        task = self.store._get_task_for_update(ckpt.task_id)
        idempotency = self._begin_task_operation(
            task,
            "checkpoint.resolve",
            {
                "checkpoint_id": ckpt_id,
                "by": by,
                "action": action,
                "choice": choice,
                "input": input,
                "reassign_to": reassign_to,
                "approved_actions": approved_actions,
                "denied_actions": denied_actions,
                "state_patch": state_patch,
                "edited_artifact_ref": edited_artifact_ref,
                "comment": comment,
            },
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        if isinstance(idempotency, _TaskOperationReplay):
            return idempotency.result
        if ckpt.state == "expired":
            raise ProtocolError(
                "CHECKPOINT_EXPIRED",
                f"checkpoint {ckpt.id} is expired",
            )
        if ckpt.state != "pending":
            raise ProtocolError(
                "PRECONDITION_FAILED",
                f"cannot resolve checkpoint in state {ckpt.state!r}",
            )
        self._require_state(task, "blocked")
        self._require_human_actor(by, "checkpoint resolver")
        self._validate_checkpoint_resolution(
            ckpt,
            action=action,
            choice=choice,
            input=input,
            reassign_to=reassign_to,
            approved_actions=approved_actions,
            denied_actions=denied_actions,
        )

        resolution = CheckpointResolution(
            by=by,
            action=action,
            choice=choice,
            input=input,
            reassign_to=reassign_to,
            approved_actions=approved_actions,
            denied_actions=denied_actions,
            state_patch=state_patch,
            edited_artifact_ref=edited_artifact_ref,
            comment=comment,
        )
        resume_payload = self._resolution_payload(resolution)
        run_id = self.store.run_of_task(task.id)
        if run_id is not None:
            adapter_context = self._adapter_context(task, idempotency)
            self._prepare_adapter_outbox(
                adapter_context,
                {
                    "adapter_action": "resume",
                    "run_id": run_id,
                    "resolution": _jsonable(resume_payload),
                },
            )
            await self._call_adapter_with_context(
                self.adapter.resume,
                run_id,
                resume_payload,
                context=adapter_context,
            )

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
        self._commit_task_operation(task, idempotency, ckpt)
        return ckpt

    async def checkpoint_expire(
        self,
        ckpt_id: str,
        *,
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Checkpoint:
        """checkpoint.expire (spec §4.1, §7.2)。超时自动失效。"""
        ckpt = self.store._get_checkpoint_for_update(ckpt_id)
        task = self.store._get_task_for_update(ckpt.task_id)
        idempotency = self._begin_task_operation(
            task,
            "checkpoint.expire",
            {"checkpoint_id": ckpt_id},
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        if isinstance(idempotency, _TaskOperationReplay):
            return idempotency.result
        if ckpt.state != "pending":
            raise ProtocolError(
                "PRECONDITION_FAILED",
                f"cannot expire checkpoint in state {ckpt.state!r}",
            )
        ckpt.state = "expired"
        # 超时后 task 保持 blocked (spec §7.2 开放议题，参考实现选纯挂起)
        self._audit(
            actor="system",
            action="task.checkpoint.expired",
            subject=("checkpoint", ckpt.id),
            task_id=task.id,
        )
        self._commit_task_operation(task, idempotency, ckpt)
        return ckpt

    # ────────────────── Ownership (spec §4.1) ──────────────────

    async def ownership_transfer(
        self,
        task_id: str,
        to: str,
        via: str,
        *,
        actor: str = "system",
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Task:
        """ownership.transfer (spec §4.1, §3.5)。内部转移 assignee。"""
        task = self.store._get_task_for_update(task_id)
        idempotency = self._begin_task_operation(
            task,
            "ownership.transfer",
            {
                "to": to,
                "via": via,
                "actor": actor,
            },
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        if isinstance(idempotency, _TaskOperationReplay):
            return idempotency.result
        if task.is_terminal:
            raise ProtocolError(
                "PRECONDITION_FAILED",
                "cannot transfer ownership of terminal task",
            )
        run_id = self.store.run_of_task(task_id)
        new_run_id: str | None = None
        adapter_context: AdapterOperationContext | None = None
        if via == "handoff" and run_id is not None and to != task.ownership.assignee:
            handoff_context = {
                "task_id": task.id,
                "from": task.ownership.assignee,
                "to": to,
                "via": via,
            }
            adapter_request = {
                "adapter_action": "handoff",
                "run_id": run_id,
                "to_agent": to,
                "context": handoff_context,
            }
            adapter_context = self._adapter_context(task, idempotency)
            outbox_request = self._prepare_adapter_outbox(
                adapter_context,
                adapter_request,
            )
            new_run_id = await self._call_adapter_with_context(
                self.adapter.handoff,
                outbox_request["run_id"],
                outbox_request["to_agent"],
                outbox_request["context"],
                context=adapter_context,
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
        self._commit_task_operation(
            task,
            idempotency,
            task,
            adapter_result=new_run_id,
        )
        return task

    async def ownership_delegate(
        self,
        task_id: str,
        to_agent: str,
        *,
        actor: str,
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Task:
        """ownership.delegate (spec §4.1, §3.5)。agent 向下委派，需 delegable。"""
        task = self.store._get_task_for_update(task_id)
        idempotency = self._begin_task_operation(
            task,
            "ownership.delegate",
            {
                "to_agent": to_agent,
                "actor": actor,
            },
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        if isinstance(idempotency, _TaskOperationReplay):
            return idempotency.result
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
        adapter_request = {
            "adapter_action": "delegate",
            "task_id": task_id,
            "agent_id": to_agent,
            "capability": "",
            "input": {"goal": task.spec.goal},
            "parent_run": parent_run,
        }
        adapter_context = self._adapter_context(task, idempotency)
        outbox_request = self._prepare_adapter_outbox(
            adapter_context,
            adapter_request,
        )
        run_id = await self._call_adapter_with_context(
            self.adapter.delegate,
            context=adapter_context,
            task_id=outbox_request["task_id"],
            agent_id=outbox_request["agent_id"],
            capability=outbox_request["capability"],
            input=outbox_request["input"],
            parent_run=outbox_request["parent_run"],
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
        self._commit_task_operation(task, idempotency, task, adapter_result=run_id)
        return task

    # ────────────────── Review (spec §4.1) ──────────────────

    async def review_submit(
        self,
        *,
        task_id: str,
        artifact_id: str,
        reviewer: str,
        verdict: ReviewVerdict,
        kind: ReviewKind = "deliverable",
        comments: tuple[ReviewComment, ...] = (),
        requested_changes: tuple[str, ...] = (),
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Review:
        """review.submit (spec §4.1, §3.6)。

        - review_ready/under_review → accepted (approved)
        - review_ready/under_review → in_progress (changes_requested, 返工)
        - review_ready/under_review → rejected (rejected)
        """
        task = self.store._get_task_for_update(task_id)
        idempotency = self._begin_task_operation(
            task,
            "review.submit",
            {
                "artifact_id": artifact_id,
                "reviewer": reviewer,
                "verdict": verdict,
                "kind": kind,
                "comments": comments,
                "requested_changes": requested_changes,
            },
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        if isinstance(idempotency, _TaskOperationReplay):
            return idempotency.result
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
            kind=kind,
            verdict=verdict,
            comments=comments,
            requested_changes=requested_changes,
        ).seal()
        self.store.put_review(review)

        # 状态联动 (spec §3.6): 先 review_ready→under_review, 再按 verdict 转
        if task.state == "review_ready":
            check_transition(task.state, "under_review")
            task.state = "under_review"

        if kind == "plan" and verdict in ("approved", "changes_requested"):
            check_transition(task.state, "in_progress")
            task.state = "in_progress"
            target_agent = self._last_assignee_before(
                task,
                to=task.ownership.principal,
                via="handoff",
            )
            if target_agent is not None and task.ownership.assignee != target_agent:
                task.ownership = task.ownership.transfer(
                    target_agent,
                    via="approve" if verdict == "approved" else "reject",
                )
        elif verdict == "approved":
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
            after={"kind": kind, "verdict": verdict},
        )
        if kind == "deliverable" and verdict == "approved":
            self._audit(
                actor="system",
                action="task.completed",
                subject=("task", task.id),
                task_id=task_id,
                after={"review_id": review.id},
            )
        self._commit_task_operation(task, idempotency, review)
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
            kind=original.kind,
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
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Artifact:
        """artifact.commit (spec §4.1, §3.7)。

        in_progress→review_ready (首次交付) 或
        under_review→in_progress 不在此处理（review 状态机管）。
        参考：in_progress 状态下 commit 触发 review_ready。
        """
        task = self.store._get_task_for_update(task_id)
        idempotency = self._begin_task_operation(
            task,
            "artifact.commit",
            {
                "type": type,
                "payload": payload,
                "produced_by": produced_by,
                "parent_version": parent_version,
            },
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        if isinstance(idempotency, _TaskOperationReplay):
            return idempotency.result
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
        self._commit_task_operation(task, idempotency, art)
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

    def _begin_task_operation(
        self,
        task: Task,
        operation: str,
        request: dict[str, Any],
        *,
        expected_task_revision: int | None,
        idempotency_key: str | None,
    ) -> _TaskOperationContext | _TaskOperationReplay:
        fingerprint = _fingerprint({
            "operation": operation,
            "request": request,
        })
        self.last_operation_replayed = False
        self.last_operation_id = None
        if idempotency_key is not None:
            record = self.store.get_idempotency_record(task.id, idempotency_key)
            if record is not None:
                if (
                    record.operation != operation
                    or record.request_fingerprint != fingerprint
                ):
                    raise ProtocolError(
                        "CONFLICT",
                        "idempotency key was already used for a different request",
                        details={
                            "task_id": task.id,
                            "idempotency_key": idempotency_key,
                        },
                    )
                self.last_operation_replayed = True
                self.last_operation_id = _adapter_operation_id(
                    task.id,
                    record.operation,
                    record.key,
                    record.request_fingerprint,
                    record.revision_before,
                )
                return _TaskOperationReplay(result=record.result)

        if (
            expected_task_revision is not None
            and task.revision != expected_task_revision
        ):
            raise ProtocolError(
                "CONFLICT",
                "task revision conflict",
                details={
                    "task_id": task.id,
                    "expected_task_revision": expected_task_revision,
                    "actual_task_revision": task.revision,
                },
            )

        context = _TaskOperationContext(
            key=idempotency_key,
            operation=operation,
            fingerprint=fingerprint,
            revision_before=task.revision,
            audit_seq_before=self.store.audit_log.count,
            operation_id=_adapter_operation_id(
                task.id,
                operation,
                idempotency_key,
                fingerprint,
                task.revision,
            ),
        )
        self.last_operation_id = context.operation_id
        return context

    def _commit_task_operation(
        self,
        task: Task,
        context: _TaskOperationContext,
        result: Any,
        *,
        adapter_result: Any = None,
    ) -> None:
        self.store.bump_task_revision(task)
        should_flush = False
        if context.key is not None:
            self.store.put_idempotency_record(IdempotencyRecord(
                task_id=task.id,
                key=context.key,
                operation=context.operation,
                request_fingerprint=context.fingerprint,
                revision_before=context.revision_before,
                revision_after=task.revision,
                result=deepcopy(result),
                audit_seq_start=context.audit_seq_before + 1,
                audit_seq_end=self.store.audit_log.count,
            ))
            should_flush = True
        if self._has_adapter_outbox_record(context.operation_id):
            self.store.mark_adapter_outbox_succeeded(
                context.operation_id,
                result=adapter_result,
            )
            should_flush = True
        if should_flush:
            self._flush_store_if_available()

    def _adapter_context(
        self,
        task: Task,
        context: _TaskOperationContext,
    ) -> AdapterOperationContext:
        return AdapterOperationContext(
            operation_id=context.operation_id,
            task_id=task.id,
            correlation_id=task.id,
            operation=context.operation,
            idempotency_key=context.key,
            request_fingerprint=context.fingerprint,
            task_revision=context.revision_before,
        )

    def _prepare_adapter_outbox(
        self,
        adapter_context: AdapterOperationContext,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            existing = self.store.get_adapter_outbox_record(adapter_context.operation_id)
        except ProtocolError as exc:
            if exc.code != "NOT_FOUND":
                raise
        else:
            if (
                existing.request_fingerprint != adapter_context.request_fingerprint
                or existing.operation != adapter_context.operation
            ):
                raise ProtocolError(
                    "CONFLICT",
                    "adapter outbox operation id conflicts with a different request",
                    details={"operation_id": adapter_context.operation_id},
                )
            return deepcopy(existing.request)
        self.store.put_adapter_outbox_record(AdapterOutboxRecord(
            operation_id=adapter_context.operation_id,
            task_id=adapter_context.task_id,
            operation=adapter_context.operation,
            request_fingerprint=adapter_context.request_fingerprint,
            context=adapter_context,
            request=request,
        ))
        self._flush_store_if_available()
        return deepcopy(request)

    def _has_adapter_outbox_record(self, operation_id: str) -> bool:
        try:
            self.store.get_adapter_outbox_record(operation_id)
        except ProtocolError as exc:
            if exc.code == "NOT_FOUND":
                return False
            raise
        return True

    async def _call_adapter_with_context(
        self,
        method: Any,
        *args: Any,
        context: AdapterOperationContext,
        **kwargs: Any,
    ) -> Any:
        signature = inspect.signature(method)
        accepts_kwargs = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        if "operation_context" in signature.parameters:
            return await method(*args, **kwargs, operation_context=context)
        parameter = signature.parameters.get("context")
        if parameter is not None and parameter.kind is inspect.Parameter.KEYWORD_ONLY:
            return await method(*args, **kwargs, context=context)
        if accepts_kwargs:
            if getattr(method, "__name__", "") in {"block", "resume", "steer"}:
                return await method(*args, **kwargs, context=context)
            return await method(*args, **kwargs, operation_context=context)
        return await method(*args, **kwargs)

    def _flush_store_if_available(self) -> None:
        flush = getattr(self.store, "flush", None)
        if flush is not None:
            flush()

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
            reducer=self._audit_reducer_payload(
                subject=subject,
                task_id=task_id,
                change=after,
            ),
        )

    def _audit_reducer_payload(
        self,
        *,
        subject: tuple[str, str],
        task_id: str | None,
        change: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "subject": {"kind": subject[0], "id": subject[1]},
            "change": _jsonable(change),
        }
        if task_id is not None:
            task = self.store.tasks.get(task_id)
            if task is not None:
                payload["task"] = {
                    "id": task.id,
                    "state": task.state,
                    "revision": task.revision,
                    "ownership": {
                        "principal": task.ownership.principal,
                        "assignee": task.ownership.assignee,
                        "delegable": task.ownership.delegable,
                    },
                    "checkpoint_ids": list(task.checkpoints),
                    "artifact_ids": list(task.artifacts),
                    "steering_count": len(task.steering_log),
                }
        return payload

    @staticmethod
    def _is_human(actor: str) -> bool:
        return bool(actor) and not actor.startswith("agent_")

    @staticmethod
    def _is_agent(actor: str) -> bool:
        return actor.startswith("agent_")

    def _require_human_actor(self, actor: str, role: str) -> None:
        if not self._is_human(actor):
            raise ProtocolError("UNAUTHORIZED", f"{role} must be a human actor")

    def _require_principal(self, task: Task, actor: str, role: str) -> None:
        self._require_human_actor(actor, role)
        if actor != task.ownership.principal:
            raise ProtocolError(
                "UNAUTHORIZED",
                f"{role} must be performed by task principal",
            )

    def _validate_checkpoint_resolution(
        self,
        ckpt: Checkpoint,
        *,
        action: CheckpointResolutionAction,
        choice: str | None,
        input: str | None,
        reassign_to: str | None,
        approved_actions: tuple[str, ...],
        denied_actions: tuple[str, ...],
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
        action_ids = {proposed.id for proposed in ckpt.proposed_actions}
        requested_ids = set(approved_actions) | set(denied_actions)
        if requested_ids and not requested_ids.issubset(action_ids):
            raise ProtocolError(
                "INVALID_SPEC",
                "approved_actions and denied_actions must reference proposed_actions",
            )

    @staticmethod
    def _resolution_payload(resolution: CheckpointResolution) -> dict[str, Any]:
        return {
            "by": resolution.by,
            "action": resolution.action,
            "choice": resolution.choice,
            "input": resolution.input,
            "reassign_to": resolution.reassign_to,
            "approved_actions": resolution.approved_actions,
            "denied_actions": resolution.denied_actions,
            "state_patch": resolution.state_patch,
            "edited_artifact_ref": resolution.edited_artifact_ref,
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


def _fingerprint(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
    )


def _adapter_operation_id(
    task_id: str,
    operation: str,
    idempotency_key: str | None,
    fingerprint: str,
    revision: int,
) -> str:
    seed = json.dumps(
        {
            "task_id": task_id,
            "operation": operation,
            "idempotency_key": idempotency_key,
            "request_fingerprint": fingerprint,
            "task_revision": revision,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "op_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _steering_amendment_from_outbox(value: Any) -> SteeringAmendment:
    if not isinstance(value, dict):
        raise ProtocolError(
            "INVALID_SPEC",
            "adapter outbox amendment payload must be an object",
        )
    at = value.get("at", _now())
    if isinstance(at, str):
        at = datetime.fromisoformat(at)
    return SteeringAmendment(
        text=str(value["text"]),
        intent=value.get("intent", "clarify"),
        by=str(value.get("by", "")),
        at=at,
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {
            field.name: _jsonable(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    return value
