from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from typing import Any

from .audit import AuditEvent
from .objects import (
    AdapterOperationContext,
    AdapterOutboxRecord,
    Artifact,
    ArtifactPayload,
    ArtifactProvenance,
    ArtifactRef,
    Checkpoint,
    CheckpointOption,
    CheckpointResolution,
    Constraints,
    ControlSignal,
    Evidence,
    ExternalRef,
    HumanInboxItem,
    IdempotencyRecord,
    InputRef,
    InteractionRef,
    Ledger,
    LedgerEntry,
    Ownership,
    OwnershipTransfer,
    PermissionGrant,
    ProposedAction,
    Review,
    ReviewComment,
    SteeringAmendment,
    Task,
    TaskSpec,
)
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


def from_wire(name: str, value: dict[str, Any]) -> Any:
    """Reconstruct a typed HLP object from its wire dict (counterpart of to_wire).

    ``name`` is the wire object name ("Task", "Checkpoint", "AuditEvent", ...).
    Unknown names raise NOT_FOUND (mirrors schema_for). Unknown extra keys —
    e.g. the schema_version/profile stamps — are ignored. Missing required
    fields raise INVALID_SPEC, checked against HLP_JSON_SCHEMAS when a schema
    is registered for ``name``; otherwise the per-type builders fail fast.
    """
    builder = _FROM_WIRE_BUILDERS.get(name)
    if builder is None:
        raise ProtocolError("NOT_FOUND", f"schema {name!r} is not registered")
    if not isinstance(value, dict):
        raise ProtocolError("INVALID_SPEC", f"{name} wire value must be an object")
    schema = HLP_JSON_SCHEMAS.get(name)
    if schema is not None:
        for field in schema.get("required", ()):
            if field not in value:
                raise ProtocolError("INVALID_SPEC", f"{name} missing required field {field!r}")
    return builder(value)


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


# ════════════════════════════════════════════════════════════
# from_wire builders — hand-written per type (the inverse of to_wire)
# ════════════════════════════════════════════════════════════

_MISSING: Any = object()


def _wire_field(wire: dict[str, Any], name: str, default: Any = _MISSING) -> Any:
    """Read dataclass field ``name`` from a wire dict (alias-inverted: from_ ↔ from)."""
    key = _wire_field_name(name)
    if key in wire:
        return wire[key]
    if name in wire:
        return wire[name]
    if default is _MISSING:
        raise ProtocolError("INVALID_SPEC", f"missing required wire field {key!r}")
    return default


def _parse_datetime(value: Any) -> datetime:
    """Parse an ISO-8601 wire timestamp back to a datetime (handles trailing "Z")."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        return datetime.fromisoformat(text)
    raise ProtocolError("INVALID_SPEC", f"expected ISO-8601 datetime string, got {value!r}")


def _parse_optional_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    return _parse_datetime(value)


def _str_pair(value: Any) -> tuple[str, str]:
    items = tuple(value)
    if len(items) != 2:
        raise ProtocolError("INVALID_SPEC", f"expected a (kind, id) pair, got {value!r}")
    return str(items[0]), str(items[1])


def _input_ref_from_wire(wire: dict[str, Any]) -> InputRef:
    return InputRef(
        kind=_wire_field(wire, "kind"),
        id=_wire_field(wire, "id", None),
        version=_wire_field(wire, "version", None),
        uri=_wire_field(wire, "uri", None),
    )


def _external_ref_from_wire(wire: dict[str, Any]) -> ExternalRef:
    return ExternalRef(
        kind=_wire_field(wire, "kind"),
        namespace=_wire_field(wire, "namespace"),
        id=_wire_field(wire, "id"),
        version=_wire_field(wire, "version", None),
        label=_wire_field(wire, "label", None),
    )


def _permission_grant_from_wire(wire: dict[str, Any]) -> PermissionGrant:
    until = _wire_field(wire, "until", "task")
    if isinstance(until, str) and "T" in until:
        # PermissionGrant.until is str | datetime: ISO-8601 values with a time
        # component decode back to datetime; boundary labels ("task") stay str.
        until = _parse_datetime(until)
    return PermissionGrant(
        scope=_wire_field(wire, "scope"),
        decision=_wire_field(wire, "decision"),
        until=until,
        granted_by=_wire_field(wire, "granted_by", ""),
        granted_at=_parse_datetime(_wire_field(wire, "granted_at")),
    )


def _constraints_from_wire(wire: dict[str, Any]) -> Constraints:
    return Constraints(
        max_duration=_wire_field(wire, "max_duration", None),
        external_refs=tuple(
            _external_ref_from_wire(item) for item in _wire_field(wire, "external_refs", ())
        ),
        autonomy=_wire_field(wire, "autonomy", "autonomous"),
        grants=tuple(_permission_grant_from_wire(item) for item in _wire_field(wire, "grants", ())),
    )


def _task_spec_from_wire(wire: dict[str, Any]) -> TaskSpec:
    constraints = _wire_field(wire, "constraints", None)
    return TaskSpec(
        goal=_wire_field(wire, "goal"),
        acceptance_criteria=tuple(
            str(item) for item in _wire_field(wire, "acceptance_criteria", ())
        ),
        inputs=tuple(_input_ref_from_wire(item) for item in _wire_field(wire, "inputs", ())),
        constraints=_constraints_from_wire(constraints) if constraints is not None else None,
    )


def _steering_amendment_from_wire(wire: dict[str, Any]) -> SteeringAmendment:
    return SteeringAmendment(
        text=_wire_field(wire, "text"),
        intent=_wire_field(wire, "intent", "clarify"),
        by=_wire_field(wire, "by", ""),
        at=_parse_datetime(_wire_field(wire, "at")),
    )


def _interaction_ref_from_wire(wire: dict[str, Any]) -> InteractionRef:
    return InteractionRef(
        channel=_wire_field(wire, "channel"),
        session_id=_wire_field(wire, "session_id"),
        episode_id=_wire_field(wire, "episode_id", None),
    )


def _control_signal_from_wire(wire: dict[str, Any]) -> ControlSignal:
    interaction = _wire_field(wire, "interaction", None)
    return ControlSignal(
        strength=_wire_field(wire, "strength"),
        intent=_wire_field(wire, "intent"),
        principal_binding=_wire_field(wire, "principal_binding"),
        confidence=float(_wire_field(wire, "confidence", 1.0)),
        source_kind=_wire_field(wire, "source_kind", "text"),
        source_ref=_wire_field(wire, "source_ref", None),
        text=_wire_field(wire, "text", ""),
        promotion=_wire_field(wire, "promotion", "none"),
        run_id=_wire_field(wire, "run_id", None),
        interaction=_interaction_ref_from_wire(interaction) if interaction is not None else None,
        effective_at=_parse_datetime(_wire_field(wire, "effective_at")),
        recorded_at=_parse_datetime(_wire_field(wire, "recorded_at")),
    )


def _proposed_action_from_wire(wire: dict[str, Any]) -> ProposedAction:
    return ProposedAction(
        id=_wire_field(wire, "id"),
        kind=_wire_field(wire, "kind"),
        summary=_wire_field(wire, "summary"),
        permission_scope=_wire_field(wire, "permission_scope", None),
        detail=_wire_field(wire, "detail", None),
        risk=_wire_field(wire, "risk", "medium"),
    )


def _ownership_transfer_from_wire(wire: dict[str, Any]) -> OwnershipTransfer:
    return OwnershipTransfer(
        from_=_wire_field(wire, "from_"),
        to=_wire_field(wire, "to"),
        at=_parse_datetime(_wire_field(wire, "at")),
        via=_wire_field(wire, "via", "assign"),
    )


def _ownership_from_wire(wire: dict[str, Any]) -> Ownership:
    return Ownership(
        principal=_wire_field(wire, "principal"),
        assignee=_wire_field(wire, "assignee"),
        delegable=bool(_wire_field(wire, "delegable", True)),
        chain=tuple(_ownership_transfer_from_wire(item) for item in _wire_field(wire, "chain", ())),
    )


def _checkpoint_option_from_wire(wire: dict[str, Any]) -> CheckpointOption:
    return CheckpointOption(
        id=_wire_field(wire, "id"),
        label=_wire_field(wire, "label"),
        risk=_wire_field(wire, "risk", "medium"),
    )


def _evidence_from_wire(wire: dict[str, Any]) -> Evidence:
    return Evidence(
        kind=_wire_field(wire, "kind"),
        id=_wire_field(wire, "id", None),
        content=_wire_field(wire, "content", None),
    )


def _checkpoint_resolution_from_wire(wire: dict[str, Any]) -> CheckpointResolution:
    return CheckpointResolution(
        by=_wire_field(wire, "by"),
        action=_wire_field(wire, "action"),
        choice=_wire_field(wire, "choice", None),
        input=_wire_field(wire, "input", None),
        reassign_to=_wire_field(wire, "reassign_to", None),
        approved_actions=tuple(str(item) for item in _wire_field(wire, "approved_actions", ())),
        denied_actions=tuple(str(item) for item in _wire_field(wire, "denied_actions", ())),
        state_patch=_wire_field(wire, "state_patch", None),
        edited_artifact_ref=_wire_field(wire, "edited_artifact_ref", None),
        comment=_wire_field(wire, "comment", None),
        at=_parse_datetime(_wire_field(wire, "at")),
    )


def _review_comment_from_wire(wire: dict[str, Any]) -> ReviewComment:
    return ReviewComment(
        anchor=_wire_field(wire, "anchor"),
        severity=_wire_field(wire, "severity", "minor"),
        body=_wire_field(wire, "body", ""),
    )


def _artifact_provenance_from_wire(wire: dict[str, Any]) -> ArtifactProvenance:
    return ArtifactProvenance(
        produced_by=_wire_field(wire, "produced_by"),
        produced_at=_parse_datetime(_wire_field(wire, "produced_at")),
    )


def _artifact_payload_from_wire(wire: dict[str, Any]) -> ArtifactPayload:
    return ArtifactPayload(
        kind=_wire_field(wire, "kind"),
        uri=_wire_field(wire, "uri"),
        checksum=_wire_field(wire, "checksum"),
        size=int(_wire_field(wire, "size", 0)),
    )


def _artifact_ref_from_wire(wire: dict[str, Any]) -> ArtifactRef:
    return ArtifactRef(
        task_id=_wire_field(wire, "task_id"),
        as_=_wire_field(wire, "as_", "output"),
    )


def _ledger_entry_from_wire(wire: dict[str, Any]) -> LedgerEntry:
    return LedgerEntry(
        key=_wire_field(wire, "key"),
        value=_wire_field(wire, "value"),
        by=_wire_field(wire, "by"),
        written_at=_parse_datetime(_wire_field(wire, "written_at")),
    )


def _human_inbox_item_from_wire(wire: dict[str, Any]) -> HumanInboxItem:
    return HumanInboxItem(
        kind=_wire_field(wire, "kind"),
        action=_wire_field(wire, "action"),
        task_id=_wire_field(wire, "task_id"),
        subject_id=_wire_field(wire, "subject_id"),
        title=_wire_field(wire, "title"),
        principal=_wire_field(wire, "principal"),
        created_at=_parse_datetime(_wire_field(wire, "created_at")),
    )


def _adapter_operation_context_from_wire(wire: dict[str, Any]) -> AdapterOperationContext:
    return AdapterOperationContext(
        operation_id=_wire_field(wire, "operation_id"),
        task_id=_wire_field(wire, "task_id"),
        correlation_id=_wire_field(wire, "correlation_id"),
        operation=_wire_field(wire, "operation"),
        idempotency_key=_wire_field(wire, "idempotency_key", None),
        request_fingerprint=_wire_field(wire, "request_fingerprint"),
        task_revision=int(_wire_field(wire, "task_revision")),
    )


def _adapter_outbox_record_from_wire(wire: dict[str, Any]) -> AdapterOutboxRecord:
    return AdapterOutboxRecord(
        operation_id=_wire_field(wire, "operation_id"),
        task_id=_wire_field(wire, "task_id"),
        operation=_wire_field(wire, "operation"),
        request_fingerprint=_wire_field(wire, "request_fingerprint"),
        context=_adapter_operation_context_from_wire(_wire_field(wire, "context")),
        request=_wire_field(wire, "request"),
        result=_wire_field(wire, "result", None),
        state=_wire_field(wire, "state", "pending"),
        created_at=_parse_datetime(_wire_field(wire, "created_at")),
        updated_at=_parse_datetime(_wire_field(wire, "updated_at")),
    )


def _idempotency_record_from_wire(wire: dict[str, Any]) -> IdempotencyRecord:
    return IdempotencyRecord(
        task_id=_wire_field(wire, "task_id"),
        key=_wire_field(wire, "key"),
        operation=_wire_field(wire, "operation"),
        request_fingerprint=_wire_field(wire, "request_fingerprint"),
        revision_before=int(_wire_field(wire, "revision_before")),
        revision_after=int(_wire_field(wire, "revision_after")),
        result=_wire_field(wire, "result"),
        audit_seq_start=int(_wire_field(wire, "audit_seq_start")),
        audit_seq_end=int(_wire_field(wire, "audit_seq_end")),
    )


def _task_from_wire(wire: dict[str, Any]) -> Task:
    return Task(
        id=_wire_field(wire, "id"),
        type=_wire_field(wire, "type", ""),
        spec=_task_spec_from_wire(_wire_field(wire, "spec")),
        ownership=_ownership_from_wire(_wire_field(wire, "ownership")),
        state=_wire_field(wire, "state", "created"),
        parent_task=_wire_field(wire, "parent_task", None),
        created_at=_parse_datetime(_wire_field(wire, "created_at")),
        revision=int(_wire_field(wire, "revision", 0)),
        deadline=_parse_optional_datetime(_wire_field(wire, "deadline", None)),
        checkpoints=list(_wire_field(wire, "checkpoints", ())),
        artifacts=list(_wire_field(wire, "artifacts", ())),
        steering_log=tuple(
            _steering_amendment_from_wire(item) for item in _wire_field(wire, "steering_log", ())
        ),
    )


def _checkpoint_from_wire(wire: dict[str, Any]) -> Checkpoint:
    resolution = _wire_field(wire, "resolution", None)
    return Checkpoint(
        id=_wire_field(wire, "id"),
        task_id=_wire_field(wire, "task_id", ""),
        kind=_wire_field(wire, "kind", "approval"),
        prompt=_wire_field(wire, "prompt", ""),
        options=tuple(
            _checkpoint_option_from_wire(item) for item in _wire_field(wire, "options", ())
        ),
        proposed_actions=tuple(
            _proposed_action_from_wire(item) for item in _wire_field(wire, "proposed_actions", ())
        ),
        context=tuple(_evidence_from_wire(item) for item in _wire_field(wire, "context", ())),
        state=_wire_field(wire, "state", "pending"),
        raised_at=_parse_datetime(_wire_field(wire, "raised_at")),
        raised_by=_wire_field(wire, "raised_by", "agent"),
        expires_at=_parse_optional_datetime(_wire_field(wire, "expires_at", None)),
        resolution=(
            _checkpoint_resolution_from_wire(resolution) if resolution is not None else None
        ),
    )


def _review_from_wire(wire: dict[str, Any]) -> Review:
    # to_wire skips `_`-private fields, so a reconstructed Review is unsealed.
    return Review(
        id=_wire_field(wire, "id"),
        task_id=_wire_field(wire, "task_id", ""),
        artifact_id=_wire_field(wire, "artifact_id", ""),
        reviewer=_wire_field(wire, "reviewer", ""),
        kind=_wire_field(wire, "kind", "deliverable"),
        verdict=_wire_field(wire, "verdict"),
        comments=tuple(
            _review_comment_from_wire(item) for item in _wire_field(wire, "comments", ())
        ),
        requested_changes=tuple(str(item) for item in _wire_field(wire, "requested_changes", ())),
        at=_parse_datetime(_wire_field(wire, "at")),
    )


def _artifact_from_wire(wire: dict[str, Any]) -> Artifact:
    # to_wire skips `_`-private fields, so a reconstructed Artifact is unsealed.
    provenance = _wire_field(wire, "provenance", None)
    payload = _wire_field(wire, "payload", None)
    return Artifact(
        id=_wire_field(wire, "id"),
        type=_wire_field(wire, "type", ""),
        provenance=(_artifact_provenance_from_wire(provenance) if provenance is not None else None),
        version=_wire_field(wire, "version", "v1"),
        parent_version=_wire_field(wire, "parent_version", None),
        payload=_artifact_payload_from_wire(payload) if payload is not None else None,
        references=tuple(
            _artifact_ref_from_wire(item) for item in _wire_field(wire, "references", ())
        ),
    )


def _ledger_from_wire(wire: dict[str, Any]) -> Ledger:
    return Ledger(
        id=_wire_field(wire, "id"),
        scope=_wire_field(wire, "scope", ""),
        entries={
            str(key): tuple(_ledger_entry_from_wire(item) for item in history)
            for key, history in _wire_field(wire, "entries", {}).items()
        },
    )


def _audit_event_from_wire(wire: dict[str, Any]) -> AuditEvent:
    return AuditEvent(
        seq=int(_wire_field(wire, "seq")),
        at=_parse_datetime(_wire_field(wire, "at")),
        actor=_wire_field(wire, "actor", ""),
        action=_wire_field(wire, "action", ""),
        subject=_str_pair(_wire_field(wire, "subject")),
        task_id=_wire_field(wire, "task_id", None),
        before=_wire_field(wire, "before", None),
        after=_wire_field(wire, "after", None),
        reducer=_wire_field(wire, "reducer", None),
        id=_wire_field(wire, "id"),
        schema_version=_wire_field(wire, "schema_version", HLP_SCHEMA_VERSION),
        profile=_wire_field(wire, "profile", HLP_PROFILE),
        prev_hash=_wire_field(wire, "prev_hash", ""),
        hash=_wire_field(wire, "hash", ""),
    )


_FROM_WIRE_BUILDERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "AdapterOperationContext": _adapter_operation_context_from_wire,
    "AdapterOutboxRecord": _adapter_outbox_record_from_wire,
    "Artifact": _artifact_from_wire,
    "ArtifactPayload": _artifact_payload_from_wire,
    "ArtifactProvenance": _artifact_provenance_from_wire,
    "ArtifactRef": _artifact_ref_from_wire,
    "AuditEvent": _audit_event_from_wire,
    "Checkpoint": _checkpoint_from_wire,
    "CheckpointOption": _checkpoint_option_from_wire,
    "CheckpointResolution": _checkpoint_resolution_from_wire,
    "Constraints": _constraints_from_wire,
    "ControlSignal": _control_signal_from_wire,
    "Evidence": _evidence_from_wire,
    "ExternalRef": _external_ref_from_wire,
    "HumanInboxItem": _human_inbox_item_from_wire,
    "IdempotencyRecord": _idempotency_record_from_wire,
    "InputRef": _input_ref_from_wire,
    "InteractionRef": _interaction_ref_from_wire,
    "Ledger": _ledger_from_wire,
    "LedgerEntry": _ledger_entry_from_wire,
    "Ownership": _ownership_from_wire,
    "OwnershipTransfer": _ownership_transfer_from_wire,
    "PermissionGrant": _permission_grant_from_wire,
    "ProposedAction": _proposed_action_from_wire,
    "Review": _review_from_wire,
    "ReviewComment": _review_comment_from_wire,
    "SteeringAmendment": _steering_amendment_from_wire,
    "Task": _task_from_wire,
    "TaskSpec": _task_spec_from_wire,
}
