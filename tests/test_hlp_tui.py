from __future__ import annotations

import asyncio
import json
import sys

import pytest

from loops.hlp import (
    AgentAdapterError,
    ArtifactPayload,
    CheckpointOption,
    ClaudeCodeHarnessAdapter,
    CodexHarnessAdapter,
    FakeAgentAdapter,
    HLPClient,
    KimiHarnessAdapter,
    PiHarnessAdapter,
    ProcessResult,
)
from loops.tui import session as session_module
from loops.tui.commands import (
    CommandParseError,
    InputIntent,
    parse_user_input,
)
from loops.tui.compat import compatibility_report
from loops.tui.controller import TUIController
from loops.tui.render import render_help, render_status, render_transcript
from loops.tui.session import SessionStore, TranscriptEvent


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
    for title in (
        "Session:",
        "Tasks & artifacts:",
        "Human-loop decisions:",
        "Continuous control:",
        "Other:",
    ):
        assert title in lines
    assert "/handoff" in help_text
    assert "/tasks" in help_text
    assert "/amend        Append HLP steering amendment." in help_text
    assert "/audit        Replay HLP audit." in help_text
    assert "/help         Show command help." in help_text
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


def test_slash_amend_updates_active_task(tmp_path):
    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="fake")
    controller = TUIController(client=client, sessions=store)

    run(controller.handle(session.id, "Review the patch"))
    result = run(controller.handle(session.id, "/amend Focus on auth boundaries"))
    updated = store.resume(session.id)
    task = run(client.get_task(updated.active_task_id))

    assert result.output == f"amended task {task.id}"
    assert task.steering_log[-1].text == "Focus on auth boundaries"
    assert task.steering_log[-1].intent == "clarify"
    assert [name for name, _payload in adapter.calls] == ["delegate", "steer"]


def test_slash_amend_requires_text_without_mutating_hlp(tmp_path):
    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="fake")
    controller = TUIController(client=client, sessions=store)

    run(controller.handle(session.id, "Review the patch"))
    active = store.resume(session.id)
    before = run(client.get_task(active.active_task_id))
    result = run(controller.handle(session.id, "/amend"))
    after = run(client.get_task(active.active_task_id))

    assert "error:" in result.output
    assert "/amend requires text" in result.output
    assert after.steering_log == before.steering_log
    assert [name for name, _payload in adapter.calls] == ["delegate"]


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


def test_handle_unknown_session_returns_error_result(tmp_path):
    client = HLPClient(adapter=FakeAgentAdapter())
    store = SessionStore(tmp_path / "sessions.json")
    controller = TUIController(client=client, sessions=store)

    result = run(controller.handle("missing", "Review the patch"))

    assert "error:" in result.output
    assert "unknown session: missing" in result.output
    assert result.should_exit is False


def test_handle_unexpected_runtime_error_is_not_swallowed(tmp_path, monkeypatch):
    client = HLPClient(adapter=FakeAgentAdapter())
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="fake")
    controller = TUIController(client=client, sessions=store)

    async def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(controller, "_handle_prompt", boom)

    with pytest.raises(RuntimeError, match="boom"):
        run(controller.handle(session.id, "Review the patch"))


def test_adapter_failure_is_rendered_without_crashing_tui(tmp_path):
    class FailingDelegateAdapter(FakeAgentAdapter):
        async def delegate(self, *args, **kwargs):
            raise AgentAdapterError(
                "failing-adapter",
                "delegate",
                "process command failed",
                details={"exit_code": 1},
            )

    client = HLPClient(adapter=FailingDelegateAdapter())
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="fake")
    controller = TUIController(client=client, sessions=store)

    result = run(controller.handle(session.id, "Review the patch"))

    assert result.should_exit is False
    assert "error: AgentAdapterError: failing-adapter.delegate" in result.output
    assert "process command failed" in result.output


def test_direct_commands_do_not_call_hlp(tmp_path):
    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="fake")
    controller = TUIController(client=client, sessions=store)

    theme_result = run(controller.handle(session.id, "/theme dark"))
    vim_result = run(controller.handle(session.id, "/vim"))
    mcp_result = run(controller.handle(session.id, "/mcp"))
    compact_result = run(controller.handle(session.id, "/compact"))
    status_result = run(controller.handle(session.id, "/statusline"))

    assert "theme=dark" in theme_result.output
    assert "composer_mode=vim" in vim_result.output
    assert "MCP is owned" in mcp_result.output
    assert "compacted transcript summary recorded" in compact_result.output
    assert "session=" in status_result.output
    assert "inbox=" in status_result.output
    assert adapter.calls == []


def test_diff_command_renders_git_diff_stat(tmp_path, monkeypatch):
    import subprocess

    client = HLPClient(adapter=FakeAgentAdapter())
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd=str(tmp_path), adapter="fake")
    controller = TUIController(client=client, sessions=store)
    (tmp_path / ".git").mkdir()
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=" README.md | 2 ++\n 1 file changed, 2 insertions(+)\n",
            stderr="",
        )

    monkeypatch.setattr("loops.tui.controller.subprocess.run", fake_run)

    result = run(controller.handle(session.id, "/diff"))

    assert "README.md | 2 ++" in result.output
    assert "1 file changed" in result.output
    assert calls[0][0] == ("git", "-C", str(tmp_path), "diff", "--stat")


def test_diff_command_lets_git_discover_repository_from_subdirectory(tmp_path, monkeypatch):
    import subprocess

    subdir = tmp_path / "src"
    subdir.mkdir()
    client = HLPClient(adapter=FakeAgentAdapter())
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd=str(subdir), adapter="fake")
    controller = TUIController(client=client, sessions=store)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("loops.tui.controller.subprocess.run", fake_run)

    result = run(controller.handle(session.id, "/diff"))

    assert result.output == "diff is empty"
    assert calls[0][0] == ("git", "-C", str(subdir), "diff", "--stat")


def test_resume_unknown_session_returns_error_result(tmp_path):
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="fake")
    controller = TUIController(client=HLPClient(adapter=FakeAgentAdapter()), sessions=store)

    result = run(controller.handle(session.id, "/resume missing"))

    assert "error:" in result.output
    assert "unknown session: missing" in result.output


def _started_hlp_tui(tmp_path, name="sessions.json"):
    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / name)
    session = store.create(cwd="/repo", adapter="fake")
    controller = TUIController(client=client, sessions=store)

    run(controller.handle(session.id, "Review the patch"))

    return adapter, client, store, session, controller


def _start_hlp_tui_session(store, controller):
    session = store.create(cwd="/repo", adapter="fake")
    run(controller.handle(session.id, "Review the patch"))
    return session, store.resume(session.id)


def test_hlp_inbox_approve_interrupt_and_audit_commands(tmp_path):
    _adapter, client, store, session, controller = _started_hlp_tui(tmp_path)
    active = store.resume(session.id)
    checkpoint = run(
        client.raise_checkpoint(
            task_id=active.active_task_id,
            kind="approval",
            prompt="Apply patch?",
            raised_by="agent_tui",
        )
    )

    inbox = run(controller.handle(session.id, "/inbox"))
    approved = run(controller.handle(session.id, "/approve proceed with patch"))
    interrupted = run(controller.handle(session.id, "/interrupt inspect before continuing"))
    audit = run(controller.handle(session.id, "/audit"))
    resolved = client.store.get_checkpoint(checkpoint.id)

    assert checkpoint.id in inbox.output
    assert "approved checkpoint" in approved.output
    assert resolved.resolution is not None
    assert resolved.resolution.comment == "proceed with patch"
    assert "interrupted task" in interrupted.output
    assert "task.checkpoint.resolved" in audit.output
    assert "task.interrupted" in audit.output


@pytest.mark.parametrize(
    ("kind", "options", "command", "expected_action", "field", "expected_value"),
    (
        ("approval", (), "/approve target ok", "approve", "comment", "target ok"),
        ("approval", (), "/reject unsafe target", "reject", "comment", "unsafe target"),
        (
            "choice",
            (CheckpointOption(id="target", label="Target path", risk="low"),),
            "/choose target",
            "choose",
            "choice",
            "target",
        ),
        ("input", (), "/input target detail", "provide", "input", "target detail"),
    ),
)
def test_hlp_checkpoint_commands_scope_to_current_active_task(
    tmp_path,
    kind,
    options,
    command,
    expected_action,
    field,
    expected_value,
):
    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    controller = TUIController(client=client, sessions=store)
    _older_session, older_active = _start_hlp_tui_session(store, controller)
    target_session, target_active = _start_hlp_tui_session(store, controller)
    older = run(
        client.raise_checkpoint(
            task_id=older_active.active_task_id,
            kind=kind,
            prompt="Older checkpoint",
            options=options,
            raised_by="agent_tui",
        )
    )
    target = run(
        client.raise_checkpoint(
            task_id=target_active.active_task_id,
            kind=kind,
            prompt="Target checkpoint",
            options=options,
            raised_by="agent_tui",
        )
    )

    result = run(controller.handle(target_session.id, command))
    older_after = client.store.get_checkpoint(older.id)
    target_after = client.store.get_checkpoint(target.id)

    assert target.id in result.output
    assert older.id not in result.output
    assert older_after.state == "pending"
    assert target_after.state == "resolved"
    assert target_after.resolution is not None
    assert target_after.resolution.action == expected_action
    assert getattr(target_after.resolution, field) == expected_value


def test_hlp_reject_current_checkpoint_with_reason(tmp_path):
    _adapter, client, store, session, controller = _started_hlp_tui(tmp_path)
    active = store.resume(session.id)
    checkpoint = run(
        client.raise_checkpoint(
            task_id=active.active_task_id,
            kind="approval",
            prompt="Apply patch?",
            raised_by="agent_tui",
        )
    )

    rejected = run(controller.handle(session.id, "/reject unsafe state"))
    resolved = client.store.get_checkpoint(checkpoint.id)

    assert "rejected checkpoint" in rejected.output
    assert resolved.resolution is not None
    assert resolved.resolution.action == "reject"
    assert resolved.resolution.comment == "unsafe state"


def test_hlp_choose_and_input_resolve_current_checkpoint(tmp_path):
    _adapter, client, store, session, controller = _started_hlp_tui(tmp_path)
    active = store.resume(session.id)
    choice = run(
        client.raise_checkpoint(
            task_id=active.active_task_id,
            kind="choice",
            prompt="Pick path",
            options=(CheckpointOption(id="safe", label="Safe path", risk="low"),),
            raised_by="agent_tui",
        )
    )

    chosen = run(controller.handle(session.id, "/choose safe"))
    input_checkpoint = run(
        client.raise_checkpoint(
            task_id=active.active_task_id,
            kind="input",
            prompt="Need detail",
            raised_by="agent_tui",
        )
    )
    provided = run(controller.handle(session.id, "/input use stricter validation"))

    resolved_choice = client.store.get_checkpoint(choice.id)
    resolved_input = client.store.get_checkpoint(input_checkpoint.id)

    assert choice.id in chosen.output
    assert resolved_choice.resolution is not None
    assert resolved_choice.resolution.choice == "safe"
    assert input_checkpoint.id in provided.output
    assert resolved_input.resolution is not None
    assert resolved_input.resolution.input == "use stricter validation"


def test_hlp_review_commands_submit_protocol_reviews(tmp_path):
    cases = (
        (
            "approved",
            "/review approved looks good",
            "approved",
            (),
            "looks good",
        ),
        (
            "approve",
            "/review approve good alias",
            "approved",
            (),
            "good alias",
        ),
        (
            "changes-alias",
            "/review changes fix API contract",
            "changes_requested",
            ("fix API contract",),
            "fix API contract",
        ),
        (
            "changes-requested",
            "/review changes_requested tighten validation",
            "changes_requested",
            ("tighten validation",),
            "tighten validation",
        ),
        (
            "rejected",
            "/review rejected unacceptable output",
            "rejected",
            (),
            "unacceptable output",
        ),
        (
            "reject",
            "/review reject unsafe output",
            "rejected",
            (),
            "unsafe output",
        ),
    )

    for name, command, verdict, requested_changes, comment in cases:
        _adapter, client, store, session, controller = _started_hlp_tui(
            tmp_path,
            f"{name}.json",
        )
        active = store.resume(session.id)
        artifact = run(
            client.commit_artifact(
                task_id=active.active_task_id,
                type="patch",
                payload=ArtifactPayload(
                    kind="inline",
                    uri=f"mem://{name}-patch",
                    checksum=f"sha256:{name}-patch",
                ),
                produced_by="agent_tui",
            )
        )

        reviewed = run(controller.handle(session.id, command))
        review = client.store.reviews_of_artifact(artifact.id)[0]

        assert artifact.id in reviewed.output
        assert f"verdict={verdict}" in reviewed.output
        assert review.verdict == verdict
        assert review.requested_changes == requested_changes
        assert review.comments[0].body == comment


def test_hlp_review_scopes_to_current_active_task(tmp_path):
    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    controller = TUIController(client=client, sessions=store)
    _older_session, older_active = _start_hlp_tui_session(store, controller)
    target_session, target_active = _start_hlp_tui_session(store, controller)
    older_artifact = run(
        client.commit_artifact(
            task_id=older_active.active_task_id,
            type="patch",
            payload=ArtifactPayload(
                kind="inline",
                uri="mem://older-patch",
                checksum="sha256:older-patch",
            ),
            produced_by="agent_tui",
        )
    )
    target_artifact = run(
        client.commit_artifact(
            task_id=target_active.active_task_id,
            type="patch",
            payload=ArtifactPayload(
                kind="inline",
                uri="mem://target-patch",
                checksum="sha256:target-patch",
            ),
            produced_by="agent_tui",
        )
    )

    result = run(controller.handle(target_session.id, "/review approved target ok"))

    assert target_artifact.id in result.output
    assert older_artifact.id not in result.output
    assert client.store.reviews_of_artifact(older_artifact.id) == []
    target_reviews = client.store.reviews_of_artifact(target_artifact.id)
    assert len(target_reviews) == 1
    assert target_reviews[0].verdict == "approved"


def test_hlp_review_commented_is_unsupported_and_does_not_create_review(tmp_path):
    _adapter, client, store, session, controller = _started_hlp_tui(tmp_path)
    active = store.resume(session.id)
    artifact = run(
        client.commit_artifact(
            task_id=active.active_task_id,
            type="patch",
            payload=ArtifactPayload(
                kind="inline",
                uri="mem://commented-patch",
                checksum="sha256:commented-patch",
            ),
            produced_by="agent_tui",
        )
    )

    result = run(controller.handle(session.id, "/review commented FYI only"))

    assert "error:" in result.output
    assert "unsupported review verdict: commented" in result.output
    assert client.store.reviews_of_artifact(artifact.id) == []


def test_tui_promote_soft_control_amends_with_provenance(tmp_path):
    adapter, client, store, session, controller = _started_hlp_tui(tmp_path)
    # Need in_progress for amend.
    run(controller.handle(session.id, "start work"))
    active = store.resume(session.id)
    assert active.active_task_id

    result = run(controller.handle(session.id, "/promote focus on auth boundaries"))
    assert "promoted 1 soft → amended task" in result.output
    assert "HLP-realtime" in result.output or "profile=HLP-realtime" in result.output

    task = run(client.get_task(active.active_task_id))
    assert task.state == "in_progress"
    assert any("focus on auth boundaries" in item.text for item in task.steering_log)
    events = run(client.replay_audit(task.id))
    amended = [e for e in events if e.action == "task.amended"]
    assert amended
    after = amended[-1].after
    assert isinstance(after, dict)
    assert after.get("promotion", {}).get("profile") == "HLP-realtime"


def test_tui_multi_soft_buffer_merge_and_promote(tmp_path):
    _adapter, client, store, session, controller = _started_hlp_tui(tmp_path)
    run(controller.handle(session.id, "start work"))

    added1 = run(controller.handle(session.id, "/soft 先别动 production 配置"))
    assert "soft buffered (1)" in added1.output
    assert "Soft buffer" in added1.output

    added2 = run(
        controller.handle(
            session.id,
            "/soft --intent clarify 重点看 token 过期路径",
        )
    )
    assert "soft buffered (2)" in added2.output

    listed = run(controller.handle(session.id, "/soft list"))
    assert "先别动 production 配置" in listed.output
    assert "重点看 token 过期路径" in listed.output
    assert "2." in listed.output

    softs = run(controller.handle(session.id, "/softs"))
    assert "Soft buffer" in softs.output

    active = store.resume(session.id)
    assert len(active.soft_buffer) == 2

    promoted = run(controller.handle(session.id, "/promote"))
    assert "promoted 2 soft → amended task" in promoted.output
    assert "merged=" in promoted.output
    assert "先别动 production" in promoted.output
    assert "token 过期" in promoted.output

    after = store.resume(session.id)
    assert after.soft_buffer == ()
    task = run(client.get_task(after.active_task_id))
    assert task.state == "in_progress"
    text = task.steering_log[-1].text
    assert "先别动 production 配置" in text
    assert "重点看 token 过期路径" in text

    empty = run(controller.handle(session.id, "/promote"))
    assert "error:" in empty.output
    assert "soft buffer empty" in empty.output


def test_tui_soft_pop_and_clear(tmp_path):
    _adapter, _client, store, session, controller = _started_hlp_tui(tmp_path)
    run(controller.handle(session.id, "/soft one"))
    run(controller.handle(session.id, "/soft two"))
    popped = run(controller.handle(session.id, "/soft pop"))
    assert "soft popped: two" in popped.output
    assert len(store.resume(session.id).soft_buffer) == 1
    cleared = run(controller.handle(session.id, "/soft clear"))
    assert "soft buffer cleared" in cleared.output
    assert store.resume(session.id).soft_buffer == ()


def test_soft_buffer_persists_across_session_store_reload(tmp_path):
    from loops.tui.session import SessionStore

    path = tmp_path / "sess.json"
    store = SessionStore(path)
    session = store.create(cwd="/repo", adapter="fake")
    store.add_soft(session.id, text="alpha", intent="constrain", confidence=0.9)
    store.add_soft(session.id, text="beta", intent="clarify")
    reloaded = SessionStore(path)
    again = reloaded.resume(session.id)
    assert len(again.soft_buffer) == 2
    assert again.soft_buffer[0].text == "alpha"
    assert again.soft_buffer[0].confidence == 0.9
    assert again.soft_buffer[1].text == "beta"


def test_hlp_permissions_record_session_metadata_only(tmp_path):
    adapter, _client, store, session, controller = _started_hlp_tui(tmp_path)

    auto = run(controller.handle(session.id, "/permissions auto"))
    plan = run(controller.handle(session.id, "/permissions plan"))
    confirm = run(controller.handle(session.id, "/permissions confirm"))
    read_only = run(controller.handle(session.id, "/permissions read-only"))
    unsupported = run(controller.handle(session.id, "/permissions suggest"))
    updated = store.resume(session.id)

    assert "permission_mode=auto" in auto.output
    assert "permission_mode=plan" in plan.output
    assert "permission_mode=confirm" in confirm.output
    assert "permission_mode=read-only" in read_only.output
    assert updated.permission_mode == "read-only"
    assert "unsupported permission mode: suggest" in unsupported.output
    assert [name for name, _payload in adapter.calls] == ["delegate"]


def test_run_lines_executes_line_oriented_tui(tmp_path):
    from loops.tui.app import run_lines

    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)

    outputs = run(
        run_lines(
            lines=("Review the patch", "/statusline", "/model gpt-5", "!git status"),
            client=client,
            session_path=tmp_path / "sessions.json",
            cwd="/repo",
            adapter_name="fake",
        )
    )

    joined = "\n".join(outputs)
    assert "started task" in joined
    assert "state=in_progress" in joined
    assert "model=gpt-5" in joined
    assert "captured shell input: git status" in joined


def test_run_lines_stops_on_archive_or_delete_exit(tmp_path):
    from loops.tui.app import run_lines

    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)

    archive_outputs = run(
        run_lines(
            lines=("/archive", "/help"),
            client=client,
            session_path=tmp_path / "archive-sessions.json",
            cwd="/repo",
            adapter_name="fake",
        )
    )
    delete_outputs = run(
        run_lines(
            lines=("/delete confirm", "/help"),
            client=client,
            session_path=tmp_path / "delete-sessions.json",
            cwd="/repo",
            adapter_name="fake",
        )
    )

    assert archive_outputs == ["archived session"]
    assert delete_outputs == ["deleted session"]
    assert adapter.calls == []


def test_delete_requires_confirmation(tmp_path):
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="fake")
    controller = TUIController(client=HLPClient(adapter=FakeAgentAdapter()), sessions=store)

    result = run(controller.handle(session.id, "/delete"))

    assert "error:" in result.output
    assert "/delete requires confirmation" in result.output
    assert store.resume(session.id).id == session.id


def test_run_lines_new_switches_following_prompt_to_fresh_session(tmp_path):
    from loops.tui.app import run_lines

    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)

    outputs = run(
        run_lines(
            lines=("Review the patch", "/new", "Review another patch"),
            client=client,
            session_path=tmp_path / "sessions.json",
            cwd="/repo",
            adapter_name="fake",
        )
    )

    assert outputs[0].startswith("started task")
    assert outputs[1].startswith("new session")
    assert outputs[2].startswith("started task")
    assert "amended task" not in "\n".join(outputs)
    assert [name for name, _payload in adapter.calls] == ["delegate", "delegate"]


def test_run_lines_resume_switches_following_prompt_to_target_session(tmp_path):
    from loops.tui.app import run_lines

    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    target = store.create(cwd="/repo", adapter="fake")
    controller = TUIController(client=client, sessions=store)
    run(controller.handle(target.id, "Review the target patch"))

    outputs = run(
        run_lines(
            lines=(f"/resume {target.id}", "Focus on target auth"),
            client=client,
            session_path=tmp_path / "sessions.json",
            cwd="/repo",
            adapter_name="fake",
        )
    )

    assert outputs[0].startswith("session=" + target.id)
    assert outputs[1].startswith("amended task")
    assert [name for name, _payload in adapter.calls] == ["delegate", "steer"]


def test_run_lines_rejects_unsupported_adapter_name(tmp_path):
    from loops.tui.app import run_lines

    with pytest.raises(ValueError, match="unsupported adapter: mystery"):
        run(
            run_lines(
                lines=("Review the patch",),
                client=HLPClient(adapter=FakeAgentAdapter()),
                session_path=tmp_path / "sessions.json",
                cwd="/repo",
                adapter_name="mystery",
            )
        )

    assert not (tmp_path / "sessions.json").exists()


def test_build_client_uses_harness_capable_codex_and_pi():
    from loops.tui.app import build_client

    codex = build_client("codex", timeout=12.0)
    pi = build_client("pi", timeout=12.0)
    fake = build_client("fake")

    assert isinstance(codex.adapter, CodexHarnessAdapter)
    assert codex.adapter.timeout == 12.0
    assert codex.adapter.command[:3] == ("codex", "exec", "--json")
    assert isinstance(pi.adapter, PiHarnessAdapter)
    assert pi.adapter.timeout == 12.0
    # Session continuity (default) strips --no-session so runs are resumable.
    assert "--no-session" not in pi.adapter.command
    assert pi.adapter.command[:4] == ("pi", "--mode", "json", "-p")
    assert "--no-tools" in pi.adapter.command
    assert isinstance(fake.adapter, FakeAgentAdapter)


def _harness_human_loop_runner(*, flavor: str, run_id: str):
    """Injected Codex/Pi harness runner that emits approval then artifact."""

    async def runner(command, request, timeout):
        correlation = request["correlation_id"]
        event_key = "hlp" if flavor == "codex" else "pi"
        event_type = "hlp.event" if flavor == "codex" else "pi.event"
        if request["operation"] == "delegate":
            return ProcessResult(
                exit_code=0,
                stdout="\n".join(
                    (
                        json.dumps(
                            {
                                "type": event_type,
                                "run_id": run_id,
                                "correlation_id": correlation,
                                event_key: {
                                    "kind": "needs_approval",
                                    "agent_id": "agent_tui",
                                    "prompt": f"Allow {flavor} side effects?",
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "turn.completed",
                                "run_id": run_id,
                                "correlation_id": correlation,
                                "status": "ok",
                                "summary": f"{flavor} delegated",
                            }
                        ),
                    )
                ),
                stderr="",
            )
        if request["operation"] == "resume":
            return ProcessResult(
                exit_code=0,
                stdout="\n".join(
                    (
                        json.dumps(
                            {
                                "type": event_type,
                                "run_id": run_id,
                                "correlation_id": correlation,
                                event_key: {
                                    "kind": "artifact",
                                    "agent_id": "agent_tui",
                                    "artifact_type": "review-report",
                                    "artifact_uri": f"mem://{flavor}-report",
                                    "artifact_checksum": f"sha256:{flavor}",
                                    "artifact_size": 11,
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "turn.completed",
                                "run_id": run_id,
                                "correlation_id": correlation,
                                "status": "ok",
                            }
                        ),
                    )
                ),
                stderr="",
            )
        return ProcessResult(
            exit_code=0,
            stdout=json.dumps(
                {
                    "type": "turn.completed",
                    "run_id": run_id,
                    "correlation_id": correlation,
                    "status": "ok",
                }
            ),
            stderr="",
        )

    return runner


def test_tui_codex_harness_auto_projects_checkpoint_then_artifact_after_approve(tmp_path):
    adapter = CodexHarnessAdapter(
        runner=_harness_human_loop_runner(flavor="codex", run_id="codex_tui_hl"),
        timeout=9.0,
    )
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="codex", principal="user_local")
    controller = TUIController(client=client, sessions=store)

    started = run(controller.handle(session.id, "Review PR with Codex harness"))
    assert "started task" in started.output
    assert "Allow codex side effects?" in started.output
    assert "checkpoint pending" in started.output
    assert "inbox:" in started.output

    inbox = run(controller.handle(session.id, "/inbox"))
    assert "resolve_checkpoint" in inbox.output
    assert "Allow codex side effects?" in inbox.output

    approved = run(controller.handle(session.id, "/approve"))
    assert "approved checkpoint" in approved.output
    assert "artifact ready" in approved.output or "review-report" in approved.output
    assert "inbox:" in approved.output

    reviewed = run(controller.handle(session.id, "/review approved"))
    assert "verdict=approved" in reviewed.output

    active = store.resume(session.id)
    transcript = "\n".join(event.text for event in active.transcript)
    assert "Allow codex side effects?" in transcript
    assert "started task" in transcript
    task = run(client.get_task(active.active_task_id))
    assert task.state == "completed"


def test_tui_pi_harness_auto_projects_checkpoint_then_artifact_after_approve(tmp_path):
    adapter = PiHarnessAdapter(
        runner=_harness_human_loop_runner(flavor="pi", run_id="pi_tui_hl"),
        timeout=9.0,
    )
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="pi", principal="user_local")
    controller = TUIController(client=client, sessions=store)

    started = run(controller.handle(session.id, "Review PR with Pi harness"))
    assert "started task" in started.output
    assert "Allow pi side effects?" in started.output
    assert "checkpoint pending" in started.output

    approved = run(controller.handle(session.id, "/approve"))
    assert "approved checkpoint" in approved.output
    assert "mem://pi-report" in approved.output or "artifact ready" in approved.output

    reviewed = run(controller.handle(session.id, "/review approved"))
    assert "verdict=approved" in reviewed.output
    active = store.resume(session.id)
    assert run(client.get_task(active.active_task_id)).state == "completed"


def test_render_human_loop_summarizes_projected_checkpoint_and_inbox():
    from loops.hlp import Checkpoint, HumanInboxItem
    from loops.tui.render import render_human_loop

    ckpt = Checkpoint(
        task_id="task_1",
        kind="approval",
        prompt="Ship it?",
        raised_by="agent",
    )
    inbox = [
        HumanInboxItem(
            kind="checkpoint",
            action="resolve_checkpoint",
            task_id="task_1",
            subject_id=ckpt.id,
            title="Ship it?",
            principal="user_local",
        ),
    ]
    text = render_human_loop([ckpt], inbox)
    assert "checkpoint pending: Ship it?" in text
    assert "inbox:" in text
    assert "/approve" in text or "/inbox" in text


def test_render_agent_reply_prefers_summary_text():
    from loops.tui.render import render_agent_reply

    assert (
        render_agent_reply(
            {
                "status": "success",
                "summary": "Acknowledged hello request",
                "run_id": "run_1",
            }
        )
        == "agent: Acknowledged hello request"
    )
    assert render_agent_reply({"status": "ok"}) == "agent status: ok"
    assert render_agent_reply(None) == ""


def test_tui_surfaces_pi_summary_when_no_human_events(tmp_path):
    async def runner(command, request, timeout):
        return ProcessResult(
            exit_code=0,
            stdout=json.dumps(
                {
                    "run_id": "pi_summary_run",
                    "correlation_id": request["correlation_id"],
                    "status": "success",
                    "summary": "Acknowledged hello request",
                }
            ),
            stderr="",
        )

    adapter = PiHarnessAdapter(runner=runner, timeout=9.0, prompt_mode="chat")
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="pi", principal="user_local")
    controller = TUIController(client=client, sessions=store)

    started = run(controller.handle(session.id, "hello"))
    assert "started task" in started.output
    assert "agent: Acknowledged hello request" in started.output
    active = store.resume(session.id)
    transcript = "\n".join(event.text for event in active.transcript)
    assert "agent: Acknowledged hello request" in transcript


def test_chat_mode_prompt_puts_user_message_first():
    from loops.hlp.adapters import (
        chat_mode_prompt,
        cli_operation_prompt,
        prompt_for_adapter_operation,
    )

    request = {
        "operation": "delegate",
        "task_id": "task_hello",
        "correlation_id": "task_hello",
        "input": {"goal": "hello"},
    }
    chat = chat_mode_prompt(request)
    assert chat.startswith("hello\n")
    assert "correlation_id MUST be exactly: task_hello" in chat
    assert "You are executing an HLP adapter operation." not in chat
    assert "HLP request:" not in chat

    protocol = cli_operation_prompt(request)
    assert "You are executing an HLP adapter operation." in protocol
    assert "HLP request:" in protocol

    assert prompt_for_adapter_operation(request, mode="chat").startswith("hello\n")
    assert "HLP adapter operation" in prompt_for_adapter_operation(request, mode="protocol")
    # Lifecycle ops stay protocol-shaped even in chat mode adapters.
    resume_req = {**request, "operation": "resume"}
    assert "HLP adapter operation" in prompt_for_adapter_operation(resume_req, mode="chat")
    # Follow-up turns (amend → steer) also use chat shape.
    steer_req = {
        "operation": "steer",
        "run_id": "run_1",
        "correlation_id": "task_hello",
        "amendment": {"text": "介绍下项目", "intent": "clarify", "by": "user_local"},
    }
    steer_chat = prompt_for_adapter_operation(steer_req, mode="chat")
    assert steer_chat.startswith("介绍下项目\n")
    assert "HLP adapter operation" not in steer_chat


def test_tui_follow_up_prompt_reinvokes_chat_and_refreshes_agent_reply(tmp_path):
    """Second user message must not reuse the first turn's summary."""
    turns: list[str] = []

    async def runner(command, request, timeout):
        prompt = command[-1]
        turns.append(request["operation"])
        if request["operation"] == "delegate":
            assert prompt.startswith("hello\n")
            return ProcessResult(
                exit_code=0,
                stdout=json.dumps(
                    {
                        "run_id": "chat_run_mt",
                        "correlation_id": request["correlation_id"],
                        "status": "success",
                        "summary": "Hello! How can I help?",
                    }
                ),
                stderr="",
            )
        if request["operation"] == "steer":
            assert prompt.startswith("介绍下项目\n")
            assert "You are executing an HLP adapter operation." not in prompt
            return ProcessResult(
                exit_code=0,
                stdout=json.dumps(
                    {
                        "run_id": "chat_run_mt",
                        "correlation_id": request["correlation_id"],
                        "status": "success",
                        "summary": "Loops is an HLP SDK for human-agent responsibility loops.",
                    }
                ),
                stderr="",
            )
        return ProcessResult(
            exit_code=0,
            stdout=json.dumps(
                {
                    "run_id": request.get("run_id") or "chat_run_mt",
                    "correlation_id": request["correlation_id"],
                    "status": "ok",
                }
            ),
            stderr="",
        )

    adapter = PiHarnessAdapter(runner=runner, timeout=9.0, prompt_mode="chat")
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="pi", principal="user_local")
    controller = TUIController(client=client, sessions=store)

    first = run(controller.handle(session.id, "hello"))
    assert "agent: Hello! How can I help?" in first.output

    second = run(controller.handle(session.id, "介绍下项目"))
    assert "amended task" in second.output
    assert "agent: Loops is an HLP SDK for human-agent responsibility loops." in second.output
    assert "Hello! How can I help?" not in second.output
    assert turns == ["delegate", "steer"]


def test_tui_chat_mode_delegate_sends_user_first_prompt_and_shows_reply(tmp_path):
    captured: list[dict] = []

    async def runner(command, request, timeout):
        captured.append({"command": command, "request": request})
        return ProcessResult(
            exit_code=0,
            stdout=json.dumps(
                {
                    "run_id": "chat_run_1",
                    "correlation_id": request["correlation_id"],
                    "status": "success",
                    "summary": "Hi there — chat mode works.",
                }
            ),
            stderr="",
        )

    adapter = PiHarnessAdapter(runner=runner, timeout=9.0, prompt_mode="chat")
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="pi", principal="user_local")
    controller = TUIController(client=client, sessions=store)

    started = run(controller.handle(session.id, "hello"))
    assert captured, "runner was not invoked"
    prompt = captured[0]["command"][-1]
    assert prompt.startswith("hello\n")
    assert "You are executing an HLP adapter operation." not in prompt
    assert "correlation_id MUST be exactly:" in prompt
    request_correlation = captured[0]["request"]["correlation_id"]
    assert str(request_correlation).startswith("task_")
    assert "agent: Hi there — chat mode works." in started.output
    assert "started task" in started.output


def test_tui_build_client_enables_chat_prompt_mode_for_live_harnesses():
    from loops.tui.app import build_client

    codex = build_client("codex")
    pi = build_client("pi")
    assert codex.adapter.prompt_mode == "chat"
    assert pi.adapter.prompt_mode == "chat"


def test_tui_chat_mode_still_projects_human_events_after_delegate(tmp_path):
    async def runner(command, request, timeout):
        correlation = request["correlation_id"]
        if request["operation"] == "delegate":
            # Chat prompt is still used, but harness may emit human events.
            assert command[-1].startswith("Review PR with chat mode\n") or (
                "Review PR with chat mode" in command[-1]
            )
            return ProcessResult(
                exit_code=0,
                stdout="\n".join(
                    (
                        json.dumps(
                            {
                                "type": "pi.event",
                                "run_id": "pi_chat_hl",
                                "correlation_id": correlation,
                                "pi": {
                                    "kind": "needs_approval",
                                    "agent_id": "agent_tui",
                                    "prompt": "Proceed with chat-mode work?",
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "turn.completed",
                                "run_id": "pi_chat_hl",
                                "correlation_id": correlation,
                                "status": "ok",
                                "summary": "Need approval before continuing",
                            }
                        ),
                    )
                ),
                stderr="",
            )
        return ProcessResult(
            exit_code=0,
            stdout=json.dumps(
                {
                    "type": "turn.completed",
                    "run_id": request.get("run_id") or "pi_chat_hl",
                    "correlation_id": correlation,
                    "status": "ok",
                }
            ),
            stderr="",
        )

    adapter = PiHarnessAdapter(runner=runner, timeout=9.0, prompt_mode="chat")
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="pi", principal="user_local")
    controller = TUIController(client=client, sessions=store)

    started = run(controller.handle(session.id, "Review PR with chat mode"))
    assert "agent: Need approval before continuing" in started.output
    assert "checkpoint pending: Proceed with chat-mode work?" in started.output
    assert "inbox:" in started.output


def test_run_with_progress_emits_heartbeat_until_done():
    from loops.tui.app import run_with_progress

    lines: list[str] = []

    async def slow():
        await asyncio.sleep(0.05)
        return "ok"

    result = run(
        run_with_progress(
            slow(),
            label="pi adapter",
            timeout=1.0,
            every=0.02,
            printer=lambda *args, **kwargs: lines.append(args[0] if args else ""),
        )
    )

    assert result == "ok"
    assert lines[0].startswith("… pi adapter (timeout 1s)")
    assert any("still waiting" in line for line in lines)


def test_run_lines_accepts_pi_adapter_metadata_with_injected_client(tmp_path):
    from loops.tui.app import run_lines

    async def runner(command, request, timeout):
        return ProcessResult(
            exit_code=0,
            stdout=json.dumps(
                {
                    "run_id": "pi_tui_run",
                    "correlation_id": request["correlation_id"],
                    "status": "ok",
                }
            ),
            stderr="",
        )

    adapter = PiHarnessAdapter(runner=runner)
    client = HLPClient(adapter=adapter)

    outputs = run(
        run_lines(
            lines=("Review through Pi", "/statusline"),
            client=client,
            session_path=tmp_path / "sessions.json",
            cwd="/repo",
            adapter_name="pi",
        )
    )

    joined = "\n".join(outputs)
    assert "started task" in joined
    assert "adapter=pi" in joined
    assert "delegate" in [name for name, _payload in adapter.calls]


def test_hlp_tui_demo_runs_full_offline_human_loop():
    from examples.hlp_tui_demo import run_demo as run_tui_demo

    result = run(run_tui_demo())

    assert result["adapter_name"] == "codex-cli"
    assert result["process_summary"] == "TUI demo delegate accepted"
    assert result["final_task_state"] == "completed"
    assert result["checkpoint_decision"] == "approve"
    assert result["review_verdict"] == "approved"
    assert result["adapter_operations"] == ["delegate", "block", "resume"]
    assert "task.checkpoint.raised" in result["audit_actions"]
    assert "task.checkpoint.resolved" in result["audit_actions"]
    assert "artifact.committed" in result["audit_actions"]
    assert "review.submitted" in result["audit_actions"]
    assert "task.completed" in result["audit_actions"]


def test_tui_package_exports_app_controller_session_and_render_apis():
    import loops.tui as tui

    for name in (
        "build_client",
        "main",
        "run_lines",
        "run_with_progress",
        "StreamPrinter",
        "TUIController",
        "TUIResult",
        "TUISessionError",
        "TUIUsageError",
        "SessionStore",
        "SoftBufferEntry",
        "TUISession",
        "TranscriptEvent",
        "render_agent_reply",
        "render_audit",
        "render_error",
        "render_help",
        "render_human_loop",
        "render_inbox",
        "render_lines",
        "render_soft_buffer",
        "render_status",
        "render_transcript",
    ):
        assert hasattr(tui, name)
        assert name in tui.__all__


def test_format_harness_stream_line_maps_pi_and_status_events():
    from loops.hlp.adapters import format_harness_stream_line

    assert format_harness_stream_line("") is None
    assert format_harness_stream_line('{"type":"session","id":"x"}') is None
    start = format_harness_stream_line('{"type":"agent_start"}')
    assert start is not None and start.kind == "status" and "agent start" in start.text

    thinking = format_harness_stream_line(
        json.dumps(
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "thinking_delta", "delta": "noise"},
            }
        )
    )
    assert thinking is None

    delta = format_harness_stream_line(
        json.dumps(
            {
                "type": "message_update",
                "assistantMessageEvent": {"type": "text_delta", "delta": "Hel"},
            }
        )
    )
    assert delta is not None
    assert delta.kind == "text"
    assert delta.text == "Hel"
    assert delta.newline is False

    approval = format_harness_stream_line(
        json.dumps(
            {
                "type": "hlp.event",
                "hlp": {"kind": "needs_approval", "prompt": "Ship?"},
            }
        )
    )
    assert approval is not None
    assert "needs_approval" in approval.text
    assert "Ship?" in approval.text


def test_stream_printer_coalesces_text_deltas():
    from loops.hlp.adapters import StreamChunk
    from loops.tui.stream import StreamPrinter

    lines: list[str] = []

    def printer(*args, **kwargs):
        text = args[0] if args else ""
        end = kwargs.get("end", "\n")
        lines.append(text + ("" if end == "" else "\n"))

    sp = StreamPrinter(printer=printer)
    sp(StreamChunk(kind="status", text="agent start"))
    sp(StreamChunk(kind="text", text="Hel", newline=False))
    sp(StreamChunk(kind="text", text="lo", newline=False))
    sp(StreamChunk(kind="status", text="turn end"))
    sp.close()
    joined = "".join(lines)
    assert "⋯ agent start" in joined
    assert "⋯ agent: Hello" in joined or (
        "⋯ agent: " in joined and "Hel" in joined and "lo" in joined
    )
    assert "⋯ turn end" in joined


def test_run_prompt_process_streaming_invokes_chunk_callback():
    from loops.hlp.adapters import StreamChunk, run_prompt_process_streaming

    chunks: list[StreamChunk] = []

    async def on_chunk(chunk: StreamChunk) -> None:
        chunks.append(chunk)

    # Emit two JSONL events then exit — no network harness required.
    script = (
        "import sys\n"
        'print(\'{"type":"agent_start"}\', flush=True)\n'
        'print(\'{"type":"message_update","assistantMessageEvent":'
        '{"type":"text_delta","delta":"Hi"}}\', flush=True)\n'
    )
    result = run(
        run_prompt_process_streaming(
            (sys.executable, "-c", script),
            {"operation": "delegate", "correlation_id": "task_x"},
            5.0,
            on_chunk=on_chunk,
        )
    )
    assert result.exit_code == 0
    assert any(c.kind == "status" for c in chunks)
    assert any(c.kind == "text" and c.text == "Hi" for c in chunks)
    assert "agent_start" in result.stdout


def test_format_harness_stream_line_maps_kimi_shapes():
    from loops.hlp.adapters import format_harness_stream_line

    assistant = format_harness_stream_line(
        json.dumps({"role": "assistant", "content": "Kimi reply text"})
    )
    assert assistant is not None
    assert assistant.kind == "text"
    assert assistant.text == "Kimi reply text"
    assert assistant.newline is False

    meta = format_harness_stream_line(
        json.dumps(
            {
                "role": "meta",
                "type": "session.resume_hint",
                "session_id": "session_x",
                "command": "kimi -r session_x",
                "content": "To resume this session: kimi -r session_x",
            }
        )
    )
    assert meta is None


def test_format_harness_stream_line_maps_claude_shapes():
    from loops.hlp.adapters import format_harness_stream_line

    assert (
        format_harness_stream_line(
            json.dumps({"type": "system", "subtype": "init", "session_id": "s", "model": "m"})
        )
        is None
    )

    thinking = format_harness_stream_line(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "thinking", "thinking": "reasoning"}],
                },
            }
        )
    )
    assert thinking is not None
    assert thinking.kind == "thinking"

    text = format_harness_stream_line(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "reasoning"},
                        {"type": "text", "text": "Hel"},
                        {"type": "text", "text": "lo"},
                    ],
                },
            }
        )
    )
    assert text is not None
    assert text.kind == "text"
    assert text.text == "Hello"
    assert text.newline is False

    assert (
        format_harness_stream_line(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": "done",
                    "session_id": "s",
                }
            )
        )
        is None
    )

    error = format_harness_stream_line(
        json.dumps(
            {
                "type": "result",
                "subtype": "error",
                "is_error": True,
                "result": "permission denied",
                "session_id": "s",
            }
        )
    )
    assert error is not None
    assert error.kind == "error"
    assert "permission denied" in error.text


def test_build_client_supports_claude_and_kimi():
    from loops.tui.app import build_client

    claude = build_client("claude", stream=False)
    kimi = build_client("kimi", stream=False)

    assert isinstance(claude.adapter, ClaudeCodeHarnessAdapter)
    assert claude.adapter.prompt_mode == "chat"
    assert claude.adapter.command[:4] == ("claude", "-p", "--output-format", "stream-json")
    assert isinstance(kimi.adapter, KimiHarnessAdapter)
    assert kimi.adapter.prompt_mode == "chat"
    assert kimi.adapter.command[:4] == ("kimi", "--output-format", "stream-json", "-p")


def test_tasks_use_handoff_artifacts_show_commands(tmp_path):
    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    controller = TUIController(client=client, sessions=store)
    session, active = _start_hlp_tui_session(store, controller)
    task_id = active.active_task_id

    result = run(controller.handle(session.id, "/tasks"))
    assert task_id in result.output
    assert result.output.splitlines()[1].startswith("*")

    result = run(controller.handle(session.id, f"/use {task_id}"))
    assert "active task" in result.output

    terminal = run(client.create_task(principal="user_alice", goal="done"))
    run(client.operations.task_cancel(terminal.id, by="user_alice"))
    result = run(controller.handle(session.id, f"/use {terminal.id}"))
    assert "terminal" in result.output

    result = run(controller.handle(session.id, "/handoff agent_review"))
    assert "handed off task" in result.output
    assert "agent_review" in result.output
    assert store.resume(session.id).active_task_id == task_id

    artifact = run(
        client.commit_artifact(
            task_id=task_id,
            type="report",
            payload=ArtifactPayload(kind="inline", uri="mem://v1", checksum="sha256:v1"),
            produced_by="agent_review",
        )
    )
    result = run(controller.handle(session.id, "/artifacts"))
    assert artifact.id in result.output
    assert "mem://v1" in result.output
    result = run(controller.handle(session.id, f"/show {artifact.id}"))
    assert "mem://v1" in result.output
    assert "sha256:v1" in result.output


def test_interrupt_active_ctrl_c_semantics(tmp_path):
    from loops.tui.app import _interrupt_active

    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    controller = TUIController(client=client, sessions=store)
    session, active = _start_hlp_tui_session(store, controller)

    result = run(_interrupt_active(controller, session.id, active.principal))
    assert "interrupted: checkpoint" in result
    assert "blocked" in result
    task = run(client.get_task(active.active_task_id))
    assert task.state == "blocked"

    empty = store.create(cwd="/repo", adapter="fake")
    result = run(_interrupt_active(controller, empty.id, "user_local"))
    assert "no active task" in result


def test_build_client_passes_model_to_cli_commands():
    from loops.tui.app import build_client

    assert build_client("codex", stream=False, model="gpt-x").adapter.command[-2:] == (
        "-m",
        "gpt-x",
    )
    assert build_client("pi", stream=False, model="p1").adapter.command[-2:] == ("--model", "p1")
    claude_cmd = build_client("claude", stream=False, model="sonnet").adapter.command
    assert claude_cmd[-2:] == ("--model", "sonnet")
    assert build_client("kimi", stream=False, model="k2").adapter.command[-2:] == ("-m", "k2")
    assert "--model" not in build_client("pi", stream=False).adapter.command


def test_adapter_switch_rebuilds_client_and_hands_off_active_task(tmp_path):
    builds = []

    def builder(name, model, store):
        builds.append((name, model, store))
        return HLPClient(store=store, adapter=FakeAgentAdapter())

    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)
    store = SessionStore(tmp_path / "sessions.json")
    controller = TUIController(client=client, sessions=store, adapter_builder=builder)
    session, active = _start_hlp_tui_session(store, controller)
    original_store = client.store

    result = run(controller.handle(session.id, "/adapter codex"))

    assert result.output.startswith("adapter=codex")
    assert "handed off" in result.output
    assert builds and builds[-1][0] == "codex"
    # Shared store: task history survives the switch.
    assert builds[-1][2] is original_store
    assert store.resume(session.id).adapter == "codex"
    # Active task got a fresh run on the new adapter.
    assert store.resume(session.id).active_run_id


def test_adapter_switch_validation_and_missing_builder(tmp_path):
    client = HLPClient(adapter=FakeAgentAdapter())
    store = SessionStore(tmp_path / "sessions.json")
    controller = TUIController(client=client, sessions=store)
    session, _active = _start_hlp_tui_session(store, controller)

    result = run(controller.handle(session.id, "/adapter nope"))
    assert "unsupported adapter" in result.output
    result = run(controller.handle(session.id, "/adapter codex"))
    assert "not configured" in result.output


def test_model_command_rebuilds_live_adapter_and_records_for_fake(tmp_path):
    builds = []

    def builder(name, model, store):
        builds.append((name, model, store))
        return HLPClient(store=store, adapter=FakeAgentAdapter())

    store = SessionStore(tmp_path / "sessions.json")
    session = store.create(cwd="/repo", adapter="pi", principal="user_local")
    controller = TUIController(
        client=HLPClient(adapter=FakeAgentAdapter()),
        sessions=store,
        adapter_builder=builder,
    )

    result = run(controller.handle(session.id, "/model kimi-k2"))
    assert "model=kimi-k2" in result.output
    assert "client rebuilt" in result.output
    assert builds == [("pi", "kimi-k2", controller.client.store)]
    assert store.resume(session.id).model == "kimi-k2"

    fake_session = store.create(cwd="/repo", adapter="fake", principal="user_local")
    builds.clear()
    result = run(controller.handle(fake_session.id, "/model none"))
    assert "client rebuilt" not in result.output
    assert builds == []
