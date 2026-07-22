from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .commands import COMMANDS
from .session import TUISession

_GROUP_ORDER = ("session", "work", "hlp", "control", "other")
_GROUP_TITLES = {
    "session": "Session",
    "work": "Tasks & artifacts",
    "hlp": "Human-loop decisions",
    "control": "Continuous control",
    "other": "Other",
}


def render_help() -> str:
    lines = ["HLP TUI commands:"]
    for group in _GROUP_ORDER:
        members = sorted(
            (command for command in COMMANDS.values() if command.group == group),
            key=lambda command: command.name,
        )
        if not members:
            continue
        lines.append(f"\n{_GROUP_TITLES[group]}:")
        for command in members:
            lines.append(f"/{command.name:<12} {command.summary}")
    return "\n".join(lines)


def render_tasks(tasks: Iterable[Any], *, active_task_id: str) -> str:
    rows = []
    for task in tasks:
        marker = "*" if task.id == active_task_id else " "
        goal = (task.spec.goal or "")[:48]
        rows.append(f"{marker} {task.id}  {task.state:<12} {goal}")
    return render_lines("tasks (* = active):", rows)


def render_artifacts(artifacts: Iterable[Any]) -> str:
    rows = []
    for artifact in artifacts:
        payload = artifact.payload
        uri = payload.uri if payload else ""
        rows.append(f"{artifact.id}  {artifact.version:<5} {artifact.type:<12} {uri}")
    return render_lines("artifacts:", rows)


_STATE_MARKS = {
    "done": "✓",
    "in_progress": "◐",
    "pending": "○",
    "blocked": "✗",
    "skipped": "—",
}


def render_progress(snapshot: Any) -> str:
    """Render a run's ephemeral progress projection (checklist + agent tree)."""
    header = f"progress: run {snapshot.run_id}"
    if snapshot.summary:
        header += f" — {snapshot.summary}"
    lines = [header]
    for item in snapshot.items:
        lines.append(f"  {_STATE_MARKS.get(item.state, '?')} {item.label}")
    for agent in snapshot.agents:
        indent = "    " if agent.parent_id else "  "
        lines.append(f"{indent}▸ {agent.label or agent.id} ({agent.state})")
    if not snapshot.items and not snapshot.agents:
        lines.append("  (no progress events yet)")
    return "\n".join(lines)


def progress_summary_line(snapshot: Any) -> str:
    """One compact progress line for post-prompt display."""
    done = sum(1 for item in snapshot.items if item.state == "done")
    running = sum(1 for agent in snapshot.agents if agent.state == "running")
    parts = []
    if snapshot.items:
        parts.append(f"{done}/{len(snapshot.items)} todos")
    if snapshot.agents:
        parts.append(f"{running} agents running")
    if not parts and snapshot.summary:
        parts.append(snapshot.summary)
    return "progress " + " · ".join(parts) if parts else ""


def render_artifact_detail(artifact: Any) -> str:
    lines = [f"artifact {artifact.id}  version={artifact.version}"]
    if artifact.parent_version:
        lines.append(f"parent_version={artifact.parent_version}")
    if artifact.provenance is not None:
        lines.append(
            f"produced_by={artifact.provenance.produced_by} at={artifact.provenance.produced_at}"
        )
    payload = artifact.payload
    if payload is not None:
        lines.append(
            f"payload: kind={payload.kind} uri={payload.uri} "
            f"checksum={payload.checksum} size={payload.size}"
        )
    if artifact.references:
        refs = ", ".join(f"{ref.task_id}({ref.as_})" for ref in artifact.references)
        lines.append(f"referenced_by: {refs}")
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


def _error_hint(error: Exception) -> str:
    """One actionable recovery line per error family (industrial UX)."""
    name = error.__class__.__name__
    if name == "AgentAdapterError":
        return (
            "hint: check the CLI binary on PATH and its auth, or /adapter to "
            "switch harness; /interrupt pauses the task instead"
        )
    if name in {"TimeoutError", "TimeoutExpiredError"}:
        return "hint: the harness is slow — raise --timeout, or /interrupt to pause"
    code = getattr(error, "code", "")
    if code == "DEADLINE_EXCEEDED":
        return "hint: the harness is slow — raise --timeout, or /interrupt to pause"
    if code == "NOT_FOUND":
        return "hint: unknown object — list tasks with /tasks, sessions with /resume <id>"
    if code == "PRECONDITION_FAILED":
        return "hint: state conflict — /statusline and /inbox show what is actionable now"
    if code == "UNAUTHORIZED":
        return "hint: this action needs the task principal or a policy member"
    if name == "TUIUsageError":
        return "hint: usage — /help lists commands with forms"
    if name == "CommandParseError":
        return "hint: /help lists commands; typos get did-you-mean suggestions"
    return ""


def render_error(error: Exception) -> str:
    lines = [f"error: {error.__class__.__name__}: {error}"]
    details = getattr(error, "details", None)
    if isinstance(details, dict) and details:
        if details.get("exit_code") is not None:
            lines.append(f"exit_code: {details['exit_code']}")
        command = details.get("command")
        if command:
            # Keep the prompt short so the terminal stays readable.
            rendered = []
            for part in command:
                text = str(part)
                if len(text) > 80:
                    text = text[:77] + "..."
                rendered.append(text)
            lines.append(f"command: {' '.join(rendered)}")
        stderr = str(details.get("stderr") or "").strip()
        if stderr:
            tail = stderr if len(stderr) <= 400 else stderr[-400:]
            lines.append(f"stderr: {tail}")
        stdout = str(details.get("stdout") or "").strip()
        if stdout and not stderr:
            tail = stdout if len(stdout) <= 400 else stdout[-400:]
            lines.append(f"stdout: {tail}")
    hint = _error_hint(error)
    if hint:
        lines.append(hint)
    return "\n".join(lines)


def render_inbox(items: Iterable[Any]) -> str:
    rows = [
        f"{item.kind} {item.action} task={item.task_id} subject={item.subject_id} title={item.title}"
        for item in items
    ]
    return render_lines("Human inbox:", rows)


def render_soft_buffer(entries: Iterable[Any]) -> str:
    """Render host soft-control buffer before multi-signal promotion."""
    rows = []
    for index, entry in enumerate(entries, start=1):
        text = getattr(entry, "text", "")
        intent = getattr(entry, "intent", "constrain")
        confidence = getattr(entry, "confidence", 1.0)
        rows.append(f"{index}. [{intent} c={confidence:g}] {text}")
    return render_lines("Soft buffer (host merge → /promote):", rows)


def render_audit(events: Iterable[Any]) -> str:
    rows = [f"{event.action} task={event.task_id}" for event in events]
    return render_lines("Audit:", rows)


def agent_reply_text(payload: dict[str, Any] | None) -> str:
    """Extract reply text from a harness/process payload (no host prefix)."""
    if not payload:
        return ""
    for key in (
        "summary",
        "output_text",
        "final_output",
        "message",
        "text",
        "content",
        "result",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = agent_reply_text(value)
            if nested:
                return nested
        if isinstance(value, list):
            for item in reversed(value):
                if isinstance(item, dict):
                    nested = agent_reply_text(item)
                    if nested:
                        return nested
                elif isinstance(item, str) and item.strip():
                    return item.strip()
    return ""


def render_agent_reply(payload: dict[str, Any] | None) -> str:
    """Surface harness/process payload text for host channels.

    HLP human events (checkpoints/artifacts) are separate; coding harnesses often
    only return a summary/status JSON after a one-shot prompt. The TUI must still
    show that reply or the session looks empty after "started task".
    """
    text = agent_reply_text(payload)
    if text:
        return f"agent: {text}"
    if payload:
        status = payload.get("status")
        if status is not None and str(status).strip():
            return f"agent status: {status}"
    return ""


def render_human_loop(
    projected: Iterable[Any],
    inbox: Iterable[Any] | None = None,
) -> str:
    """Compact host summary after harness events are projected into HLP."""
    lines: list[str] = []
    for item in projected:
        prompt = getattr(item, "prompt", None)
        item_id = getattr(item, "id", "")
        if prompt is not None and hasattr(item, "state"):
            lines.append(f"checkpoint pending: {prompt} ({item_id})")
            continue
        payload = getattr(item, "payload", None)
        artifact_type = getattr(item, "type", "") or "artifact"
        if payload is not None:
            uri = getattr(payload, "uri", "") or ""
            suffix = f" {uri}" if uri else ""
            lines.append(f"artifact ready: {artifact_type} {item_id}{suffix}")
            continue
        name = item.__class__.__name__.lower()
        lines.append(f"projected {name}: {item_id}")

    pending = [
        item for item in (inbox or ()) if getattr(item, "kind", "") in {"checkpoint", "review"}
    ]
    if pending:
        lines.append(f"inbox: {len(pending)} item(s) — use /inbox, /approve, /reject, /review")
    return "\n".join(lines)


_BROADCAST_REPLY_LIMIT = 600


def render_broadcast(rows: Iterable[dict[str, str]]) -> str:
    """Side-by-side comparison of one prompt fanned out to every harness."""
    lines = ["broadcast results:"]
    for row in rows:
        task = row.get("task") or "n/a"
        run = row.get("run") or "n/a"
        lines.append(f"\n── {row['adapter']} ── task={task} run={run}")
        reply = row.get("reply", "")
        if len(reply) > _BROADCAST_REPLY_LIMIT:
            reply = reply[: _BROADCAST_REPLY_LIMIT - 3] + "..."
        body = reply.splitlines() if reply else ["(no reply)"]
        lines.extend(f"  {line}" for line in body)
    return "\n".join(lines)
