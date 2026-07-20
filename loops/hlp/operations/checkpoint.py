from __future__ import annotations

from typing import Any

from ..objects import (
    AdapterOperationContext,
    Checkpoint,
    CheckpointOption,
    CheckpointResolution,
    Evidence,
    ProposedAction,
)
from ..state_machine import check_transition
from ..types import CheckpointKind, CheckpointResolutionAction, ProtocolError
from ._base import HumanLoopOperationsBase, _jsonable, _TaskOperationReplay


class CheckpointOps(HumanLoopOperationsBase):
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
        """checkpoint.raise (spec §4.1). in_progress→blocked."""
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

        # state coordination (spec §3.4)
        check_transition(task.state, "blocked")
        task.state = "blocked"
        # ownership falls back to principal (spec §2.1)
        task.ownership = task.ownership.transfer(task.ownership.principal, via="checkpoint")

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
        """checkpoint.resolve (spec §4.1). blocked→in_progress (approve/provide)
        or blocked→completed (reject)."""
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

        # action determines where the task goes (spec §3.4)
        if action == "reject":
            check_transition(task.state, "completed")
            task.state = "completed"
        else:  # approve / choose / provide / reassign
            check_transition(task.state, "in_progress")
            task.state = "in_progress"
            # ownership returns to the agent
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
        """checkpoint.expire (spec §4.1, §7.2). Automatically expires on timeout."""
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
        # after timeout the task stays blocked (spec §7.2 open issue; the reference implementation chooses pure suspension)
        self._audit(
            actor="system",
            action="task.checkpoint.expired",
            subject=("checkpoint", ckpt.id),
            task_id=task.id,
        )
        self._commit_task_operation(task, idempotency, ckpt)
        return ckpt
