"""Session-resume continuity for the four first-party CLI harness adapters.

Delegate binds the CLI-native session id from the wire; follow-up ops
(block/resume/steer/cancel) resume the same native session instead of spawning
a fresh one-shot process. Fallback stays one-shot when no session id exists or
session_continuity=False.
"""

from __future__ import annotations

import asyncio
import json

from loops.hlp import (
    ClaudeCodeHarnessAdapter,
    CodexHarnessAdapter,
    KimiHarnessAdapter,
    PiHarnessAdapter,
    ProcessResult,
)


def run(coro):
    return asyncio.run(coro)


def _envelope(request, **extra):
    payload = {
        "run_id": "run_1",
        "correlation_id": request["correlation_id"],
        "status": "ok",
        "summary": "ack",
        "error": "",
    }
    payload.update(extra)
    return json.dumps(payload)


CODEX_STDOUT = lambda request: "\n".join(  # noqa: E731
    (
        json.dumps({"type": "thread.started", "thread_id": "thread_abc"}),
        json.dumps({"type": "turn.started"}),
        json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "item_0", "type": "agent_message", "text": _envelope(request)},
            }
        ),
    )
)

CLAUDE_STDOUT = lambda request: "\n".join(  # noqa: E731
    (
        json.dumps({"type": "system", "subtype": "init", "session_id": "sess_claude_1"}),
        json.dumps(
            {
                "type": "assistant",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "ack"}]},
            }
        ),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "ack",
                "session_id": "sess_claude_1",
                "structured_output": json.loads(_envelope(request)),
            }
        ),
    )
)

KIMI_STDOUT = lambda request: "\n".join(  # noqa: E731
    (
        json.dumps({"role": "assistant", "content": _envelope(request)}),
        json.dumps({"role": "meta", "type": "session.resume_hint", "session_id": "session_kimi_1"}),
    )
)

PI_STDOUT = lambda request: "\n".join(  # noqa: E731
    (
        json.dumps({"type": "session", "version": 3, "id": "pi_sess_1"}),
        json.dumps({"type": "agent_start"}),
        json.dumps(
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": _envelope(request)}],
                },
            }
        ),
        json.dumps(
            {
                "type": "turn.completed",
                "run_id": "run_1",
                "correlation_id": request["correlation_id"],
                "status": "ok",
            }
        ),
    )
)

CASES = {
    "codex": (
        CodexHarnessAdapter,
        CODEX_STDOUT,
        "thread_abc",
        ("codex", "exec", "resume"),
    ),
    "claude": (
        ClaudeCodeHarnessAdapter,
        CLAUDE_STDOUT,
        "sess_claude_1",
        ("claude", "--resume", "sess_claude_1"),
    ),
    "kimi": (
        KimiHarnessAdapter,
        KIMI_STDOUT,
        "session_kimi_1",
        ("kimi", "--output-format", "stream-json", "--session", "session_kimi_1"),
    ),
    "pi": (
        PiHarnessAdapter,
        PI_STDOUT,
        "pi_sess_1",
        ("pi", "--mode", "json", "--session", "pi_sess_1"),
    ),
}


def _drive(adapter_cls, stdout_fn):
    commands = []

    async def runner(command, request, timeout):
        commands.append(command)
        return ProcessResult(exit_code=0, stdout=stdout_fn(request), stderr="")

    adapter = adapter_cls(runner=runner)
    run_id = run(adapter.delegate("task_1", "agent_x", "probe", input={"goal": "g"}))
    run(adapter.block(run_id, "ckpt_1", "why"))
    run(adapter.resume(run_id, {"action": "approve"}))
    run(adapter.steer(run_id, {"text": "focus"}))
    run(adapter.cancel(run_id, "done"))
    return adapter, run_id, commands


def test_delegate_binds_native_session_and_followups_resume_it():
    for name, (adapter_cls, stdout_fn, session_id, resume_prefix) in CASES.items():
        adapter, run_id, commands = _drive(adapter_cls, stdout_fn)
        assert adapter.session_of_run(run_id) == session_id, name
        # Delegate is one-shot; all four follow-up ops resume the native session.
        for command in commands[1:]:
            assert command[: len(resume_prefix)] == resume_prefix, (name, command)


def test_followups_fall_back_to_one_shot_without_session_id():
    async def runner(command, request, timeout):
        # Wire carries no session event at all.
        return ProcessResult(
            exit_code=0,
            stdout=json.dumps({"role": "assistant", "content": _envelope(request)}),
            stderr="",
        )

    adapter = KimiHarnessAdapter(runner=runner)
    commands = []

    async def spy(command, request, timeout):
        commands.append(command)
        return await runner(command, request, timeout)

    adapter = KimiHarnessAdapter(runner=spy)
    run_id = run(adapter.delegate("task_1", "agent_x", "probe", input={"goal": "g"}))
    assert adapter.session_of_run(run_id) is None
    run(adapter.steer(run_id, {"text": "focus"}))
    assert commands[-1][:3] == ("kimi", "--output-format", "stream-json")
    assert "--session" not in commands[-1]


def test_session_continuity_off_keeps_one_shot_everywhere():
    commands = []

    async def runner(command, request, timeout):
        commands.append(command)
        return ProcessResult(exit_code=0, stdout=CLAUDE_STDOUT(request), stderr="")

    adapter = ClaudeCodeHarnessAdapter(runner=runner, session_continuity=False)
    run_id = run(adapter.delegate("task_1", "agent_x", "probe", input={"goal": "g"}))
    run(adapter.steer(run_id, {"text": "focus"}))
    assert "--resume" not in commands[-1]
    # ...and the old no-persistence flag is preserved.
    assert "--no-session-persistence" in adapter.command


def test_claude_resume_command_keeps_protocol_schema_and_drops_no_persistence():
    commands = []

    async def runner(command, request, timeout):
        commands.append(command)
        return ProcessResult(exit_code=0, stdout=CLAUDE_STDOUT(request), stderr="")

    adapter = ClaudeCodeHarnessAdapter(runner=runner)
    run_id = run(adapter.delegate("task_1", "agent_x", "probe", input={"goal": "g"}))
    run(adapter.steer(run_id, {"text": "focus"}))
    resume = commands[-1]
    assert "--no-session-persistence" not in adapter.command
    assert "--no-session-persistence" not in resume
    assert "--json-schema" in resume
    assert adapter.session_of_run(run_id) == "sess_claude_1"


def test_codex_resume_command_keeps_json_and_schema_file():
    commands = []

    async def runner(command, request, timeout):
        commands.append(command)
        return ProcessResult(exit_code=0, stdout=CODEX_STDOUT(request), stderr="")

    adapter = CodexHarnessAdapter(runner=runner)
    run_id = run(adapter.delegate("task_1", "agent_x", "probe", input={"goal": "g"}))
    run(adapter.block(run_id, "ckpt_1", "why"))
    resume = commands[-1]
    # codex exec resume [options] <thread_id> [prompt] — options come first.
    assert resume[:3] == ("codex", "exec", "resume")
    assert "--json" in resume
    assert "--output-schema" in resume
    assert "thread_abc" in resume
    assert resume.index("thread_abc") > resume.index("--json")
