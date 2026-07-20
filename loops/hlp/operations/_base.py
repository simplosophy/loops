from __future__ import annotations

import hashlib
import inspect
import json
from copy import deepcopy
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import UTC, datetime
from typing import Any

from ..adapters import AgentAdapter, FakeAgentAdapter
from ..objects import (
    AdapterOperationContext,
    AdapterOutboxRecord,
    Checkpoint,
    CheckpointResolution,
    IdempotencyRecord,
    SteeringAmendment,
    Task,
)
from ..store import HumanLoopStore
from ..types import CheckpointResolutionAction, ProtocolError, TaskState


def _now() -> datetime:
    return datetime.now(UTC)


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


@dataclass
class HumanLoopOperationsBase:
    store: HumanLoopStore = field(default_factory=HumanLoopStore)
    adapter: AgentAdapter = field(default_factory=FakeAgentAdapter)
    last_operation_replayed: bool = field(default=False, init=False)
    last_operation_id: str | None = field(default=None, init=False)

    # ────────────────── Internal helpers ──────────────────

    def _begin_task_operation(
        self,
        task: Task,
        operation: str,
        request: dict[str, Any],
        *,
        expected_task_revision: int | None,
        idempotency_key: str | None,
    ) -> _TaskOperationContext | _TaskOperationReplay:
        fingerprint = _fingerprint(
            {
                "operation": operation,
                "request": request,
            }
        )
        self.last_operation_replayed = False
        self.last_operation_id = None
        if idempotency_key is not None:
            record = self.store.get_idempotency_record(task.id, idempotency_key)
            if record is not None:
                if record.operation != operation or record.request_fingerprint != fingerprint:
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

        if expected_task_revision is not None and task.revision != expected_task_revision:
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
            self.store.put_idempotency_record(
                IdempotencyRecord(
                    task_id=task.id,
                    key=context.key,
                    operation=context.operation,
                    request_fingerprint=context.fingerprint,
                    revision_before=context.revision_before,
                    revision_after=task.revision,
                    result=deepcopy(result),
                    audit_seq_start=context.audit_seq_before + 1,
                    audit_seq_end=self.store.audit_log.count,
                )
            )
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
        self.store.put_adapter_outbox_record(
            AdapterOutboxRecord(
                operation_id=adapter_context.operation_id,
                task_id=adapter_context.task_id,
                operation=adapter_context.operation,
                request_fingerprint=adapter_context.request_fingerprint,
                context=adapter_context,
                request=request,
            )
        )
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
        """Precondition: require the task to be in a given state (spec §4.3)."""
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
        """Uniform audit recording (spec §4.2)."""
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
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
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
