from __future__ import annotations

import json
from typing import Any

from ..types import HarnessEventKind
from . import _util as util
from .protocol import AgentAdapterError, AgentRunHandle, HarnessEvent


def parse_process_stdout(stdout: str) -> dict[str, Any]:
    stripped = stdout.strip()
    if not stripped:
        return {}
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        events: list[dict[str, Any]] = []
        for line in stripped.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("stdout line was not valid JSON") from exc
            if not isinstance(event, dict):
                raise ValueError("stdout JSONL lines must be objects") from None
            events.append(event)
        if not events:
            return {}
        for event in reversed(events):
            if "run_id" in event:
                return event
        return events[-1]
    if not isinstance(payload, dict):
        raise ValueError("stdout JSON must be an object")
    return payload


def parse_cli_stdout(stdout: str) -> dict[str, Any]:
    stripped = stdout.strip()
    if not stripped:
        return {}
    try:
        parsed = parse_process_stdout(stripped)
    except ValueError:
        parsed = None
    payload = extract_hlp_json_payload(parsed)
    if payload is not None:
        return payload
    payload = extract_hlp_json_payload(stripped)
    if payload is not None:
        return payload
    raise ValueError("stdout did not contain JSON object")


def extract_hlp_json_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        for key in (
            "result",
            "output_text",
            "final_output",
            "structured_output",
            "raw",
            "message",
            "text",
            "content",
        ):
            nested = extract_hlp_json_payload(value.get(key))
            if nested is not None:
                return nested
        item = value.get("item")
        if isinstance(item, dict):
            nested = extract_hlp_json_payload(item)
            if nested is not None:
                return nested
        if looks_like_hlp_payload(value):
            return value
        return None
    if isinstance(value, list):
        for item in reversed(value):
            nested = extract_hlp_json_payload(item)
            if nested is not None:
                return nested
        return None
    if isinstance(value, str):
        return extract_last_json_object(value)
    return None


def looks_like_hlp_payload(value: dict[str, Any]) -> bool:
    return any(key in value for key in ("run_id", "correlation_id", "status", "summary"))


def extract_last_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            nested = extract_hlp_json_payload(value)
            candidates.append(nested or value)
    for candidate in reversed(candidates):
        if looks_like_hlp_payload(candidate):
            return candidate
    return candidates[-1] if candidates else None


CODEX_EVENTS_KEY = "_codex_events"

# Result envelope schema for CLIs with native structured-output support
# (Codex --output-schema, Claude Code --json-schema). Protocol-mode requests ask
# the model for exactly this shape; "hlp" stays an optional nested channel for
# human-loop events. Kimi/Pi have no such flag and keep the prompt contract.
# Result envelope schema for CLIs with native structured-output support
# (Codex --output-schema, Claude Code --json-schema). Protocol-mode requests ask
# the model for exactly this shape. Human-loop events keep flowing through
# intermediate stream text (the existing extraction handles those); only the
# final message is schema-locked, which is what makes run_id/correlation_id
# deterministic. Codex strict mode requires additionalProperties: false.
HLP_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string"},
        "correlation_id": {"type": "string"},
        "status": {"type": "string", "enum": ["ok", "error"]},
        "summary": {"type": "string"},
        "error": {"type": "string"},
    },
    "required": ["run_id", "correlation_id", "status", "summary", "error"],
    "additionalProperties": False,
}


def parse_codex_stdout(stdout: str) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    events: list[dict[str, Any]] = []
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            if line.startswith(("{", "[")):
                raise ValueError("Codex JSON event line was invalid") from exc
            continue
        if not isinstance(event, dict):
            raise ValueError("Codex JSONL events must be objects")
        events.append(event)

    if not events:
        payload = parse_cli_stdout(stdout)
        events = [payload]

    payload = codex_result_payload(tuple(events))
    return payload, tuple(events)


def codex_result_payload(events: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    for event in reversed(events):
        if "run_id" in event:
            return dict(event)
        payload = extract_hlp_json_payload(event)
        if payload is not None and ("run_id" in payload or "correlation_id" in payload):
            return dict(payload)
    return dict(events[-1]) if events else {}


def pop_codex_events(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    raw_events = payload.pop(CODEX_EVENTS_KEY, ())
    if isinstance(raw_events, tuple):
        return tuple(event for event in raw_events if isinstance(event, dict))
    if isinstance(raw_events, list):
        return tuple(event for event in raw_events if isinstance(event, dict))
    return ()


def codex_run_id_from_events(events: tuple[dict[str, Any], ...]) -> str | None:
    for event in reversed(events):
        run_id = codex_event_run_id(event)
        if run_id is not None:
            return run_id
    return None


def codex_event_run_id(event: dict[str, Any]) -> str | None:
    payload = codex_hlp_payload(event)
    for value in (
        event.get("run_id"),
        event.get("id") if str(event.get("type", "")).endswith("run") else None,
        payload.get("run_id") if payload is not None else None,
    ):
        if value:
            return str(value)
    return None


def codex_event_id(event: dict[str, Any]) -> str | None:
    payload = codex_hlp_payload(event)
    for value in (
        event.get("_hlp_event_id"),
        payload.get("event_id") if payload is not None else None,
        event.get("event_id"),
        event.get("id"),
        event.get("seq"),
    ):
        if value:
            return str(value)
    return None


def validate_codex_event_correlations(
    events: tuple[dict[str, Any], ...],
    expected: str,
    adapter: str,
    operation: str,
) -> None:
    if not expected:
        return
    for event in events:
        actual = codex_event_correlation(event)
        if actual is not None and actual != expected:
            raise AgentAdapterError(
                adapter,
                operation,
                "runtime returned mismatched correlation_id",
                details={"expected": expected, "actual": actual},
            )


def codex_event_correlation(event: dict[str, Any]) -> str | None:
    payload = codex_hlp_payload(event)
    for value in (
        event.get("correlation_id"),
        event.get("hlp_task_id"),
        payload.get("correlation_id") if payload is not None else None,
        payload.get("task_id") if payload is not None else None,
        payload.get("hlp_task_id") if payload is not None else None,
    ):
        if value:
            return str(value)
    return None


def codex_event_to_harness_event(
    event: dict[str, Any],
    handle: AgentRunHandle,
) -> HarnessEvent | None:
    payload = codex_hlp_payload(event)
    if payload is not None:
        kind = normalize_codex_hlp_kind(
            payload.get("kind") or event.get("kind") or event.get("type")
        )
        if kind is None:
            return None
        return HarnessEvent(
            kind=kind,
            task_id=str(payload.get("task_id") or event.get("correlation_id") or handle.task_id),
            run_id=str(payload.get("run_id") or event.get("run_id") or handle.run_id),
            agent_id=str(payload.get("agent_id") or event.get("agent_id") or handle.agent_id),
            prompt=str(payload.get("prompt") or event.get("message") or ""),
            options=util.tuple_value(payload.get("options")),
            context=util.tuple_value(payload.get("context")),
            artifact_type=str(payload.get("artifact_type") or payload.get("type") or "artifact"),
            artifact_uri=str(payload.get("artifact_uri") or payload.get("uri") or ""),
            artifact_checksum=str(
                payload.get("artifact_checksum") or payload.get("checksum") or ""
            ),
            artifact_size=util.int_value(payload.get("artifact_size") or payload.get("size")),
        )

    artifact_uri = event.get("artifact_uri") or event.get("patch_uri") or event.get("diff_uri")
    if artifact_uri:
        return HarnessEvent(
            kind="artifact",
            task_id=str(event.get("correlation_id") or handle.task_id),
            run_id=str(event.get("run_id") or handle.run_id),
            agent_id=str(event.get("agent_id") or handle.agent_id),
            artifact_type=str(event.get("artifact_type") or "artifact"),
            artifact_uri=str(artifact_uri),
            artifact_checksum=str(event.get("artifact_checksum") or event.get("checksum") or ""),
            artifact_size=util.int_value(event.get("artifact_size") or event.get("size")),
        )
    return None


def codex_event_may_project(event: dict[str, Any]) -> bool:
    payload = codex_hlp_payload(event)
    if payload is not None:
        kind = normalize_codex_hlp_kind(
            payload.get("kind") or event.get("kind") or event.get("type")
        )
        return kind is not None
    return bool(event.get("artifact_uri") or event.get("patch_uri") or event.get("diff_uri"))


def codex_event_signature(event: dict[str, Any]) -> str | None:
    """Stable identity of the logical HLP event inside a raw stdout event.

    Some CLIs emit the same logical event twice in one stream (e.g. Claude
    Code's ``result`` envelope repeats the final assistant text). Adapters use
    this signature to drop such transport-level duplicates at queue time.
    """
    payload = codex_hlp_payload(event)
    if payload is not None:
        return json.dumps(payload, sort_keys=True, default=str)
    artifact_uri = event.get("artifact_uri") or event.get("patch_uri") or event.get("diff_uri")
    if artifact_uri:
        return json.dumps({"artifact_uri": str(artifact_uri)}, sort_keys=True)
    return None


def codex_hlp_payload(event: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("hlp", "human_loop", "humanLoop", "pi"):
        payload = event.get(key)
        if isinstance(payload, dict):
            return payload
    nested = extract_hlp_json_payload(event)
    if nested is not None and nested is not event:
        for key in ("hlp", "human_loop", "humanLoop"):
            payload = nested.get(key)
            if isinstance(payload, dict):
                merged = dict(payload)
                for metadata_key in (
                    "task_id",
                    "correlation_id",
                    "hlp_task_id",
                    "run_id",
                    "agent_id",
                ):
                    if metadata_key in nested and metadata_key not in merged:
                        merged[metadata_key] = nested[metadata_key]
                return merged
        return nested
    event_type = str(event.get("type") or "")
    if event_type.startswith(("hlp.", "pi.")) or event_type in {
        "needs_approval",
        "needs_choice",
        "needs_input",
        "artifact",
    }:
        return event
    return None


def normalize_codex_hlp_kind(value: Any) -> HarnessEventKind | None:
    aliases: dict[str, HarnessEventKind] = {
        "approval": "needs_approval",
        "approval_required": "needs_approval",
        "needs_approval": "needs_approval",
        "choice": "needs_choice",
        "choice_required": "needs_choice",
        "needs_choice": "needs_choice",
        "input": "needs_input",
        "input_required": "needs_input",
        "needs_input": "needs_input",
        "artifact": "artifact",
        "artifact_ready": "artifact",
        "patch": "artifact",
    }
    normalized = aliases.get(str(value or ""))
    if normalized in {"needs_approval", "needs_choice", "needs_input", "artifact"}:
        return normalized
    return None
