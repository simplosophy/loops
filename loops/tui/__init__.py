from __future__ import annotations

from .app import build_client, main, run_lines, run_with_progress
from .stream import StreamPrinter
from .commands import CommandDefinition, CommandParseError, InputIntent, parse_user_input
from .compat import CompatibilityReport, compatibility_report
from .controller import TUIController, TUIResult, TUISessionError, TUIUsageError
from .render import (
    render_agent_reply,
    render_audit,
    render_error,
    render_help,
    render_human_loop,
    render_inbox,
    render_lines,
    render_status,
    render_transcript,
)
from .session import SessionStore, TUISession, TranscriptEvent

__all__ = [
    "CommandDefinition",
    "CommandParseError",
    "CompatibilityReport",
    "InputIntent",
    "SessionStore",
    "TUISession",
    "TUISessionError",
    "TranscriptEvent",
    "TUIUsageError",
    "build_client",
    "compatibility_report",
    "main",
    "TUIController",
    "TUIResult",
    "parse_user_input",
    "render_agent_reply",
    "render_audit",
    "render_error",
    "render_help",
    "render_human_loop",
    "render_inbox",
    "render_lines",
    "render_status",
    "render_transcript",
    "run_lines",
    "run_with_progress",
    "StreamPrinter",
]
