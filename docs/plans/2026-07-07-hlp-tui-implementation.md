# HLP TUI Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a line-oriented HLP TUI channel that covers the common Claude Code / Codex interaction surface while preserving HLP's SDK-only architecture boundary.

**Architecture:** Add a new `loops.tui` package that depends on `loops.hlp` and owns only terminal-channel concerns: command parsing, session transcript, rendering, controller orchestration, and a console script. HLP remains channel-agnostic; all agent execution still flows through existing `AgentAdapter` / `HarnessAdapter` implementations.

**Tech Stack:** Python 3.13 standard library, existing `loops.hlp` SDK, `pytest`, setuptools console scripts.

---

## Source Inputs

- Approved design plan: `docs/plans/2026-07-07-hlp-tui.md`
- Architecture guardrail: `docs/architecture/OVERVIEW.md`
- HLP SDK facade: `loops/hlp/sdk.py`
- HLP objects and adapters: `loops/hlp/objects.py`, `loops/hlp/adapters.py`
- Existing test style: `tests/test_hlp_sdk.py`

## File Structure

| Path | Responsibility |
|---|---|
| `loops/tui/__init__.py` | Public TUI API exports |
| `loops/tui/commands.py` | Slash command parser, `@file` mention parser, `!shell` input classifier, command catalog |
| `loops/tui/compat.py` | Claude Code / Codex compatibility matrix and coverage calculation |
| `loops/tui/session.py` | In-memory and JSON-backed session state, transcript events, fork/resume/archive/delete |
| `loops/tui/render.py` | Deterministic plain-text rendering for help, status, inbox, audit, errors, and transcript |
| `loops/tui/controller.py` | TUI intents mapped to `HLPClient` operations |
| `loops/tui/app.py` | Line-oriented CLI shell and `main()` entry point |
| `examples/hlp_tui_demo.py` | Offline demo that exercises prompt, checkpoint, approval, artifact, review, and audit |
| `tests/test_hlp_tui.py` | TUI parser, compatibility, session, render, controller, app, and demo tests |
| `pyproject.toml` | Adds `loops-hlp-tui` console script |

## Task 1: Command Parser and Compatibility Catalog

**Files:**
- Create: `loops/tui/__init__.py`
- Create: `loops/tui/commands.py`
- Create: `loops/tui/compat.py`
- Test: `tests/test_hlp_tui.py`

- [ ] **Step 1: Write failing parser and compatibility tests**

Add these tests to a new `tests/test_hlp_tui.py`:

```python
from __future__ import annotations

from loops.tui.commands import (
    CommandParseError,
    InputIntent,
    parse_user_input,
)
from loops.tui.compat import compatibility_report


def test_parse_slash_command_with_quoted_args_and_file_mentions():
    intent = parse_user_input('/review approved "looks good" @src/app.py')

    assert intent == InputIntent(
        kind="command",
        name="review",
        args=("approved", "looks good", "@src/app.py"),
        raw='/review approved "looks good" @src/app.py',
        mentions=("src/app.py",),
    )


def test_parse_prompt_and_shell_capture():
    prompt = parse_user_input("inspect @README.md and summarize")
    shell = parse_user_input("!git status --short")

    assert prompt.kind == "prompt"
    assert prompt.text == "inspect @README.md and summarize"
    assert prompt.mentions == ("README.md",)
    assert shell.kind == "shell"
    assert shell.text == "git status --short"


def test_unknown_slash_command_fails_without_mutation():
    try:
        parse_user_input("/unknown")
    except CommandParseError as exc:
        assert "unknown command: /unknown" in str(exc)
    else:
        raise AssertionError("unknown command should fail")


def test_compatibility_report_meets_first_version_threshold():
    report = compatibility_report()

    assert report.total >= 20
    assert report.covered >= 18
    assert report.coverage >= 0.90
    assert "/help" in report.commands
    assert "/permissions" in report.commands
    assert "/audit" in report.commands
```

- [ ] **Step 2: Run parser tests to verify RED**

Run:

```bash
uv run pytest tests/test_hlp_tui.py::test_parse_slash_command_with_quoted_args_and_file_mentions -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'loops.tui'`.

- [ ] **Step 3: Implement parser and compatibility catalog**

Create `loops/tui/__init__.py`:

```python
from __future__ import annotations

from .commands import CommandDefinition, CommandParseError, InputIntent, parse_user_input
from .compat import CompatibilityReport, compatibility_report

__all__ = [
    "CommandDefinition",
    "CommandParseError",
    "CompatibilityReport",
    "InputIntent",
    "compatibility_report",
    "parse_user_input",
]
```

Create `loops/tui/commands.py`:

```python
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
    "delete": CommandDefinition("delete", "Delete a saved session.", "direct"),
    "permissions": CommandDefinition("permissions", "Set autonomy and permission mode.", "hlp"),
    "inbox": CommandDefinition("inbox", "Show HLP human inbox.", "hlp"),
    "approve": CommandDefinition("approve", "Approve current checkpoint.", "hlp"),
    "reject": CommandDefinition("reject", "Reject current checkpoint.", "hlp"),
    "choose": CommandDefinition("choose", "Resolve a choice checkpoint.", "hlp"),
    "input": CommandDefinition("input", "Provide text to an input checkpoint.", "hlp"),
    "amend": CommandDefinition("amend", "Append HLP steering amendment.", "hlp"),
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
    if value.startswith("!"):
        text = value[1:].strip()
        return InputIntent(kind="shell", raw=value, text=text, mentions=_mentions(text))
    if value.startswith("/"):
        return _parse_command(value)
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
```

Create `loops/tui/compat.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from .commands import COMMANDS


@dataclass(frozen=True)
class CompatibilityReport:
    total: int
    covered: int
    coverage: float
    commands: tuple[str, ...]


def compatibility_report() -> CompatibilityReport:
    commands = tuple(f"/{name}" for name in sorted(COMMANDS))
    total = len(COMMANDS)
    covered = sum(1 for command in COMMANDS.values() if command.covered)
    return CompatibilityReport(
        total=total,
        covered=covered,
        coverage=covered / total,
        commands=commands,
    )
```

- [ ] **Step 4: Run parser tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_hlp_tui.py::test_parse_slash_command_with_quoted_args_and_file_mentions tests/test_hlp_tui.py::test_parse_prompt_and_shell_capture tests/test_hlp_tui.py::test_unknown_slash_command_fails_without_mutation tests/test_hlp_tui.py::test_compatibility_report_meets_first_version_threshold -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add loops/tui/__init__.py loops/tui/commands.py loops/tui/compat.py tests/test_hlp_tui.py
git commit -m "feat: add HLP TUI command parser"
```

## Task 2: Session State and Deterministic Rendering

**Files:**
- Create: `loops/tui/session.py`
- Create: `loops/tui/render.py`
- Modify: `loops/tui/__init__.py`
- Test: `tests/test_hlp_tui.py`

- [ ] **Step 1: Write failing session and render tests**

Append to `tests/test_hlp_tui.py`:

```python
from loops.tui.render import render_help, render_status, render_transcript
from loops.tui.session import SessionStore, TranscriptEvent


def test_session_store_new_fork_archive_delete_roundtrip(tmp_path):
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="fake")
    session = store.append(session.id, TranscriptEvent(kind="user", text="review @README.md"))
    fork = store.fork(session.id)
    archived = store.archive(session.id)

    assert archived.archived is True
    assert fork.id != session.id
    assert fork.transcript[0].text == "review @README.md"
    assert store.resume(fork.id).id == fork.id

    store.delete(session.id)
    assert [item.id for item in store.list()] == [fork.id]


def test_render_help_status_and_transcript_are_stable(tmp_path):
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="fake")
    session = store.append(session.id, TranscriptEvent(kind="user", text="inspect"))

    help_text = render_help()
    status = render_status(session, task_state="in_progress", inbox_count=2)
    transcript = render_transcript(session)

    assert "/help" in help_text
    assert "adapter=fake" in status
    assert "state=in_progress" in status
    assert "inbox=2" in status
    assert "user: inspect" in transcript
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run pytest tests/test_hlp_tui.py::test_session_store_new_fork_archive_delete_roundtrip -q
```

Expected: FAIL with `ModuleNotFoundError` or import error for `loops.tui.session`.

- [ ] **Step 3: Implement session state**

Create `loops/tui/session.py`:

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TranscriptEvent:
    kind: str
    text: str
    at: str = field(default_factory=_now)
    ref: str = ""


@dataclass(frozen=True)
class TUISession:
    id: str
    cwd: str
    adapter: str
    principal: str = "user_local"
    active_task_id: str = ""
    active_run_id: str = ""
    permission_mode: str = "auto"
    model: str = ""
    theme: str = "system"
    composer_mode: str = "default"
    archived: bool = False
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    transcript: tuple[TranscriptEvent, ...] = ()


class SessionStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def create(self, *, cwd: str, adapter: str, principal: str = "user_local") -> TUISession:
        session = TUISession(
            id=f"tui_{uuid4().hex[:12]}",
            cwd=cwd,
            adapter=adapter,
            principal=principal,
        )
        sessions = self._load()
        sessions[session.id] = session
        self._save(sessions)
        return session

    def resume(self, session_id: str) -> TUISession:
        sessions = self._load()
        if session_id not in sessions:
            raise KeyError(f"unknown session: {session_id}")
        return sessions[session_id]

    def list(self) -> list[TUISession]:
        return sorted(self._load().values(), key=lambda item: item.updated_at)

    def append(self, session_id: str, event: TranscriptEvent) -> TUISession:
        session = self.resume(session_id)
        updated = self._replace(
            session,
            transcript=(*session.transcript, event),
            updated_at=_now(),
        )
        self._put(updated)
        return updated

    def set_active(self, session_id: str, *, task_id: str, run_id: str) -> TUISession:
        session = self.resume(session_id)
        updated = self._replace(
            session,
            active_task_id=task_id,
            active_run_id=run_id,
            updated_at=_now(),
        )
        self._put(updated)
        return updated

    def set_preference(self, session_id: str, *, field: str, value: str) -> TUISession:
        session = self.resume(session_id)
        allowed = {"permission_mode", "model", "theme", "composer_mode"}
        if field not in allowed:
            raise ValueError(f"unsupported preference: {field}")
        updated = self._replace(session, **{field: value, "updated_at": _now()})
        self._put(updated)
        return updated

    def clear_visible(self, session_id: str) -> TUISession:
        session = self.resume(session_id)
        updated = self._replace(session, transcript=(), updated_at=_now())
        self._put(updated)
        return updated

    def fork(self, session_id: str) -> TUISession:
        session = self.resume(session_id)
        forked = self._replace(
            session,
            id=f"tui_{uuid4().hex[:12]}",
            active_task_id="",
            active_run_id="",
            archived=False,
            created_at=_now(),
            updated_at=_now(),
        )
        self._put(forked)
        return forked

    def archive(self, session_id: str) -> TUISession:
        session = self.resume(session_id)
        updated = self._replace(session, archived=True, updated_at=_now())
        self._put(updated)
        return updated

    def delete(self, session_id: str) -> None:
        sessions = self._load()
        sessions.pop(session_id, None)
        self._save(sessions)

    def _put(self, session: TUISession) -> None:
        sessions = self._load()
        sessions[session.id] = session
        self._save(sessions)

    def _load(self) -> dict[str, TUISession]:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text())
        return {
            item["id"]: TUISession(
                **{
                    **item,
                    "transcript": tuple(TranscriptEvent(**event) for event in item.get("transcript", ())),
                }
            )
            for item in data
        }

    def _save(self, sessions: dict[str, TUISession]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = []
        for session in sorted(sessions.values(), key=lambda item: item.updated_at):
            row = asdict(session)
            row["transcript"] = [asdict(event) for event in session.transcript]
            payload.append(row)
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    @staticmethod
    def _replace(session: TUISession, **changes: object) -> TUISession:
        values = asdict(session)
        values.update(changes)
        values["transcript"] = tuple(
            event if isinstance(event, TranscriptEvent) else TranscriptEvent(**event)
            for event in values["transcript"]
        )
        return TUISession(**values)
```

- [ ] **Step 4: Implement deterministic renderers**

Create `loops/tui/render.py`:

```python
from __future__ import annotations

from typing import Iterable, Any

from .commands import COMMANDS
from .session import TUISession


def render_help() -> str:
    lines = ["HLP TUI commands:"]
    for name, command in sorted(COMMANDS.items()):
        lines.append(f"/{name:<12} {command.kind:<6} {command.summary}")
    return "\n".join(lines)


def render_status(session: TUISession, *, task_state: str = "none", inbox_count: int = 0) -> str:
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
```

Modify `loops/tui/__init__.py` to export session and rendering helpers:

```python
from __future__ import annotations

from .commands import CommandDefinition, CommandParseError, InputIntent, parse_user_input
from .compat import CompatibilityReport, compatibility_report
from .render import render_help, render_status, render_transcript
from .session import SessionStore, TUISession, TranscriptEvent

__all__ = [
    "CommandDefinition",
    "CommandParseError",
    "CompatibilityReport",
    "InputIntent",
    "SessionStore",
    "TUISession",
    "TranscriptEvent",
    "compatibility_report",
    "parse_user_input",
    "render_help",
    "render_status",
    "render_transcript",
]
```

- [ ] **Step 5: Run session/render tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_hlp_tui.py::test_session_store_new_fork_archive_delete_roundtrip tests/test_hlp_tui.py::test_render_help_status_and_transcript_are_stable -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add loops/tui/__init__.py loops/tui/session.py loops/tui/render.py tests/test_hlp_tui.py
git commit -m "feat: add HLP TUI sessions and rendering"
```

## Task 3: Controller Prompt, Steering, and Direct Commands

**Files:**
- Create: `loops/tui/controller.py`
- Modify: `loops/tui/__init__.py`
- Test: `tests/test_hlp_tui.py`

- [ ] **Step 1: Write failing controller tests**

Append to `tests/test_hlp_tui.py`:

```python
from loops.hlp import FakeAgentAdapter, HLPClient
from loops.tui.controller import TUIController


def run(coro):
    import asyncio

    return asyncio.run(coro)


def test_submit_prompt_creates_delegates_and_starts_task(tmp_path):
    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="fake")
    controller = TUIController(client=client, sessions=store)

    result = run(controller.handle(session.id, "Review the patch"))
    updated = store.resume(session.id)
    task = run(client.get_task(updated.active_task_id))

    assert "started task" in result.output
    assert task.state == "in_progress"
    assert updated.active_run_id
    assert [name for name, _payload in adapter.calls] == ["delegate"]


def test_submit_prompt_on_active_task_amends_instead_of_new_delegate(tmp_path):
    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="fake")
    controller = TUIController(client=client, sessions=store)

    run(controller.handle(session.id, "Review the patch"))
    result = run(controller.handle(session.id, "Focus on auth boundaries"))
    updated = store.resume(session.id)
    task = run(client.get_task(updated.active_task_id))

    assert "amended task" in result.output
    assert task.steering_log[-1].text == "Focus on auth boundaries"
    assert [name for name, _payload in adapter.calls] == ["delegate", "steer"]


def test_direct_session_commands_do_not_mutate_hlp(tmp_path):
    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="fake")
    controller = TUIController(client=client, sessions=store)

    help_result = run(controller.handle(session.id, "/help"))
    clear_result = run(controller.handle(session.id, "/clear"))
    model_result = run(controller.handle(session.id, "/model gpt-5"))

    assert "/help" in help_result.output
    assert "cleared transcript" in clear_result.output
    assert "model=gpt-5" in model_result.output
    assert adapter.calls == []
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run pytest tests/test_hlp_tui.py::test_submit_prompt_creates_delegates_and_starts_task -q
```

Expected: FAIL with import error for `loops.tui.controller`.

- [ ] **Step 3: Implement controller result and prompt flow**

Create `loops/tui/controller.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loops.hlp import Constraints, HLPClient, ProtocolError

from .commands import CommandParseError, InputIntent, parse_user_input
from .render import render_audit, render_error, render_help, render_inbox, render_status, render_transcript
from .session import SessionStore, TranscriptEvent


@dataclass(frozen=True)
class TUIResult:
    output: str
    should_exit: bool = False


class TUIController:
    def __init__(
        self,
        *,
        client: HLPClient,
        sessions: SessionStore,
        agent_id: str = "agent_tui",
        capability: str = "coding-agent",
    ) -> None:
        self.client = client
        self.sessions = sessions
        self.agent_id = agent_id
        self.capability = capability

    async def handle(self, session_id: str, raw: str) -> TUIResult:
        try:
            intent = parse_user_input(raw)
            if intent.kind == "prompt":
                return await self._handle_prompt(session_id, intent)
            if intent.kind == "shell":
                return self._record(session_id, "shell", f"captured shell input: {intent.text}")
            return await self._handle_command(session_id, intent)
        except (CommandParseError, ProtocolError, KeyError, ValueError) as exc:
            self.sessions.append(session_id, TranscriptEvent(kind="error", text=str(exc)))
            return TUIResult(render_error(exc))

    async def _handle_prompt(self, session_id: str, intent: InputIntent) -> TUIResult:
        session = self.sessions.resume(session_id)
        self.sessions.append(session_id, TranscriptEvent(kind="user", text=intent.text))
        if not session.active_task_id:
            task = await self.client.create_task(
                principal=session.principal,
                goal=intent.text,
                type="tui",
                constraints=Constraints(autonomy=_autonomy(session.permission_mode)),
            )
            run = await self.client.delegate(
                task.id,
                self.agent_id,
                capability=self.capability,
                input={
                    "goal": intent.text,
                    "mentions": intent.mentions,
                    "permission_mode": session.permission_mode,
                    "model": session.model,
                },
            )
            await self.client.start(task.id)
            self.sessions.set_active(session_id, task_id=task.id, run_id=run.run_id)
            self.sessions.append(session_id, TranscriptEvent(kind="task", text=f"started task {task.id}", ref=task.id))
            return TUIResult(f"started task {task.id} run {run.run_id}")
        task = await self.client.amend(
            session.active_task_id,
            by=session.principal,
            text=intent.text,
            intent="clarify",
        )
        self.sessions.append(session_id, TranscriptEvent(kind="task", text=f"amended task {task.id}", ref=task.id))
        return TUIResult(f"amended task {task.id}")

    async def _handle_command(self, session_id: str, intent: InputIntent) -> TUIResult:
        name = intent.name
        if name == "help":
            return TUIResult(render_help())
        if name == "clear":
            self.sessions.clear_visible(session_id)
            return TUIResult("cleared transcript")
        if name == "new":
            current = self.sessions.resume(session_id)
            created = self.sessions.create(cwd=current.cwd, adapter=current.adapter, principal=current.principal)
            return TUIResult(f"new session {created.id}")
        if name == "fork":
            forked = self.sessions.fork(session_id)
            return TUIResult(f"forked session {forked.id}")
        if name == "archive":
            self.sessions.archive(session_id)
            return TUIResult("archived session", should_exit=True)
        if name == "delete":
            self.sessions.delete(session_id)
            return TUIResult("deleted session", should_exit=True)
        if name == "resume":
            target = _required_arg(intent, "/resume requires a session id")
            resumed = self.sessions.resume(target)
            return TUIResult(render_status(resumed))
        if name == "model":
            value = _required_arg(intent, "/model requires a model name")
            updated = self.sessions.set_preference(session_id, field="model", value=value)
            return TUIResult(f"model={updated.model}")
        if name == "theme":
            value = _required_arg(intent, "/theme requires a theme name")
            updated = self.sessions.set_preference(session_id, field="theme", value=value)
            return TUIResult(f"theme={updated.theme}")
        if name == "vim":
            updated = self.sessions.set_preference(session_id, field="composer_mode", value="vim")
            return TUIResult(f"composer_mode={updated.composer_mode}")
        if name == "compact":
            self.sessions.append(session_id, TranscriptEvent(kind="summary", text=render_transcript(self.sessions.resume(session_id))))
            return TUIResult("compacted transcript summary recorded")
        if name == "mcp":
            return TUIResult("MCP is owned by the selected harness/tool runtime.")
        if name == "statusline":
            return await self._status(session_id)
        if name == "diff":
            return TUIResult(_diff_summary(Path.cwd()))
        return await self._handle_hlp_command(session_id, intent)

    async def _status(self, session_id: str) -> TUIResult:
        session = self.sessions.resume(session_id)
        task_state = "none"
        if session.active_task_id:
            task_state = (await self.client.get_task(session.active_task_id)).state
        inbox = await self.client.human_inbox(session.principal)
        return TUIResult(render_status(session, task_state=task_state, inbox_count=len(inbox)))

    async def _handle_hlp_command(self, session_id: str, intent: InputIntent) -> TUIResult:
        raise ValueError(f"command not wired yet: /{intent.name}")

    def _record(self, session_id: str, kind: str, text: str) -> TUIResult:
        self.sessions.append(session_id, TranscriptEvent(kind=kind, text=text))
        return TUIResult(text)


def _required_arg(intent: InputIntent, message: str) -> str:
    if not intent.args:
        raise ValueError(message)
    return intent.args[0]


def _autonomy(permission_mode: str) -> str:
    return {
        "auto": "autonomous",
        "plan": "plan_then_implement",
        "confirm": "confirm_each_action",
        "read-only": "read_only",
    }.get(permission_mode, "autonomous")


def _diff_summary(cwd: Path) -> str:
    git = cwd / ".git"
    if not git.exists():
        return "diff unavailable: not a git workspace"
    return "diff available through harness or injected provider"
```

Modify `loops/tui/__init__.py` exports:

```python
from __future__ import annotations

from .commands import CommandDefinition, CommandParseError, InputIntent, parse_user_input
from .compat import CompatibilityReport, compatibility_report
from .controller import TUIController, TUIResult
from .render import render_help, render_status, render_transcript
from .session import SessionStore, TUISession, TranscriptEvent

__all__ = [
    "CommandDefinition",
    "CommandParseError",
    "CompatibilityReport",
    "InputIntent",
    "SessionStore",
    "TUIController",
    "TUIResult",
    "TUISession",
    "TranscriptEvent",
    "compatibility_report",
    "parse_user_input",
    "render_help",
    "render_status",
    "render_transcript",
]
```

- [ ] **Step 4: Run controller direct tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_hlp_tui.py::test_submit_prompt_creates_delegates_and_starts_task tests/test_hlp_tui.py::test_submit_prompt_on_active_task_amends_instead_of_new_delegate tests/test_hlp_tui.py::test_direct_session_commands_do_not_mutate_hlp -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add loops/tui/__init__.py loops/tui/controller.py tests/test_hlp_tui.py
git commit -m "feat: wire HLP TUI prompt controller"
```

## Task 4: HLP Inbox, Checkpoint, Review, Audit, and Permissions Commands

**Files:**
- Modify: `loops/tui/controller.py`
- Modify: `loops/tui/render.py`
- Test: `tests/test_hlp_tui.py`

- [ ] **Step 1: Write failing HLP command tests**

Append to `tests/test_hlp_tui.py`:

```python
from loops.hlp import ArtifactPayload, CheckpointOption


def test_inbox_approve_interrupt_and_audit_commands(tmp_path):
    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="fake")
    controller = TUIController(client=client, sessions=store)

    run(controller.handle(session.id, "Review the patch"))
    active = store.resume(session.id)
    checkpoint = run(client.raise_checkpoint(
        task_id=active.active_task_id,
        kind="approval",
        prompt="Apply patch?",
        raised_by="agent_tui",
    ))

    inbox = run(controller.handle(session.id, "/inbox"))
    approved = run(controller.handle(session.id, "/approve"))
    interrupted = run(controller.handle(session.id, "/interrupt inspect before continuing"))
    audit = run(controller.handle(session.id, "/audit"))

    assert checkpoint.id in inbox.output
    assert "approved checkpoint" in approved.output
    assert "interrupted task" in interrupted.output
    assert "task.interrupted" in audit.output


def test_choose_input_review_and_permissions_commands(tmp_path):
    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="fake")
    controller = TUIController(client=client, sessions=store)

    run(controller.handle(session.id, "Review the patch"))
    active = store.resume(session.id)
    choice = run(client.raise_checkpoint(
        task_id=active.active_task_id,
        kind="choice",
        prompt="Pick path",
        options=(CheckpointOption(id="safe", label="Safe path", risk="low"),),
        raised_by="agent_tui",
    ))
    chosen = run(controller.handle(session.id, "/choose safe"))
    input_checkpoint = run(client.raise_checkpoint(
        task_id=active.active_task_id,
        kind="input",
        prompt="Need detail",
        raised_by="agent_tui",
    ))
    provided = run(controller.handle(session.id, "/input use stricter validation"))
    artifact = run(client.commit_artifact(
        task_id=active.active_task_id,
        type="patch",
        payload=ArtifactPayload(kind="inline", uri="mem://patch-v1", checksum="sha256:patch-v1"),
        produced_by="agent_tui",
    ))
    reviewed = run(controller.handle(session.id, "/review approved"))
    permissions = run(controller.handle(session.id, "/permissions read-only"))

    assert choice.id in chosen.output
    assert input_checkpoint.id in provided.output
    assert artifact.id in reviewed.output
    assert "permission_mode=read-only" in permissions.output
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run pytest tests/test_hlp_tui.py::test_inbox_approve_interrupt_and_audit_commands -q
```

Expected: FAIL with `ValueError: command not wired yet: /inbox`.

- [ ] **Step 3: Implement HLP command dispatch**

Modify `loops/tui/controller.py` by replacing `_handle_hlp_command` and adding helper methods:

```python
    async def _handle_hlp_command(self, session_id: str, intent: InputIntent) -> TUIResult:
        if intent.name == "permissions":
            return self._set_permissions(session_id, intent)
        if intent.name == "inbox":
            session = self.sessions.resume(session_id)
            return TUIResult(render_inbox(await self.client.human_inbox(session.principal)))
        if intent.name == "approve":
            return await self._resolve_checkpoint(session_id, action="approve")
        if intent.name == "reject":
            return await self._resolve_checkpoint(session_id, action="reject")
        if intent.name == "choose":
            return await self._resolve_checkpoint(session_id, action="choose", choice=_required_arg(intent, "/choose requires an option id"))
        if intent.name == "input":
            text = " ".join(intent.args).strip()
            if not text:
                raise ValueError("/input requires text")
            return await self._resolve_checkpoint(session_id, action="provide", input_text=text)
        if intent.name == "amend":
            text = " ".join(intent.args).strip()
            if not text:
                raise ValueError("/amend requires text")
            session = self._require_active(session_id)
            task = await self.client.amend(session.active_task_id, by=session.principal, text=text)
            return TUIResult(f"amended task {task.id}")
        if intent.name == "interrupt":
            prompt = " ".join(intent.args).strip()
            if not prompt:
                raise ValueError("/interrupt requires a prompt")
            session = self._require_active(session_id)
            checkpoint = await self.client.interrupt(session.active_task_id, by=session.principal, prompt=prompt)
            return TUIResult(f"interrupted task {session.active_task_id} checkpoint {checkpoint.id}")
        if intent.name == "review":
            verdict = _required_arg(intent, "/review requires approved, changes, or rejected")
            return await self._review_current(session_id, verdict)
        if intent.name == "audit":
            session = self._require_active(session_id)
            return TUIResult(render_audit(await self.client.replay_audit(session.active_task_id)))
        raise ValueError(f"command not wired: /{intent.name}")

    def _set_permissions(self, session_id: str, intent: InputIntent) -> TUIResult:
        value = _required_arg(intent, "/permissions requires auto, plan, confirm, or read-only")
        if value not in {"auto", "plan", "confirm", "read-only"}:
            raise ValueError(f"unsupported permission mode: {value}")
        updated = self.sessions.set_preference(session_id, field="permission_mode", value=value)
        return TUIResult(f"permission_mode={updated.permission_mode}")

    async def _resolve_checkpoint(
        self,
        session_id: str,
        *,
        action: str,
        choice: str | None = None,
        input_text: str | None = None,
    ) -> TUIResult:
        session = self.sessions.resume(session_id)
        inbox = await self.client.human_inbox(session.principal)
        checkpoint = next((item for item in inbox if item.kind == "checkpoint"), None)
        if checkpoint is None:
            raise ValueError("no pending checkpoint")
        resolved = await self.client.resolve_checkpoint(
            checkpoint.subject_id,
            by=session.principal,
            action=action,
            choice=choice,
            input=input_text,
        )
        return TUIResult(f"{action}d checkpoint {resolved.id}")

    async def _review_current(self, session_id: str, verdict_arg: str) -> TUIResult:
        verdicts = {
            "approved": "approved",
            "approve": "approved",
            "changes": "changes_requested",
            "changes_requested": "changes_requested",
            "rejected": "rejected",
            "reject": "rejected",
        }
        if verdict_arg not in verdicts:
            raise ValueError(f"unsupported review verdict: {verdict_arg}")
        session = self.sessions.resume(session_id)
        inbox = await self.client.human_inbox(session.principal)
        review_item = next((item for item in inbox if item.kind == "review"), None)
        if review_item is None:
            raise ValueError("no review-ready artifact")
        review = await self.client.submit_review(
            task_id=review_item.task_id,
            artifact_id=review_item.subject_id,
            reviewer=session.principal,
            verdict=verdicts[verdict_arg],
        )
        return TUIResult(f"reviewed artifact {review.artifact_id} verdict={review.verdict}")

    def _require_active(self, session_id: str):
        session = self.sessions.resume(session_id)
        if not session.active_task_id:
            raise ValueError("no active task")
        return session
```

- [ ] **Step 4: Fix approval wording if needed**

If `approve` renders `approved checkpoint`, keep it. If it renders `approved checkpoint` through `f"{action}d"`, no change is needed for approve. If `reject` renders `rejectd`, replace the return line with:

```python
        label = "approved" if action == "approve" else "rejected" if action == "reject" else "resolved"
        return TUIResult(f"{label} checkpoint {resolved.id}")
```

- [ ] **Step 5: Run HLP command tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_hlp_tui.py::test_inbox_approve_interrupt_and_audit_commands tests/test_hlp_tui.py::test_choose_input_review_and_permissions_commands -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add loops/tui/controller.py loops/tui/render.py tests/test_hlp_tui.py
git commit -m "feat: map HLP TUI commands to protocol operations"
```

## Task 5: CLI App, Console Script, and Offline Demo

**Files:**
- Create: `loops/tui/app.py`
- Create: `examples/hlp_tui_demo.py`
- Modify: `pyproject.toml`
- Modify: `loops/tui/__init__.py`
- Test: `tests/test_hlp_tui.py`

- [ ] **Step 1: Write failing app and demo tests**

Append to `tests/test_hlp_tui.py`:

```python
from examples.hlp_tui_demo import run_demo as run_tui_demo
from loops.tui.app import run_lines


def test_run_lines_executes_line_oriented_tui(tmp_path):
    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)
    outputs = run(run_lines(
        lines=("Review the patch", "/statusline", "/model gpt-5", "!git status"),
        client=client,
        session_path=tmp_path / "sessions.json",
        cwd="/repo",
        adapter_name="fake",
    ))

    joined = "\n".join(outputs)
    assert "started task" in joined
    assert "state=in_progress" in joined
    assert "model=gpt-5" in joined
    assert "captured shell input: git status" in joined


def test_hlp_tui_demo_runs_full_offline_human_loop():
    result = run(run_tui_demo())

    assert result["final_task_state"] == "completed"
    assert result["checkpoint_decision"] == "approve"
    assert result["review_verdict"] == "approved"
    assert "task.checkpoint.raised" in result["audit_actions"]
    assert "review.submitted" in result["audit_actions"]
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run pytest tests/test_hlp_tui.py::test_run_lines_executes_line_oriented_tui -q
```

Expected: FAIL with import error for `loops.tui.app`.

- [ ] **Step 3: Implement line-oriented app shell**

Create `loops/tui/app.py`:

```python
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Iterable

from loops.hlp import CodexCLIAdapter, FakeAgentAdapter, HLPClient

from .controller import TUIController
from .session import SessionStore


async def run_lines(
    *,
    lines: Iterable[str],
    client: HLPClient,
    session_path: str | Path,
    cwd: str,
    adapter_name: str,
    principal: str = "user_local",
) -> list[str]:
    sessions = SessionStore(session_path)
    session = sessions.create(cwd=cwd, adapter=adapter_name, principal=principal)
    controller = TUIController(client=client, sessions=sessions)
    outputs: list[str] = []
    for line in lines:
        result = await controller.handle(session.id, line)
        outputs.append(result.output)
        if result.should_exit:
            break
    return outputs


def build_client(adapter_name: str) -> HLPClient:
    if adapter_name == "fake":
        return HLPClient(adapter=FakeAgentAdapter())
    if adapter_name == "codex":
        return HLPClient(adapter=CodexCLIAdapter())
    raise ValueError(f"unsupported adapter: {adapter_name}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the HLP TUI channel.")
    parser.add_argument("--adapter", default="codex", choices=("codex", "fake"))
    parser.add_argument("--session-path", default=str(Path(".hlp-tui-sessions.json")))
    parser.add_argument("--principal", default="user_local")
    args = parser.parse_args(argv)

    client = build_client(args.adapter)
    sessions = SessionStore(args.session_path)
    session = sessions.create(cwd=str(Path.cwd()), adapter=args.adapter, principal=args.principal)
    controller = TUIController(client=client, sessions=sessions)
    print(f"HLP TUI session {session.id}. Type /help for commands.")
    try:
        while True:
            line = input("> ")
            result = asyncio.run(controller.handle(session.id, line))
            print(result.output)
            if result.should_exit:
                return
    except (EOFError, KeyboardInterrupt):
        print()
        return


if __name__ == "__main__":
    main(sys.argv[1:])
```

Modify `loops/tui/__init__.py` exports:

```python
from __future__ import annotations

from .app import run_lines
from .commands import CommandDefinition, CommandParseError, InputIntent, parse_user_input
from .compat import CompatibilityReport, compatibility_report
from .controller import TUIController, TUIResult
from .render import render_help, render_status, render_transcript
from .session import SessionStore, TUISession, TranscriptEvent

__all__ = [
    "CommandDefinition",
    "CommandParseError",
    "CompatibilityReport",
    "InputIntent",
    "SessionStore",
    "TUIController",
    "TUIResult",
    "TUISession",
    "TranscriptEvent",
    "compatibility_report",
    "parse_user_input",
    "render_help",
    "render_status",
    "render_transcript",
    "run_lines",
]
```

- [ ] **Step 4: Add console script**

Modify `[project.scripts]` in `pyproject.toml`:

```toml
[project.scripts]
loops-hlp-demo = "examples.hlp_e2e_demo:main"
loops-hlp-adapters-demo = "examples.hlp_adapter_compat_demo:main"
loops-hlp-codex-harness-demo = "examples.hlp_codex_harness_demo:main"
loops-hlp-harness-demo = "examples.hlp_harness_wrap_demo:main"
loops-hlp-local-cli-demo = "examples.hlp_local_cli_e2e:main"
loops-hlp-tui = "loops.tui.app:main"
```

- [ ] **Step 5: Implement offline demo**

Create `examples/hlp_tui_demo.py`:

```python
from __future__ import annotations

import asyncio
import json
from typing import Any

from loops.hlp import ArtifactPayload, FakeAgentAdapter, HLPClient
from loops.tui.controller import TUIController
from loops.tui.session import SessionStore


async def run_demo() -> dict[str, Any]:
    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)
    sessions = SessionStore("/private/tmp/hlp-tui-demo-sessions.json")
    session = sessions.create(cwd="/demo", adapter="fake", principal="user_local")
    controller = TUIController(client=client, sessions=sessions)

    await controller.handle(session.id, "Review a generated patch")
    active = sessions.resume(session.id)
    checkpoint = await client.raise_checkpoint(
        task_id=active.active_task_id,
        kind="approval",
        prompt="Apply patch?",
        raised_by="agent_tui",
    )
    await controller.handle(session.id, "/approve")
    artifact = await client.commit_artifact(
        task_id=active.active_task_id,
        type="patch",
        payload=ArtifactPayload(kind="inline", uri="mem://hlp-tui-demo.patch", checksum="sha256:hlp-tui-demo"),
        produced_by="agent_tui",
    )
    review_result = await controller.handle(session.id, "/review approved")
    final_task = await client.get_task(active.active_task_id)
    audit = await client.replay_audit(active.active_task_id)

    return {
        "session_id": session.id,
        "task_id": active.active_task_id,
        "run_id": active.active_run_id,
        "checkpoint_id": checkpoint.id,
        "checkpoint_decision": checkpoint.resolution.action if checkpoint.resolution else "approve",
        "artifact_id": artifact.id,
        "review_verdict": "approved" if "verdict=approved" in review_result.output else "",
        "final_task_state": final_task.state,
        "adapter_operations": [name for name, _payload in adapter.calls],
        "audit_actions": [event.action for event in audit],
    }


def main() -> None:
    print(json.dumps(asyncio.run(run_demo()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run app/demo tests to verify GREEN**

Run:

```bash
uv run pytest tests/test_hlp_tui.py::test_run_lines_executes_line_oriented_tui tests/test_hlp_tui.py::test_hlp_tui_demo_runs_full_offline_human_loop -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```bash
git add loops/tui/__init__.py loops/tui/app.py examples/hlp_tui_demo.py pyproject.toml tests/test_hlp_tui.py
git commit -m "feat: add HLP TUI app and offline demo"
```

## Task 6: Final Verification, Documentation Status, and Integration Commit

**Files:**
- Modify: `docs/plans/2026-07-07-hlp-tui.md`
- Modify: `README.md`
- Test: full relevant suite

- [ ] **Step 1: Write failing metadata/documentation tests by inspection**

No new automated test is required for README text. The verification gate for this task is:

```bash
rg -n "loops-hlp-tui|HLP TUI" README.md docs/plans/2026-07-07-hlp-tui.md
```

Expected before implementation: command does not find `loops-hlp-tui` in `README.md`.

- [ ] **Step 2: Update README quick start**

Add this section after the existing local CLI lifecycle quick start in `README.md`:

````markdown
Run the line-oriented HLP TUI channel:

```bash
uv run loops-hlp-tui --adapter codex
```

The TUI is a host/channel over HLP. It renders prompt input, slash commands,
human inbox approvals, artifact review, audit replay, and session transcript
state while keeping model calls, tool execution, sandboxing, and the agent loop
inside the selected harness adapter.
```
````

- [ ] **Step 3: Update plan status**

In `docs/plans/2026-07-07-hlp-tui.md`, change:

```markdown
| **状态** | 设计已批准，待实现计划 |
```

to:

```markdown
| **状态** | 首版 line-oriented TUI 已实现，待 fullscreen backend 评估 |
```

- [ ] **Step 4: Run targeted TUI tests**

Run:

```bash
uv run pytest tests/test_hlp_tui.py -q
```

Expected: PASS.

- [ ] **Step 5: Run existing HLP regression tests**

Run:

```bash
uv run pytest tests/test_hlp_sdk.py -q
uv run pytest tests/test_hlp_protocol.py -q
```

Expected: PASS for both commands.

- [ ] **Step 6: Run compile and metadata checks**

Run:

```bash
uv run python -m compileall loops tests examples
uv run python scripts/check_release_metadata.py
git diff --check
```

Expected: compileall completes, release metadata check exits 0, and `git diff --check` has no output.

- [ ] **Step 7: Run offline demo command**

Run:

```bash
uv run python -m examples.hlp_tui_demo
```

Expected: JSON output includes:

```json
{
  "final_task_state": "completed",
  "review_verdict": "approved"
}
```

- [ ] **Step 8: Commit Task 6**

```bash
git add README.md docs/plans/2026-07-07-hlp-tui.md
git commit -m "docs: document HLP TUI quickstart"
```

## Self-Review Checklist

- Spec coverage:
  - `loops/tui` package: Tasks 1-5.
  - `loops-hlp-tui` command: Task 5.
  - prompt composer, `@file`, `!shell`: Tasks 1, 3, 5.
  - transcript/session lifecycle: Task 2 and direct commands in Task 3.
  - status line/help/rendering: Tasks 2 and 3.
  - slash commands: Tasks 1, 3, 4.
  - permissions mapping: Task 4.
  - inbox approval/checkpoint/review/audit: Task 4 and demo in Task 5.
  - HLP architecture boundary: Tasks 3-5 use `HLPClient`; no `loops.hlp` import of `loops.tui`.
  - offline tests and demo: Tasks 5-6.
- Red-flag scan:
  - No incomplete markers, vague implementation instructions, or unspecified code steps remain.
- Type consistency:
  - `InputIntent`, `SessionStore`, `TUIController`, `TUIResult`, `TranscriptEvent`, and renderer names are consistent across tasks.
  - `TUIController.handle(session_id, raw)` is the controller entry point used by tests, app, and demo.
  - Session fields `active_task_id`, `active_run_id`, and `permission_mode` are consistent across session, render, and controller.

## Execution Handoff

Plan complete and saved to `docs/plans/2026-07-07-hlp-tui-implementation.md`. Two execution options:

1. Subagent-Driven (recommended) - dispatch a fresh subagent per task, review between tasks, fast iteration.

2. Inline Execution - execute tasks in this session using executing-plans, batch execution with checkpoints.

Choose one before implementation starts.
