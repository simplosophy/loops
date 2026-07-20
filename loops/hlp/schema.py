from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from typing import Any

from .types import HLP_PROFILE, HLP_SCHEMA_VERSION, HLP_SPEC_VERSION, ProtocolError


@dataclass(frozen=True)
class VersionNegotiationResult:
    spec_version: str
    schema_version: str
    profile: str

    def to_dict(self) -> dict[str, str]:
        return {
            "spec_version": self.spec_version,
            "schema_version": self.schema_version,
            "profile": self.profile,
        }


HLP_JSON_SCHEMAS: dict[str, dict[str, Any]] = {
    "Task": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Task",
        "type": "object",
        "required": ["id", "spec", "ownership", "state", "revision", "schema_version", "profile"],
        "properties": {
            "id": {"type": "string"},
            "type": {"type": "string"},
            "spec": {"type": "object"},
            "ownership": {"type": "object"},
            "state": {"type": "string"},
            "revision": {"type": "integer"},
            "schema_version": {"type": "string", "const": HLP_SCHEMA_VERSION},
            "profile": {"type": "string", "const": HLP_PROFILE},
        },
    },
    "Checkpoint": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Checkpoint",
        "type": "object",
        "required": ["id", "task_id", "kind", "state", "schema_version", "profile"],
        "properties": {
            "id": {"type": "string"},
            "task_id": {"type": "string"},
            "kind": {"type": "string"},
            "state": {"type": "string"},
            "schema_version": {"type": "string", "const": HLP_SCHEMA_VERSION},
            "profile": {"type": "string", "const": HLP_PROFILE},
        },
    },
    "Ownership": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Ownership",
        "type": "object",
        "required": ["principal", "assignee", "delegable", "chain", "schema_version", "profile"],
        "properties": {
            "principal": {"type": "string"},
            "assignee": {"type": "string"},
            "delegable": {"type": "boolean"},
            "chain": {"type": "array"},
            "schema_version": {"type": "string", "const": HLP_SCHEMA_VERSION},
            "profile": {"type": "string", "const": HLP_PROFILE},
        },
    },
    "Review": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Review",
        "type": "object",
        "required": [
            "id",
            "task_id",
            "artifact_id",
            "reviewer",
            "verdict",
            "schema_version",
            "profile",
        ],
        "properties": {
            "id": {"type": "string"},
            "task_id": {"type": "string"},
            "artifact_id": {"type": "string"},
            "reviewer": {"type": "string"},
            "verdict": {"type": "string"},
            "schema_version": {"type": "string", "const": HLP_SCHEMA_VERSION},
            "profile": {"type": "string", "const": HLP_PROFILE},
        },
    },
    "Artifact": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Artifact",
        "type": "object",
        "required": ["id", "type", "version", "schema_version", "profile"],
        "properties": {
            "id": {"type": "string"},
            "type": {"type": "string"},
            "version": {"type": "string"},
            "schema_version": {"type": "string", "const": HLP_SCHEMA_VERSION},
            "profile": {"type": "string", "const": HLP_PROFILE},
        },
    },
    "Ledger": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Ledger",
        "type": "object",
        "required": ["id", "scope", "entries", "schema_version", "profile"],
        "properties": {
            "id": {"type": "string"},
            "scope": {"type": "string"},
            "entries": {"type": "object"},
            "schema_version": {"type": "string", "const": HLP_SCHEMA_VERSION},
            "profile": {"type": "string", "const": HLP_PROFILE},
        },
    },
    "ProtocolError": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ProtocolError",
        "type": "object",
        "required": [
            "code",
            "message",
            "details",
            "retryable",
            "operation_id",
            "correlation_id",
            "spec_version",
            "schema_version",
            "profile",
        ],
        "properties": {
            "code": {"type": "string"},
            "message": {"type": "string"},
            "details": {"type": "object"},
            "retryable": {"type": "boolean"},
            "operation_id": {"type": ["string", "null"]},
            "correlation_id": {"type": ["string", "null"]},
            "spec_version": {"type": "string", "const": HLP_SPEC_VERSION},
            "schema_version": {"type": "string", "const": HLP_SCHEMA_VERSION},
            "profile": {"type": "string", "const": HLP_PROFILE},
        },
    },
    "AuditEvent": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AuditEvent",
        "type": "object",
        "required": [
            "id",
            "seq",
            "actor",
            "action",
            "subject",
            "schema_version",
            "profile",
            "prev_hash",
            "hash",
        ],
        "properties": {
            "id": {"type": "string"},
            "seq": {"type": "integer"},
            "actor": {"type": "string"},
            "action": {"type": "string"},
            "subject": {"type": "array"},
            "task_id": {"type": ["string", "null"]},
            "reducer": {"type": ["object", "null"]},
            "schema_version": {"type": "string", "const": HLP_SCHEMA_VERSION},
            "profile": {"type": "string", "const": HLP_PROFILE},
            "prev_hash": {"type": "string"},
            "hash": {"type": "string"},
        },
    },
    "HarnessEvent": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "HarnessEvent",
        "type": "object",
        "required": ["kind", "task_id", "run_id", "agent_id", "schema_version", "profile"],
        "properties": {
            "kind": {"type": "string"},
            "task_id": {"type": "string"},
            "run_id": {"type": "string"},
            "agent_id": {"type": "string"},
            "schema_version": {"type": "string", "const": HLP_SCHEMA_VERSION},
            "profile": {"type": "string", "const": HLP_PROFILE},
        },
    },
    "HarnessEventDelivery": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "HarnessEventDelivery",
        "type": "object",
        "required": ["cursor", "event", "schema_version", "profile"],
        "properties": {
            "cursor": {"type": "string"},
            "event": {"type": "object"},
            "schema_version": {"type": "string", "const": HLP_SCHEMA_VERSION},
            "profile": {"type": "string", "const": HLP_PROFILE},
        },
    },
    "PermissionGrant": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "PermissionGrant",
        "type": "object",
        "required": [
            "scope",
            "decision",
            "until",
            "granted_by",
            "granted_at",
            "schema_version",
            "profile",
        ],
        "properties": {
            "scope": {"type": "string"},
            "decision": {"type": "string", "enum": ["allow", "deny"]},
            "until": {"type": ["string", "null"]},
            "granted_by": {"type": "string"},
            "granted_at": {"type": "string"},
            "schema_version": {"type": "string", "const": HLP_SCHEMA_VERSION},
            "profile": {"type": "string", "const": HLP_PROFILE},
        },
    },
    "ProposedAction": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ProposedAction",
        "type": "object",
        "required": ["id", "kind", "summary", "permission_scope", "risk"],
        "properties": {
            "id": {"type": "string"},
            "kind": {"type": "string"},
            "summary": {"type": "string"},
            "permission_scope": {"type": ["string", "null"]},
            "detail": {"type": ["object", "null"]},
            "risk": {"type": "string", "enum": ["low", "medium", "high"]},
            "schema_version": {"type": "string", "const": HLP_SCHEMA_VERSION},
            "profile": {"type": "string", "const": HLP_PROFILE},
        },
    },
    "AdapterOperationContext": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AdapterOperationContext",
        "type": "object",
        "required": [
            "operation_id",
            "task_id",
            "correlation_id",
            "operation",
            "idempotency_key",
            "request_fingerprint",
            "task_revision",
            "schema_version",
            "profile",
        ],
        "properties": {
            "operation_id": {"type": "string"},
            "task_id": {"type": "string"},
            "correlation_id": {"type": "string"},
            "operation": {"type": "string"},
            "idempotency_key": {"type": ["string", "null"]},
            "request_fingerprint": {"type": "string"},
            "task_revision": {"type": "integer"},
            "schema_version": {"type": "string", "const": HLP_SCHEMA_VERSION},
            "profile": {"type": "string", "const": HLP_PROFILE},
        },
    },
    "AdapterOutboxRecord": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "AdapterOutboxRecord",
        "type": "object",
        "required": [
            "operation_id",
            "task_id",
            "operation",
            "request_fingerprint",
            "context",
            "request",
            "state",
            "created_at",
            "updated_at",
            "schema_version",
            "profile",
        ],
        "properties": {
            "operation_id": {"type": "string"},
            "task_id": {"type": "string"},
            "operation": {"type": "string"},
            "request_fingerprint": {"type": "string"},
            "context": {"type": "object"},
            "request": {"type": "object"},
            "result": {},
            "state": {"type": "string", "enum": ["pending", "succeeded", "failed"]},
            "created_at": {"type": "string"},
            "updated_at": {"type": "string"},
            "schema_version": {"type": "string", "const": HLP_SCHEMA_VERSION},
            "profile": {"type": "string", "const": HLP_PROFILE},
        },
    },
    "VersionNegotiation": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "VersionNegotiation",
        "type": "object",
        "required": ["spec_version", "schema_version", "profile"],
        "properties": {
            "spec_version": {"type": "string", "const": HLP_SPEC_VERSION},
            "schema_version": {"type": "string", "const": HLP_SCHEMA_VERSION},
            "profile": {"type": "string", "const": HLP_PROFILE},
        },
    },
}


def to_wire(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        wire: dict[str, Any] = {}
        for field in fields(value):
            if field.name.startswith("_"):
                continue
            wire[_wire_field_name(field.name)] = to_wire(getattr(value, field.name))
        wire.setdefault("schema_version", HLP_SCHEMA_VERSION)
        wire.setdefault("profile", HLP_PROFILE)
        return wire
    if isinstance(value, tuple):
        return [to_wire(item) for item in value]
    if isinstance(value, list):
        return [to_wire(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_wire(item) for key, item in value.items()}
    return value


def schema_for(name: str) -> dict[str, Any]:
    try:
        return deepcopy(HLP_JSON_SCHEMAS[name])
    except KeyError as exc:
        raise ProtocolError("NOT_FOUND", f"schema {name!r} is not registered") from exc


def validate_wire_object(name: str, value: dict[str, Any]) -> None:
    schema = schema_for(name)
    for field in schema.get("required", ()):
        if field not in value:
            raise ProtocolError("INVALID_SPEC", f"{name} missing required field {field!r}")

    for field, rules in schema.get("properties", {}).items():
        if field not in value:
            continue
        if "const" in rules and value[field] != rules["const"]:
            raise ProtocolError(
                "VERSION_UNSUPPORTED",
                f"{name}.{field} must be {rules['const']!r}",
            )
        if "enum" in rules and value[field] not in rules["enum"]:
            raise ProtocolError("INVALID_SPEC", f"{name}.{field} is not in enum")
        expected_type = rules.get("type")
        if expected_type is not None and not _matches_type(value[field], expected_type):
            raise ProtocolError("INVALID_SPEC", f"{name}.{field} has wrong type")


def negotiate_hlp_version(
    *,
    spec_versions: tuple[str, ...],
    schema_versions: tuple[str, ...],
    profiles: tuple[str, ...],
) -> VersionNegotiationResult:
    if HLP_SPEC_VERSION not in spec_versions:
        raise ProtocolError(
            "VERSION_UNSUPPORTED",
            "no supported HLP spec version",
            details={"supported": HLP_SPEC_VERSION, "offered": spec_versions},
        )
    if HLP_SCHEMA_VERSION not in schema_versions:
        raise ProtocolError(
            "VERSION_UNSUPPORTED",
            "no supported HLP schema version",
            details={"supported": HLP_SCHEMA_VERSION, "offered": schema_versions},
        )
    if HLP_PROFILE not in profiles:
        raise ProtocolError(
            "VERSION_UNSUPPORTED",
            "no supported HLP profile",
            details={"supported": HLP_PROFILE, "offered": profiles},
        )
    return VersionNegotiationResult(
        spec_version=HLP_SPEC_VERSION,
        schema_version=HLP_SCHEMA_VERSION,
        profile=HLP_PROFILE,
    )


def _matches_type(value: Any, expected_type: str | list[str]) -> bool:
    expected = [expected_type] if isinstance(expected_type, str) else expected_type
    return any(_matches_single_type(value, item) for item in expected)


def _matches_single_type(value: Any, expected_type: str) -> bool:
    if expected_type == "null":
        return value is None
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, (list, tuple))
    return False


def _wire_field_name(name: str) -> str:
    if name.endswith("_"):
        return name[:-1]
    return name
