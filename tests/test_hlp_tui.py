from __future__ import annotations

from loops.tui.commands import (
    CommandParseError,
    InputIntent,
    parse_user_input,
)
from loops.tui.render import render_help, render_status, render_transcript
from loops.tui.compat import compatibility_report
from loops.tui.session import SessionStore, TranscriptEvent
import pytest


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

    assert "/help" in help_text
    assert "adapter=fake" in status
    assert "state=in_progress" in status
    assert "inbox=2" in status
    assert "user: inspect" in transcript
