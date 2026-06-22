from __future__ import annotations

import json
import sqlite3
from dataclasses import fields, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .audit import AuditEvent, AuditLog
from .objects import (
    Artifact,
    ArtifactPayload,
    ArtifactProvenance,
    ArtifactRef,
    Checkpoint,
    CheckpointOption,
    CheckpointResolution,
    Constraints,
    Evidence,
    InputRef,
    Ledger,
    LedgerEntry,
    Ownership,
    OwnershipTransfer,
    Review,
    ReviewComment,
    Task,
    TaskSpec,
)
from .store import HumanLoopStore


_DATACLASS_TYPES = {
    cls.__name__: cls
    for cls in (
        Artifact,
        ArtifactPayload,
        ArtifactProvenance,
        ArtifactRef,
        AuditEvent,
        Checkpoint,
        CheckpointOption,
        CheckpointResolution,
        Constraints,
        Evidence,
        InputRef,
        Ledger,
        LedgerEntry,
        Ownership,
        OwnershipTransfer,
        Review,
        ReviewComment,
        Task,
        TaskSpec,
    )
}


class SQLiteHumanLoopStore(HumanLoopStore):
    """SQLite-backed snapshot store for local durable HLP SDK use."""

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self.path = Path(path)
        self._init_db()
        self._load()

    def flush(self) -> None:
        snapshot = {
            "tasks": self.tasks,
            "checkpoints": self.checkpoints,
            "reviews": self.reviews,
            "artifacts": self.artifacts,
            "ledgers": self.ledgers,
            "audit_events": self.audit_log.all(),
            "artifact_versions": self._artifact_versions,
            "artifact_references": self._artifact_references,
            "task_runs": self._task_runs,
        }
        with self._connect() as conn:
            conn.execute("delete from hlp_snapshot")
            conn.executemany(
                "insert into hlp_snapshot(key, payload) values (?, ?)",
                [
                    (key, json.dumps(_pack(value), sort_keys=True))
                    for key, value in snapshot.items()
                ],
            )

    def _init_db(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists hlp_snapshot (
                  key text primary key,
                  payload text not null
                )
                """
            )

    def _load(self) -> None:
        with self._connect() as conn:
            rows = conn.execute("select key, payload from hlp_snapshot").fetchall()
        snapshot = {key: _unpack(json.loads(payload)) for key, payload in rows}
        self.tasks = snapshot.get("tasks", {})
        self.checkpoints = snapshot.get("checkpoints", {})
        self.reviews = snapshot.get("reviews", {})
        self.artifacts = snapshot.get("artifacts", {})
        self.ledgers = snapshot.get("ledgers", {})
        self._artifact_versions = snapshot.get("artifact_versions", {})
        self._artifact_references = snapshot.get("artifact_references", {})
        self._task_runs = snapshot.get("task_runs", {})
        events = snapshot.get("audit_events", [])
        self.audit_log = AuditLog()
        self.audit_log._events = list(events)
        self.audit_log._seq = max((event.seq for event in events), default=0)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)


def _pack(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"__hlp_type__": "datetime", "value": value.isoformat()}
    if is_dataclass(value):
        return {
            "__hlp_type__": value.__class__.__name__,
            "fields": {
                field.name: _pack(getattr(value, field.name))
                for field in fields(value)
            },
        }
    if isinstance(value, tuple):
        return {"__hlp_type__": "tuple", "items": [_pack(item) for item in value]}
    if isinstance(value, list):
        return {"__hlp_type__": "list", "items": [_pack(item) for item in value]}
    if isinstance(value, dict):
        return {
            "__hlp_type__": "dict",
            "items": [[_pack(key), _pack(item)] for key, item in value.items()],
        }
    return value


def _unpack(value: Any) -> Any:
    if not isinstance(value, dict) or "__hlp_type__" not in value:
        return value
    type_name = value["__hlp_type__"]
    if type_name == "datetime":
        return datetime.fromisoformat(value["value"])
    if type_name == "tuple":
        return tuple(_unpack(item) for item in value["items"])
    if type_name == "list":
        return [_unpack(item) for item in value["items"]]
    if type_name == "dict":
        return {
            _unpack(key): _unpack(item)
            for key, item in value["items"]
        }
    cls = _DATACLASS_TYPES[type_name]
    return cls(**{
        field_name: _unpack(field_value)
        for field_name, field_value in value["fields"].items()
    })

