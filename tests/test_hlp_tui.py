from __future__ import annotations
import json
import asyncio

from loops.tui import session as session_module
from loops.tui.commands import (
    CommandParseError,
    InputIntent,
    parse_user_input,
)
from loops.hlp import (
    AgentAdapterError,
    ArtifactPayload,
    CheckpointOption,
    CodexHarnessAdapter,
    FakeAgentAdapter,
    HLPClient,
    PiHarnessAdapter,
    ProcessResult,
)
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
    checkpoint = run(client.raise_checkpoint(
        task_id=active.active_task_id,
        kind="approval",
        prompt="Apply patch?",
        raised_by="agent_tui",
    ))

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
    older = run(client.raise_checkpoint(
        task_id=older_active.active_task_id,
        kind=kind,
        prompt="Older checkpoint",
        options=options,
        raised_by="agent_tui",
    ))
    target = run(client.raise_checkpoint(
        task_id=target_active.active_task_id,
        kind=kind,
        prompt="Target checkpoint",
        options=options,
        raised_by="agent_tui",
    ))

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
    checkpoint = run(client.raise_checkpoint(
        task_id=active.active_task_id,
        kind="approval",
        prompt="Apply patch?",
        raised_by="agent_tui",
    ))

    rejected = run(controller.handle(session.id, "/reject unsafe state"))
    resolved = client.store.get_checkpoint(checkpoint.id)

    assert "rejected checkpoint" in rejected.output
    assert resolved.resolution is not None
    assert resolved.resolution.action == "reject"
    assert resolved.resolution.comment == "unsafe state"


def test_hlp_choose_and_input_resolve_current_checkpoint(tmp_path):
    _adapter, client, store, session, controller = _started_hlp_tui(tmp_path)
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
        artifact = run(client.commit_artifact(
            task_id=active.active_task_id,
            type="patch",
            payload=ArtifactPayload(
                kind="inline",
                uri=f"mem://{name}-patch",
                checksum=f"sha256:{name}-patch",
            ),
            produced_by="agent_tui",
        ))

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
    older_artifact = run(client.commit_artifact(
        task_id=older_active.active_task_id,
        type="patch",
        payload=ArtifactPayload(
            kind="inline",
            uri="mem://older-patch",
            checksum="sha256:older-patch",
        ),
        produced_by="agent_tui",
    ))
    target_artifact = run(client.commit_artifact(
        task_id=target_active.active_task_id,
        type="patch",
        payload=ArtifactPayload(
            kind="inline",
            uri="mem://target-patch",
            checksum="sha256:target-patch",
        ),
        produced_by="agent_tui",
    ))

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
    artifact = run(client.commit_artifact(
        task_id=active.active_task_id,
        type="patch",
        payload=ArtifactPayload(
            kind="inline",
            uri="mem://commented-patch",
            checksum="sha256:commented-patch",
        ),
        produced_by="agent_tui",
    ))

    result = run(controller.handle(session.id, "/review commented FYI only"))

    assert "error:" in result.output
    assert "unsupported review verdict: commented" in result.output
    assert client.store.reviews_of_artifact(artifact.id) == []


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


def test_run_lines_stops_on_archive_or_delete_exit(tmp_path):
    from loops.tui.app import run_lines

    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)

    archive_outputs = run(run_lines(
        lines=("/archive", "/help"),
        client=client,
        session_path=tmp_path / "archive-sessions.json",
        cwd="/repo",
        adapter_name="fake",
    ))
    delete_outputs = run(run_lines(
        lines=("/delete confirm", "/help"),
        client=client,
        session_path=tmp_path / "delete-sessions.json",
        cwd="/repo",
        adapter_name="fake",
    ))

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

    outputs = run(run_lines(
        lines=("Review the patch", "/new", "Review another patch"),
        client=client,
        session_path=tmp_path / "sessions.json",
        cwd="/repo",
        adapter_name="fake",
    ))

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

    outputs = run(run_lines(
        lines=(f"/resume {target.id}", "Focus on target auth"),
        client=client,
        session_path=tmp_path / "sessions.json",
        cwd="/repo",
        adapter_name="fake",
    ))

    assert outputs[0].startswith("session=" + target.id)
    assert outputs[1].startswith("amended task")
    assert [name for name, _payload in adapter.calls] == ["delegate", "steer"]


def test_run_lines_rejects_unsupported_adapter_name(tmp_path):
    from loops.tui.app import run_lines

    with pytest.raises(ValueError, match="unsupported adapter: mystery"):
        run(run_lines(
            lines=("Review the patch",),
            client=HLPClient(adapter=FakeAgentAdapter()),
            session_path=tmp_path / "sessions.json",
            cwd="/repo",
            adapter_name="mystery",
        ))

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
    assert pi.adapter.command[:6] == (
        "pi",
        "--mode",
        "json",
        "-p",
        "--no-session",
        "--no-tools",
    )
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
                stdout="\n".join((
                    json.dumps({
                        "type": event_type,
                        "run_id": run_id,
                        "correlation_id": correlation,
                        event_key: {
                            "kind": "needs_approval",
                            "agent_id": "agent_tui",
                            "prompt": f"Allow {flavor} side effects?",
                        },
                    }),
                    json.dumps({
                        "type": "turn.completed",
                        "run_id": run_id,
                        "correlation_id": correlation,
                        "status": "ok",
                        "summary": f"{flavor} delegated",
                    }),
                )),
                stderr="",
            )
        if request["operation"] == "resume":
            return ProcessResult(
                exit_code=0,
                stdout="\n".join((
                    json.dumps({
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
                    }),
                    json.dumps({
                        "type": "turn.completed",
                        "run_id": run_id,
                        "correlation_id": correlation,
                        "status": "ok",
                    }),
                )),
                stderr="",
            )
        return ProcessResult(
            exit_code=0,
            stdout=json.dumps({
                "type": "turn.completed",
                "run_id": run_id,
                "correlation_id": correlation,
                "status": "ok",
            }),
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
    from loops.tui.render import render_human_loop
    from loops.hlp import Checkpoint, HumanInboxItem

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

    assert render_agent_reply({
        "status": "success",
        "summary": "Acknowledged hello request",
        "run_id": "run_1",
    }) == "agent: Acknowledged hello request"
    assert render_agent_reply({"status": "ok"}) == "agent status: ok"
    assert render_agent_reply(None) == ""


def test_tui_surfaces_pi_summary_when_no_human_events(tmp_path):
    async def runner(command, request, timeout):
        return ProcessResult(
            exit_code=0,
            stdout=json.dumps({
                "run_id": "pi_summary_run",
                "correlation_id": request["correlation_id"],
                "status": "success",
                "summary": "Acknowledged hello request",
            }),
            stderr="",
        )

    adapter = PiHarnessAdapter(runner=runner, timeout=9.0)
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


def test_run_with_progress_emits_heartbeat_until_done():
    from loops.tui.app import run_with_progress

    lines: list[str] = []

    async def slow():
        await asyncio.sleep(0.05)
        return "ok"

    result = run(run_with_progress(
        slow(),
        label="pi adapter",
        timeout=1.0,
        every=0.02,
        printer=lambda *args, **kwargs: lines.append(args[0] if args else ""),
    ))

    assert result == "ok"
    assert lines[0].startswith("… pi adapter (timeout 1s)")
    assert any("still waiting" in line for line in lines)


def test_run_lines_accepts_pi_adapter_metadata_with_injected_client(tmp_path):
    from loops.tui.app import run_lines

    async def runner(command, request, timeout):
        return ProcessResult(
            exit_code=0,
            stdout=json.dumps({
                "run_id": "pi_tui_run",
                "correlation_id": request["correlation_id"],
                "status": "ok",
            }),
            stderr="",
        )

    adapter = PiHarnessAdapter(runner=runner)
    client = HLPClient(adapter=adapter)

    outputs = run(run_lines(
        lines=("Review through Pi", "/statusline"),
        client=client,
        session_path=tmp_path / "sessions.json",
        cwd="/repo",
        adapter_name="pi",
    ))

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
        "TUIController",
        "TUIResult",
        "TUISessionError",
        "TUIUsageError",
        "SessionStore",
        "TUISession",
        "TranscriptEvent",
        "render_agent_reply",
        "render_audit",
        "render_error",
        "render_help",
        "render_human_loop",
        "render_inbox",
        "render_lines",
        "render_status",
        "render_transcript",
    ):
        assert hasattr(tui, name)
        assert name in tui.__all__
