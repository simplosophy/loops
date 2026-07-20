from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import UTC, datetime
from typing import Any

from ._ids import gen_audit_id
from .types import HLP_PROFILE, HLP_SCHEMA_VERSION


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class AuditEvent:
    """Immutable audit log entry (spec §3.9).

    - seq: monotonically increasing within the scope
    - action: "<object>.<verb>" (spec §4.2)
    - subject: operation target {kind, id}
    - task_id: always associated with the aggregate root
    - before/after: state before/after the change (optional)
    """

    seq: int
    at: datetime = field(default_factory=_now)
    actor: str = ""
    action: str = ""  # e.g. "task.created"
    subject: tuple[str, str] = ("", "")  # (kind, id)
    task_id: str | None = None
    before: Any = None
    after: Any = None
    reducer: dict[str, Any] | None = None
    id: str = field(default_factory=gen_audit_id)
    schema_version: str = HLP_SCHEMA_VERSION
    profile: str = HLP_PROFILE
    prev_hash: str = ""
    hash: str = ""


class AuditLog:
    """Append-only audit log (spec §3.9).

    - never deleted or modified
    - seq monotonically increasing
    - supports query / replay
    """

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._seq = 0

    def append(
        self,
        *,
        actor: str,
        action: str,
        subject: tuple[str, str] = ("", ""),
        task_id: str | None = None,
        before: Any = None,
        after: Any = None,
        reducer: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """Append one audit event and return it. Never fails, never blocks the business flow (spec §3.9)."""
        self._seq += 1
        prev_hash = self._events[-1].hash if self._events else ""
        event = AuditEvent(
            seq=self._seq,
            actor=actor,
            action=action,
            subject=subject,
            task_id=task_id,
            before=before,
            after=after,
            reducer=reducer,
            prev_hash=prev_hash,
        )
        object.__setattr__(event, "hash", _audit_event_hash(event))
        self._events.append(event)
        return event

    def query(
        self,
        *,
        task_id: str | None = None,
        actor: str | None = None,
        action: str | None = None,
    ) -> list[AuditEvent]:
        """Query by the given criteria (spec §4.1 audit.query)."""
        result = self._events
        if task_id is not None:
            result = [e for e in result if e.task_id == task_id]
        if actor is not None:
            result = [e for e in result if e.actor == actor]
        if action is not None:
            result = [e for e in result if e.action == action]
        return list(result)

    def replay(self, task_id: str) -> list[AuditEvent]:
        """Replay the full history of a Task (spec §4.1 audit.replay)."""
        return [e for e in self._events if e.task_id == task_id]

    def all(self) -> list[AuditEvent]:
        """All events, in ascending seq order."""
        return list(self._events)

    def verify_hash_chain(self) -> bool:
        prev_hash = ""
        for event in self._events:
            if event.prev_hash != prev_hash:
                return False
            if event.hash != _audit_event_hash(event):
                return False
            prev_hash = event.hash
        return True

    @property
    def count(self) -> int:
        return len(self._events)


def _audit_event_hash(event: AuditEvent) -> str:
    payload = {
        field.name: _jsonable(getattr(event, field.name))
        for field in fields(event)
        if field.name != "hash"
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


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
