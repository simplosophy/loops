"""Projection robustness for the four first-party CLI harness adapters.

Covers the wire variance real CLIs produce: markdown fences, surrounding prose,
CRLF, unicode, duplicate events, missing correlation, malformed lines — plus the
native structured-output wiring (Codex --output-schema, Claude --json-schema).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from loops.hlp import (
    AgentAdapterError,
    ClaudeCodeCLIAdapter,
    ClaudeCodeHarnessAdapter,
    CodexCLIAdapter,
    CodexHarnessAdapter,
    HLPClient,
    KimiHarnessAdapter,
    PiHarnessAdapter,
    ProcessResult,
)
from loops.hlp.adapters._parsing import HLP_RESULT_SCHEMA


def run(coro):
    return asyncio.run(coro)


def _ok_runner(payload: dict, *, line_prefix: str = "", line_suffix: str = ""):
    """Runner answering every op with one JSONL assistant event carrying payload."""

    async def runner(command, request, timeout):
        body = dict(payload)
        body.setdefault("correlation_id", request["correlation_id"])
        line = json.dumps(
            {"role": "assistant", "content": line_prefix + json.dumps(body) + line_suffix}
        )
        return ProcessResult(exit_code=0, stdout=line, stderr="")

    return runner


# ── Native structured-output wiring ────────────────────────────────


def test_protocol_mode_appends_json_schema_for_claude_adapters():
    for adapter in (ClaudeCodeHarnessAdapter(), ClaudeCodeCLIAdapter()):
        assert adapter.command[-2] == "--json-schema"
        schema = json.loads(adapter.command[-1])
        assert schema["required"]
        assert schema["additionalProperties"] is False


def test_chat_mode_skips_json_schema_for_claude_adapters():
    for adapter in (
        ClaudeCodeHarnessAdapter(prompt_mode="chat"),
        ClaudeCodeCLIAdapter(prompt_mode="chat"),
    ):
        assert "--json-schema" not in adapter.command


def test_protocol_mode_appends_output_schema_file_for_codex_adapters():
    for adapter in (CodexHarnessAdapter(), CodexCLIAdapter()):
        assert adapter.command[-2] == "--output-schema"
        with open(adapter.command[-1], encoding="utf-8") as handle:
            schema = json.load(handle)
        assert schema == HLP_RESULT_SCHEMA


def test_chat_mode_skips_output_schema_for_codex_harness():
    adapter = CodexHarnessAdapter(prompt_mode="chat")
    assert "--output-schema" not in adapter.command


def test_custom_command_is_never_rewritten():
    custom = ("claude", "-p", "--output-format", "json")
    adapter = ClaudeCodeCLIAdapter(command=custom)
    assert adapter.command == custom


def test_kimi_and_pi_have_no_structured_output_flags():
    for adapter in (KimiHarnessAdapter(), PiHarnessAdapter()):
        assert "--json-schema" not in adapter.command
        assert "--output-schema" not in adapter.command


def test_result_schema_is_closed_and_fully_required():
    # Codex strict mode: additionalProperties false, every property required.
    assert HLP_RESULT_SCHEMA["additionalProperties"] is False
    assert set(HLP_RESULT_SCHEMA["required"]) == set(HLP_RESULT_SCHEMA["properties"])


# ── Wire variance fixtures ─────────────────────────────────────────

_ENVELOPE = {"run_id": "run_x", "status": "ok", "summary": "done ✓ 完成"}


def test_kimi_payload_extracted_from_markdown_fenced_content():
    async def runner(command, request, timeout):
        body = dict(_ENVELOPE)
        body["correlation_id"] = request["correlation_id"]
        content = f"Sure, here you go:\n```json\n{json.dumps(body)}\n```\nHope that helps."
        line = json.dumps({"role": "assistant", "content": content})
        return ProcessResult(exit_code=0, stdout=line, stderr="")

    adapter = KimiHarnessAdapter(runner=runner)
    client = HLPClient(adapter=adapter)
    task = run(client.create_task(principal="user_a", goal="fenced"))
    handle = run(client.delegate(task.id, "agent_k", capability="probe"))
    assert handle.run_id == "run_x"
    payload = adapter.process_results[handle.run_id]
    assert payload["correlation_id"] == task.id
    assert payload["summary"] == "done ✓ 完成"


def test_kimi_payload_extracted_with_crlf_and_prose_lines():
    async def runner(command, request, timeout):
        body = dict(_ENVELOPE)
        body["correlation_id"] = request["correlation_id"]
        lines = (
            "thinking out loud, not json",
            json.dumps({"role": "assistant", "content": json.dumps(body)}),
            json.dumps({"role": "meta", "type": "session.resume_hint"}),
        )
        return ProcessResult(exit_code=0, stdout="\r\n".join(lines) + "\r\n", stderr="")

    adapter = KimiHarnessAdapter(runner=runner)
    client = HLPClient(adapter=adapter)
    task = run(client.create_task(principal="user_a", goal="crlf"))
    handle = run(client.delegate(task.id, "agent_k", capability="probe"))
    assert handle.run_id == "run_x"


def test_claude_structured_output_field_is_preferred_payload():
    async def runner(command, request, timeout):
        structured = {
            "run_id": "run_structured",
            "correlation_id": request["correlation_id"],
            "status": "ok",
            "summary": "validated",
            "error": "",
        }
        lines = (
            json.dumps({"type": "system", "subtype": "init"}),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "prose reply"}],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": "prose reply",
                    "structured_output": structured,
                }
            ),
        )
        return ProcessResult(exit_code=0, stdout="\n".join(lines), stderr="")

    adapter = ClaudeCodeHarnessAdapter(runner=runner)
    client = HLPClient(adapter=adapter)
    task = run(client.create_task(principal="user_a", goal="structured"))
    handle = run(client.delegate(task.id, "agent_c", capability="probe"))
    assert handle.run_id == "run_structured"
    assert adapter.process_results[handle.run_id]["summary"] == "validated"


def test_codex_item_completed_agent_message_payload():
    async def runner(command, request, timeout):
        body = dict(_ENVELOPE)
        body["correlation_id"] = request["correlation_id"]
        lines = (
            json.dumps({"type": "thread.started", "thread_id": "t1"}),
            json.dumps({"type": "turn.started"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"id": "item_0", "type": "agent_message", "text": json.dumps(body)},
                }
            ),
            json.dumps({"type": "turn.completed", "usage": {}}),
        )
        return ProcessResult(exit_code=0, stdout="\n".join(lines), stderr="")

    adapter = CodexHarnessAdapter(runner=runner)
    client = HLPClient(adapter=adapter)
    task = run(client.create_task(principal="user_a", goal="item.completed"))
    handle = run(client.delegate(task.id, "agent_x", capability="probe"))
    assert handle.run_id == "run_x"


def test_missing_correlation_echo_is_tolerated_but_run_still_binds():
    async def runner(command, request, timeout):
        # Model forgot correlation_id entirely; validation is when-present.
        line = json.dumps(
            {"role": "assistant", "content": json.dumps({"run_id": "run_y", "status": "ok"})}
        )
        return ProcessResult(exit_code=0, stdout=line, stderr="")

    adapter = KimiHarnessAdapter(runner=runner)
    client = HLPClient(adapter=adapter)
    task = run(client.create_task(principal="user_a", goal="no echo"))
    handle = run(client.delegate(task.id, "agent_k", capability="probe"))
    assert handle.run_id == "run_y"
    assert adapter.task_of_run(handle.run_id) == task.id
    # The adapter fills the absent echo from the request (local binding).
    assert adapter.process_results[handle.run_id]["correlation_id"] == task.id


def test_wrong_correlation_echo_still_rejected():
    async def runner(command, request, timeout):
        line = json.dumps(
            {
                "role": "assistant",
                "content": json.dumps(
                    {"run_id": "run_z", "status": "ok", "correlation_id": "task_WRONG"}
                ),
            }
        )
        return ProcessResult(exit_code=0, stdout=line, stderr="")

    adapter = KimiHarnessAdapter(runner=runner)
    client = HLPClient(adapter=adapter)
    task = run(client.create_task(principal="user_a", goal="wrong echo"))
    with pytest.raises(AgentAdapterError):
        run(client.delegate(task.id, "agent_k", capability="probe"))


def test_malformed_json_line_fails_fast_with_adapter_error():
    async def runner(command, request, timeout):
        return ProcessResult(exit_code=0, stdout='{"role":"assistant", broken', stderr="")

    adapter = KimiHarnessAdapter(runner=runner)
    client = HLPClient(adapter=adapter)
    task = run(client.create_task(principal="user_a", goal="broken"))
    with pytest.raises(AgentAdapterError):
        run(client.delegate(task.id, "agent_k", capability="probe"))


def test_duplicate_embedded_hlp_event_projects_once_for_kimi():
    hlp_event = {"kind": "needs_approval", "agent_id": "agent_k", "prompt": "ship?"}

    async def runner(command, request, timeout):
        body = dict(_ENVELOPE)
        body["correlation_id"] = request["correlation_id"]
        body["hlp"] = hlp_event
        # Same embedded hlp JSON appears twice (e.g. assistant + trailing echo).
        text = json.dumps(body) + "\n" + json.dumps({"hlp": hlp_event})
        line = json.dumps({"role": "assistant", "content": text})
        return ProcessResult(exit_code=0, stdout=line, stderr="")

    adapter = KimiHarnessAdapter(runner=runner)
    client = HLPClient(adapter=adapter)
    task = run(client.create_task(principal="user_a", goal="dedupe"))
    handle = run(client.delegate(task.id, "agent_k", capability="probe"))
    run(client.start(task.id))
    projected = run(client.project_harness_events(handle.run_id))
    assert len(projected) == 1
    assert projected[0].prompt == "ship?"
