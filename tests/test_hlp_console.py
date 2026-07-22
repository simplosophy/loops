"""Console layer tests: completion, color roles, status snapshot."""

from __future__ import annotations

import asyncio

import pytest

from loops.hlp import FakeAgentAdapter, HLPClient
from loops.tui.app import _status_snapshot
from loops.tui.console import Console, adapter_completions, completion_candidates
from loops.tui.controller import TUIController
from loops.tui.session import SessionStore


def run(coro):
    return asyncio.run(coro)


def _console(**kwargs) -> Console:
    kwargs.setdefault("color", False)
    return Console(**kwargs)


def test_completer_matches_slash_commands():
    assert completion_candidates("/prog") == ["/progress"]
    first = completion_candidates("/sof")[0]
    assert first in {"/soft", "/softs"}


def test_completer_matches_adapter_names_after_adapter_command():
    candidates = completion_candidates(
        "/adapter p",
        completer_extra=lambda command: adapter_completions() if command == "adapter" else [],
    )
    assert candidates == ["pi"]


def test_completer_ignores_plain_text():
    assert completion_candidates("hello") == []


def test_color_disabled_by_no_color_env(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    console = _console(color=True)
    assert console.color is False
    assert console.style("text", "agent") == "text"


def test_color_role_wraps_codes_when_enabled():
    console = _console(color=True)
    console.color = True  # force: pytest capture is not a TTY
    assert console.style("text", "agent") == "\033[36mtext\033[0m"
    assert console.style("text", "error") == "\033[31mtext\033[0m"


def test_status_snapshot_shape(tmp_path):
    client = HLPClient(adapter=FakeAgentAdapter())
    store = SessionStore(tmp_path / "sessions.json")
    controller = TUIController(client=client, sessions=store)
    session = store.create(cwd="/repo", adapter="fake", principal="user_local")
    run(controller.handle(session.id, "do work"))

    line = run(_status_snapshot(controller, session.id))
    assert line.startswith("session=")
    assert "adapter=fake" in line
    assert "state=in_progress" in line
    assert "inbox=0" in line


def test_unknown_command_gets_did_you_mean_suggestion():
    from loops.tui.commands import CommandParseError, parse_user_input

    with pytest.raises(CommandParseError, match="did you mean /progress"):
        parse_user_input("/progres")
    with pytest.raises(CommandParseError, match="unknown command"):
        parse_user_input("/zzz-unknown")


def test_render_error_includes_actionable_hints():
    from loops.hlp import AgentAdapterError, ProtocolError
    from loops.tui.render import render_error

    text = render_error(AgentAdapterError("codex", "delegate", "process command failed"))
    assert "/adapter" in text
    assert "hint:" in text

    text = render_error(ProtocolError("NOT_FOUND", "task not found"))
    assert "/tasks" in text

    text = render_error(ProtocolError("PRECONDITION_FAILED", "illegal transition"))
    assert "/statusline" in text


def test_console_input_backslash_continues_onto_next_line(monkeypatch):
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO("first \\\nsecond\n"))
    assert _console().input() == "first \nsecond"

    # EOF mid-continuation returns what was buffered.
    monkeypatch.setattr(sys, "stdin", io.StringIO("only \\\n"))
    assert _console().input() == "only "
