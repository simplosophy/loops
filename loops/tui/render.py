from __future__ import annotations

from typing import Any, Iterable

from .commands import COMMANDS
from .session import TUISession


def render_help() -> str:
    lines = ["HLP TUI commands:"]
    for name, command in sorted(COMMANDS.items()):
        lines.append(f"/{name:<12} {command.kind:<6} {command.summary}")
    return "\n".join(lines)


def render_status(
    session: TUISession,
    *,
    task_state: str = "none",
    inbox_count: int = 0,
) -> str:
    task = session.active_task_id or "none"
    return (
        f"session={session.id} adapter={session.adapter} task={task} "
        f"state={task_state} mode={session.permission_mode} inbox={inbox_count} cwd={session.cwd}"
    )


def render_transcript(session: TUISession) -> str:
    if not session.transcript:
        return "transcript is empty"
    return "\n".join(f"{event.kind}: {event.text}" for event in session.transcript)


def render_lines(title: str, rows: Iterable[str]) -> str:
    body = tuple(rows)
    if not body:
        return f"{title}\n(no items)"
    return "\n".join((title, *body))


def render_error(error: Exception) -> str:
    return f"error: {error.__class__.__name__}: {error}"


def render_inbox(items: Iterable[Any]) -> str:
    rows = [
        f"{item.kind} {item.action} task={item.task_id} subject={item.subject_id} title={item.title}"
        for item in items
    ]
    return render_lines("Human inbox:", rows)


def render_audit(events: Iterable[Any]) -> str:
    rows = [f"{event.action} task={event.task_id}" for event in events]
    return render_lines("Audit:", rows)
