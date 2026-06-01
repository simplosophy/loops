"""Logging adapters and formatting helpers for loops runtime events."""

from __future__ import annotations

import json
import logging as py_logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Protocol, TypeAlias, runtime_checkable

from loops.events import AgentEvent


@runtime_checkable
class EventLogger(Protocol):
    """Minimal logger contract used by the runtime."""

    def log_event(self, event: AgentEvent) -> None:
        """Record one runtime event."""


LoggerLike: TypeAlias = EventLogger | py_logging.Logger | Callable[[AgentEvent], None] | None


class NoopEventLogger:
    def log_event(self, event: AgentEvent) -> None:
        del event


@dataclass
class InMemoryEventLogger:
    """Test and embedding helper that stores runtime events in memory."""

    events: list[AgentEvent] = field(default_factory=list)

    def log_event(self, event: AgentEvent) -> None:
        self.events.append(event)


@dataclass
class CallableEventLogger:
    callback: Callable[[AgentEvent], None]

    def log_event(self, event: AgentEvent) -> None:
        self.callback(event)


@dataclass
class StdlibEventLogger:
    """Adapter from loops events to Python's standard logging.Logger."""

    logger: py_logging.Logger
    include_payload: bool = False

    def log_event(self, event: AgentEvent) -> None:
        message = format_event(event, include_payload=self.include_payload)
        self.logger.log(
            _event_level(event),
            message,
            extra={
                "loops_event_id": event.event_id,
                "loops_event_type": event.type,
                "loops_run_id": event.run_id,
            },
        )


def normalize_logger(logger: LoggerLike) -> EventLogger:
    if logger is None:
        return NoopEventLogger()
    if isinstance(logger, py_logging.Logger):
        return StdlibEventLogger(logger)
    if isinstance(logger, EventLogger):
        return logger
    if callable(logger):
        return CallableEventLogger(logger)
    raise TypeError("logger must be a logging.Logger, EventLogger, callable, or None")


def get_logger(name: str = "loops", *, level: int | str | None = None) -> py_logging.Logger:
    """Return a standard-library logger with a default stream handler."""

    logger = py_logging.getLogger(name)
    if not logger.handlers:
        handler = py_logging.StreamHandler()
        handler.setFormatter(py_logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    if level is not None:
        logger.setLevel(level)
    return logger


def format_event(event: AgentEvent, *, include_payload: bool = False) -> str:
    payload = event.payload
    base = f"{event.type} run_id={event.run_id}"
    if event.type == "run_started":
        base += f" thread_id={payload.get('thread_id')} channel={payload.get('channel')}"
    elif event.type == "run_finished":
        base += f" stop_reason={payload.get('stop_reason')} output_chars={len(str(payload.get('output') or ''))}"
    elif event.type == "run_failed":
        base += f" error_type={payload.get('error_type')} error={preview_text(payload.get('error'), max_chars=180)}"
    elif event.type == "provider_started":
        base += (
            f" provider={payload.get('provider')}/{payload.get('model')}"
            f" turn={payload.get('turn')} stream={payload.get('stream')}"
            f" parallel_tool_calls={payload.get('parallel_tool_calls')}"
            f" messages={payload.get('message_count')} tools={payload.get('tool_count')}"
        )
    elif event.type == "provider_finished":
        base += (
            f" turn={payload.get('turn')} tool_calls={payload.get('tool_call_count')}"
            f" stop_reason={payload.get('stop_reason')} content_chars={payload.get('content_chars')}"
        )
    elif event.type == "provider_delta":
        base += f" chars={len(str(payload.get('text') or ''))}"
    elif event.type == "provider_reasoning_delta":
        base += f" chars={len(str(payload.get('text') or ''))}"
    elif event.type == "tool_started":
        base += (
            f" tool={payload.get('tool_name')} call_id={payload.get('tool_call_id')}"
            f" {format_tool_arguments_inline(str(payload.get('tool_name') or 'tool'), payload.get('arguments') or {})}"
        )
    elif event.type == "tool_finished":
        base += (
            f" tool={payload.get('tool_name')} call_id={payload.get('tool_call_id')}"
            f" status={payload.get('status')} duration={format_duration_ms(payload.get('duration_ms'))}"
        )
        metadata = payload.get("metadata") or {}
        if isinstance(metadata, dict) and "returncode" in metadata:
            base += f" returncode={metadata.get('returncode')}"
        if payload.get("error"):
            base += f" error={preview_text(payload.get('error'), max_chars=180)}"
        else:
            base += f" output_chars={len(str(payload.get('output') or ''))}"
    if include_payload:
        base += f" payload={compact_json(payload, max_chars=1200)}"
    return base.strip()


def format_tool_arguments_inline(tool_name: str, arguments: dict[str, Any]) -> str:
    if tool_name == "shell":
        op = str(arguments.get("op") or "run")
        command = arguments.get("command")
        commands = arguments.get("commands")
        session_id = arguments.get("session_id")
        parts = [f"op={op}"]
        if command:
            parts.append(f"command={preview_text(command, max_chars=120)!r}")
        elif commands:
            parts.append(f"commands={preview_text(compact_json(commands, max_chars=180), max_chars=180)!r}")
        if session_id:
            parts.append(f"session_id={session_id}")
        return " ".join(parts)
    if not arguments:
        return "args={}"
    return f"args={compact_json(arguments, max_chars=240)}"


def format_tool_arguments_lines(tool_name: str, arguments: dict[str, Any]) -> list[str]:
    if tool_name == "shell":
        op = str(arguments.get("op") or "run")
        lines = [f"op: {op}"]
        if command := arguments.get("command"):
            lines.append(f"command: {preview_text(command, max_chars=400)}")
        elif commands := arguments.get("commands"):
            lines.append(f"commands: {compact_json(commands, max_chars=500)}")
        if session_id := arguments.get("session_id"):
            lines.append(f"session_id: {session_id}")
        if cwd := (arguments.get("cwd") or arguments.get("working_directory")):
            lines.append(f"cwd: {preview_text(cwd, max_chars=240)}")
        if arguments.get("background") is not None:
            lines.append(f"background: {str(bool(arguments.get('background'))).lower()}")
        if arguments.get("timeout_seconds") is not None:
            lines.append(f"timeout_seconds: {arguments.get('timeout_seconds')}")
        if arguments.get("timeout_ms") is not None:
            lines.append(f"timeout_ms: {arguments.get('timeout_ms')}")
        if arguments.get("max_output_chars") is not None:
            lines.append(f"max_output_chars: {arguments.get('max_output_chars')}")
        if arguments.get("max_output_length") is not None:
            lines.append(f"max_output_length: {arguments.get('max_output_length')}")
        if arguments.get("offset") is not None:
            lines.append(f"offset: {arguments.get('offset')}")
        if arguments.get("limit") is not None:
            lines.append(f"limit: {arguments.get('limit')}")
        if arguments.get("data") is not None:
            data = str(arguments.get("data") or "")
            lines.append(f"data: {len(data)} chars {preview_text(data, max_chars=160)!r}")
        if arguments.get("eof") is not None:
            lines.append(f"eof: {str(bool(arguments.get('eof'))).lower()}")
        return lines
    if not arguments:
        return ["arguments: {}"]
    return [f"arguments: {compact_json(arguments, max_chars=1000)}"]


def format_duration_ms(value: Any) -> str:
    if value is None:
        return "unknown"
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return str(value)
    if duration >= 1000:
        return f"{duration / 1000:.2f}s"
    return f"{duration:.0f}ms"


def preview_text(value: Any, *, max_chars: int = 1000) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip("\n") + "\n... [truncated]"


def compact_json(value: Any, *, max_chars: int = 1000) -> str:
    text = json.dumps(_to_log_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return preview_text(text, max_chars=max_chars)


def _event_level(event: AgentEvent) -> int:
    if event.type in {"provider_delta", "provider_reasoning_delta"}:
        return py_logging.DEBUG
    if event.type == "run_failed":
        return py_logging.ERROR
    if event.type == "tool_finished" and event.payload.get("status") != "success":
        return py_logging.WARNING
    return py_logging.INFO


def _to_log_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _to_log_safe(asdict(value))
    if isinstance(value, dict):
        return {
            str(key): "***" if _is_sensitive_key(str(key)) else _to_log_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_to_log_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_to_log_safe(item) for item in value)
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in ("api_key", "apikey", "password", "secret", "token", "authorization"))
