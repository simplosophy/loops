from __future__ import annotations
import json
import asyncio

from loops.tui import session as session_module
from loops.tui.commands import (
    CommandParseError,
    InputIntent,
    parse_user_input,
)
from loops.hlp import FakeAgentAdapter, HLPClient
from loops.tui.render import render_help, render_status, render_transcript
from loops.tui.compat import compatibility_report
from loops.tui.session import SessionStore, TranscriptEvent
from loops.tui.controller import TUIController
import pytest


def run(coro):
    return asyncio.run(coro)


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


def test_parse_indented_prompt_is_preserved():
    prompt = parse_user_input("  indented prompt")

    assert prompt.kind == "prompt"
    assert prompt.raw == "  indented prompt"
    assert prompt.text == "  indented prompt"


def test_unknown_slash_command_fails_without_mutation():
    try:
        parse_user_input("/unknown")
    except CommandParseError as exc:
        assert "unknown command: /unknown" in str(exc)
    else:
        raise AssertionError("unknown command should fail")


def test_parse_command_with_leading_whitespace():
    intent = parse_user_input("  /help")

    assert intent == InputIntent(
        kind="command",
        name="help",
        args=(),
        raw="/help",
        mentions=(),
    )


def test_blank_input_rejected():
    with pytest.raises(CommandParseError, match="blank"):
        parse_user_input("   ")


def test_shell_only_input_rejected():
    with pytest.raises(CommandParseError, match="shell input is empty"):
        parse_user_input("!")


def test_shell_only_whitespace_rejected():
    with pytest.raises(CommandParseError, match="shell input is empty"):
        parse_user_input("!   ")


def test_compatibility_report_meets_first_version_threshold():
    report = compatibility_report()

    assert report.total >= 20
    assert report.covered >= 18
    assert report.coverage >= 0.90
    assert report.coverage < 1.0
    assert "/login" in report.commands
    assert "/doctor" in report.commands
    assert "/help" in report.commands
    assert "/permissions" in report.commands
    assert "/audit" in report.commands


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

    lines = help_text.splitlines()
    assert lines[0] == "HLP TUI commands:"
    command_lines = lines[1:]
    assert command_lines == sorted(command_lines)
    assert "/amend        hlp    Append HLP steering amendment." in command_lines
    assert "/audit        hlp    Replay HLP audit." in command_lines
    assert "/help         direct Show command help." in command_lines
    assert (
        status
        == "session="
        + session.id
        + " adapter=fake task=none state=in_progress mode=auto inbox=2 cwd=/repo"
    )
    assert transcript == "user: inspect"


def test_session_store_save_is_atomic_on_temp_write_failure(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="fake")
    original = (tmp_path / "sessions.json").read_text()
    path = tmp_path / "sessions.json"
    original_named_tempfile = session_module.tempfile.NamedTemporaryFile

    def fail_on_temp_write(*args, **kwargs):
        tmp = original_named_tempfile(*args, **kwargs)

        def fail_write(*_args, **_kwargs):
            raise OSError("temporary write failure")

        tmp.write = fail_write
        return tmp

    monkeypatch.setattr(session_module.tempfile, "NamedTemporaryFile", fail_on_temp_write)

    with pytest.raises(OSError):
        store.append(session.id, TranscriptEvent(kind="user", text="should not persist"))

    assert (tmp_path / "sessions.json").exists()
    assert (tmp_path / "sessions.json").read_text() == original
    data = json.loads(path.read_text())
    assert len(data) == 1
    assert data[0]["id"] == session.id
    assert not (tmp_path / ".sessions.json.tmp").exists()
    assert list(tmp_path.glob(".sessions.json.*.tmp")) == []


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
