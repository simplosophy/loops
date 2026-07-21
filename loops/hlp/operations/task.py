from __future__ import annotations

from typing import Any

from ..objects import (
    AdapterOperationContext,
    Checkpoint,
    InputRef,
    Ownership,
    SteeringAmendment,
    Task,
    TaskSpec,
)
from ..state_machine import check_transition
from ..types import ProtocolError, SteeringIntent
from ._base import (
    HumanLoopOperationsBase,
    _jsonable,
    _steering_amendment_from_outbox,
    _TaskOperationReplay,
)


class TaskOps(HumanLoopOperationsBase):
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
        review_policy: Any = None,
    ) -> Task:
        """task.create (spec §4.1). state=created."""
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
            review_policy=review_policy,
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
        """task.assign (spec §4.1). created→assigned; ownership transfers to the agent."""
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

        # ownership transfer (spec §3.5)
        task.ownership = task.ownership.transfer(agent_id, via="assign")
        # state transition
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
        """task.start (spec §4.1): the agent starts executing; assigned→in_progress."""
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
        """task.cancel (spec §4.1). →completed (aborted)."""
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
        """task.amend (HLP 0.2.0): append steering without changing spec/state.

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
        """task.get (spec §4.1)."""
        return self.store.get_task(task_id)

    async def task_list(self) -> list[Task]:
        """task.list (spec §4.1)."""
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
        """task.interrupt (HLP 0.2.0): human-initiated pause."""
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
