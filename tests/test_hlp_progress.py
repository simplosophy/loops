"""Harness progress projection (ephemeral §C.2): codex todo_list and
claude TodoWrite/Task tool blocks become RunProgressSnapshots."""

from __future__ import annotations

import asyncio
import json

from loops.hlp import (
    ClaudeCodeHarnessAdapter,
    CodexHarnessAdapter,
    FakeAgentAdapter,
    HLPClient,
    KimiHarnessAdapter,
    PiHarnessAdapter,
    ProcessResult,
)


def run(coro):
    return asyncio.run(coro)


def _envelope(request):
    return json.dumps(
        {
            "run_id": "run_1",
            "correlation_id": request["correlation_id"],
            "status": "ok",
            "summary": "ack",
        }
    )


def _codex_todo_stdout(request):
    return "\n".join(
        (
            json.dumps({"type": "thread.started", "thread_id": "t1"}),
            json.dumps(
                {
                    "type": "item.started",
                    "item": {
                        "id": "item_1",
                        "type": "todo_list",
                        "items": [
                            {"text": "define cases", "completed": True},
                            {"text": "execute cases", "completed": False},
                            {"text": "write report", "completed": False},
                        ],
                    },
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"id": "item_0", "type": "agent_message", "text": _envelope(request)},
                }
            ),
        )
    )


def _claude_stdout(request):
    return "\n".join(
        (
            json.dumps({"type": "system", "subtype": "init", "session_id": "s1"}),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "id": "call_todo_1",
                                "name": "TodoWrite",
                                "input": {
                                    "todos": [
                                        {"content": "map endpoints", "status": "completed"},
                                        {"content": "write tests", "status": "in_progress"},
                                        {"content": "run suite", "status": "pending"},
                                    ]
                                },
                            },
                            {
                                "type": "tool_use",
                                "id": "call_task_1",
                                "name": "Task",
                                "input": {"description": "scan auth module"},
                            },
                        ],
                    },
                    "parent_tool_use_id": "call_root_0",
                }
            ),
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": _envelope(request),
                    "structured_output": json.loads(_envelope(request)),
                }
            ),
        )
    )


def test_codex_todo_list_projects_progress_snapshot():
    async def runner(command, request, timeout):
        return ProcessResult(exit_code=0, stdout=_codex_todo_stdout(request), stderr="")

    adapter = CodexHarnessAdapter(runner=runner)
    client = HLPClient(adapter=adapter)
    task = run(client.create_task(principal="user_alice", goal="todo probe"))
    handle = run(client.delegate(task.id, "agent_codex", capability="probe", input={"goal": "g"}))

    snapshot = run(client.run_progress(handle.run_id))
    assert snapshot is not None
    assert [(item.label, item.state) for item in snapshot.items] == [
        ("define cases", "done"),
        ("execute cases", "in_progress"),
        ("write report", "pending"),
    ]
    assert snapshot.summary == "execute cases"
    assert snapshot.task_id == task.id


def test_claude_todowrite_and_task_project_items_and_agents():
    async def runner(command, request, timeout):
        return ProcessResult(exit_code=0, stdout=_claude_stdout(request), stderr="")

    adapter = ClaudeCodeHarnessAdapter(runner=runner)
    client = HLPClient(adapter=adapter)
    task = run(client.create_task(principal="user_alice", goal="todo probe"))
    handle = run(client.delegate(task.id, "agent_claude", capability="probe", input={"goal": "g"}))

    snapshot = run(client.run_progress(handle.run_id))
    assert snapshot is not None
    assert [(item.label, item.state) for item in snapshot.items] == [
        ("map endpoints", "done"),
        ("write tests", "in_progress"),
        ("run suite", "pending"),
    ]
    assert len(snapshot.agents) == 1
    assert snapshot.agents[0].state == "running"
    assert snapshot.agents[0].label == "scan auth module"
    assert snapshot.agents[0].parent_id == "call_root_0"


def test_progress_accumulates_across_operations():
    outputs = {
        "delegate": _codex_todo_stdout,
        "resume": lambda request: "\n".join(
            (
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "id": "item_1",
                            "type": "todo_list",
                            "items": [
                                {"text": "define cases", "completed": True},
                                {"text": "execute cases", "completed": True},
                                {"text": "write report", "completed": False},
                            ],
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"id": "item_0", "type": "agent_message", "text": _envelope(request)},
                    }
                ),
            )
        ),
    }

    async def runner(command, request, timeout):
        return ProcessResult(
            exit_code=0,
            stdout=outputs[request["operation"]](request) if request["operation"] in outputs else "{}",
            stderr="",
        )

    adapter = CodexHarnessAdapter(runner=runner)
    client = HLPClient(adapter=adapter)
    task = run(client.create_task(principal="user_alice", goal="accumulate"))
    handle = run(client.delegate(task.id, "agent_codex", capability="probe", input={"goal": "g"}))
    run(client.start(task.id))
    checkpoint = run(
        client.raise_checkpoint(task_id=task.id, kind="approval", prompt="ok?", raised_by="agent_codex")
    )
    run(client.resolve_checkpoint(checkpoint.id, by="user_alice", action="approve"))

    snapshot = run(client.run_progress(handle.run_id))
    assert [(item.label, item.state) for item in snapshot.items] == [
        ("define cases", "done"),
        ("execute cases", "done"),
        ("write report", "in_progress"),
    ]


def test_pi_and_kimi_have_no_progress_source():
    async def runner(command, request, timeout):
        return ProcessResult(
            exit_code=0,
            stdout=json.dumps({"role": "assistant", "content": _envelope(request)}),
            stderr="",
        )

    for adapter in (PiHarnessAdapter(runner=runner), KimiHarnessAdapter(runner=runner)):
        client = HLPClient(adapter=adapter)
        task = run(client.create_task(principal="user_alice", goal="no progress"))
        handle = run(client.delegate(task.id, "agent_x", capability="probe", input={"goal": "g"}))
        assert run(client.run_progress(handle.run_id)) is None


def test_run_progress_facade_returns_none_without_adapter_support():
    client = HLPClient(adapter=FakeAgentAdapter())
    assert run(client.run_progress("run_missing")) is None
