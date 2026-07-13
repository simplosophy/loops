from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Literal


InputKind = Literal["prompt", "command", "shell"]
CommandKind = Literal["direct", "hlp", "compat"]


@dataclass(frozen=True)
class InputIntent:
    kind: InputKind
    raw: str
    text: str = ""
    name: str = ""
    args: tuple[str, ...] = ()
    mentions: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandDefinition:
    name: str
    summary: str
    kind: CommandKind
    covered: bool = True


class CommandParseError(ValueError):
    pass


COMMANDS: dict[str, CommandDefinition] = {
    "help": CommandDefinition("help", "Show command help.", "direct"),
    "new": CommandDefinition("new", "Start a new TUI session.", "direct"),
    "clear": CommandDefinition("clear", "Clear visible transcript.", "direct"),
    "resume": CommandDefinition("resume", "Resume a saved session.", "direct"),
    "fork": CommandDefinition("fork", "Fork current session metadata and transcript.", "direct"),
    "archive": CommandDefinition("archive", "Archive current session.", "direct"),
    "delete": CommandDefinition("delete", "Delete current session after confirmation.", "direct"),
    "permissions": CommandDefinition("permissions", "Set autonomy and permission mode.", "hlp"),
    "inbox": CommandDefinition("inbox", "Show HLP human inbox.", "hlp"),
    "approve": CommandDefinition("approve", "Approve current checkpoint.", "hlp"),
    "reject": CommandDefinition("reject", "Reject current checkpoint.", "hlp"),
    "choose": CommandDefinition("choose", "Resolve a choice checkpoint.", "hlp"),
    "input": CommandDefinition("input", "Provide text to an input checkpoint.", "hlp"),
    "amend": CommandDefinition("amend", "Append HLP steering amendment.", "hlp"),
    "soft": CommandDefinition(
        "soft",
        "Buffer soft control: /soft <text> | list | pop | clear.",
        "hlp",
    ),
    "softs": CommandDefinition("softs", "List buffered soft controls.", "hlp"),
    "promote": CommandDefinition(
        "promote",
        "Merge soft buffer (or one-shot text) into task.amend.",
        "hlp",
    ),
    "interrupt": CommandDefinition("interrupt", "Raise a human interrupt checkpoint.", "hlp"),
    "review": CommandDefinition("review", "Submit artifact review.", "hlp"),
    "audit": CommandDefinition("audit", "Replay HLP audit.", "hlp"),
    "diff": CommandDefinition("diff", "Show diff summary.", "direct"),
    "model": CommandDefinition("model", "Record preferred model metadata.", "compat"),
    "mcp": CommandDefinition("mcp", "Explain harness-owned MCP surface.", "compat"),
    "statusline": CommandDefinition("statusline", "Show status line fields.", "direct"),
    "theme": CommandDefinition("theme", "Record theme metadata.", "direct"),
    "vim": CommandDefinition("vim", "Record composer mode metadata.", "compat"),
    "compact": CommandDefinition("compact", "Record transcript summary event.", "compat"),
}


_MENTION = re.compile(r"(?<!\S)@([^\s]+)")


def parse_user_input(raw: str) -> InputIntent:
    value = raw.rstrip("\n")
    if not value.strip():
        raise CommandParseError("blank input is not allowed")
    normalized = value.lstrip()
    if normalized.startswith("!"):
        text = normalized[1:].strip()
        if not text:
            raise CommandParseError("shell input is empty")
        return InputIntent(kind="shell", raw=normalized, text=text, mentions=_mentions(text))
    if normalized.startswith("/"):
        return _parse_command(normalized)
    return InputIntent(kind="prompt", raw=value, text=value, mentions=_mentions(value))


def _parse_command(value: str) -> InputIntent:
    try:
        parts = tuple(shlex.split(value))
    except ValueError as exc:
        raise CommandParseError(str(exc)) from exc
    if not parts:
        raise CommandParseError("empty command")
    command_token = parts[0]
    name = command_token[1:]
    if not name or name not in COMMANDS:
        raise CommandParseError(f"unknown command: {command_token}")
    args = parts[1:]
    return InputIntent(
        kind="command",
        raw=value,
        name=name,
        args=args,
        mentions=_mentions(" ".join(args)),
    )


def _mentions(text: str) -> tuple[str, ...]:
    return tuple(match.group(1) for match in _MENTION.finditer(text))
