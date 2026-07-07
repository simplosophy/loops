from __future__ import annotations

from loops.tui.commands import (
    CommandParseError,
    InputIntent,
    parse_user_input,
)
from loops.tui.compat import compatibility_report
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
