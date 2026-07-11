from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

from loops.hlp import (
    AgentAdapterError,
    ArtifactPayload,
    ClaudeCodeCLIAdapter,
    CheckpointOption,
    CodexCLIAdapter,
    CodexHarnessAdapter,
    CrewAIAdapter,
    FakeAgentAdapter,
    FakeHarnessAdapter,
    HarnessEvent,
    HarnessCapabilities,
    HLPEvent,
    HermesCLIAdapter,
    HermsCLIAdapter,
    HLPClient,
    HLPHost,
    InMemoryEventBus,
    KimiCLIAdapter,
    LangGraphAdapter,
    OpenAIAgentsSDKAdapter,
    OpenAIPythonSDKAdapter,
    PiHarnessAdapter,
    ProcessAgentAdapter,
    PythonCallableAgentAdapter,
    ProcessResult,
    ProtocolError,
    SQLiteHumanLoopStore,
)
from examples.hlp_e2e_demo import run_demo
from examples.hlp_adapter_compat_demo import run_demo as run_adapter_demo
from examples.hlp_codex_harness_demo import run_demo as run_codex_harness_demo
from examples.hlp_harness_wrap_demo import run_demo as run_harness_wrap_demo
from examples.hlp_local_cli_e2e import run_demo as run_local_cli_demo
from examples.hlp_pr_review_desk import (
    PullRequest,
    adapter_error_report,
    build_desk,
    live_codex_command,
    run_desk_demo,
)
from loops.hlp.adapters import AgentAdapterError


def run(coro):
    return asyncio.run(coro)


class PublishOnlyEventBus:
    def __init__(self):
        self.events = []

    async def publish(self, event: HLPEvent) -> None:
        self.events.append(event)


def test_top_level_loops_is_hlp_first_public_surface():
    import loops

    assert loops.HLPClient is HLPClient
    assert loops.HLPHost is HLPHost
    assert "HLPClient" in loops.__all__
    assert "HLPHost" in loops.__all__
    assert "agent" not in loops.__all__
    assert not hasattr(loops, "agent")

    for legacy_alias in ("agent", "providers", "tools", "types"):
        try:
            importlib.import_module(f"loops.{legacy_alias}")
        except ModuleNotFoundError:
            continue
        raise AssertionError(f"loops.{legacy_alias} should not be a public compat alias")


def test_hlp_host_wires_client_adapter_store_and_events():
    adapter = FakeAgentAdapter()
    host = HLPHost.in_memory(adapter=adapter)

    task = run(host.client.create_task(
        principal="user_alice",
        goal="Host HLP work",
    ))
    run_handle = run(host.client.delegate(task.id, "agent_reviewer"))

    assert isinstance(host.client, HLPClient)
    assert adapter.task_of_run(run_handle.run_id) == task.id
    assert [event.action for event in host.events] == [
        "task.created",
        "task.delegated",
    ]


def test_hlp_client_runs_human_loop_without_low_level_operations():
    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)

    task = run(client.create_task(
        principal="user_alice",
        goal="Review PR #1234 for security issues",
        type="code-review",
        acceptance_criteria=("All reviewer comments resolved",),
    ))
    run_handle = run(client.delegate(
        task.id,
        agent_id="agent_coder",
        capability="code-review",
        input={"goal": task.spec.goal, "repository": "web"},
    ))
    run(client.start(task.id))
    checkpoint = run(client.raise_checkpoint(
        task_id=task.id,
        kind="choice",
        prompt="Delete obsolete index?",
        options=(
            CheckpointOption(id="safe", label="Keep risky index", risk="low"),
            CheckpointOption(id="fast", label="Delete all", risk="high"),
        ),
        raised_by="agent_coder",
    ))
    run(client.resolve_checkpoint(
        checkpoint.id,
        by="user_alice",
        action="choose",
        choice="safe",
        comment="Prefer the lower-risk path.",
    ))
    artifact = run(client.commit_artifact(
        task_id=task.id,
        type="report",
        payload=ArtifactPayload(
            kind="inline",
            uri="mem://report-v1",
            checksum="sha256:report-v1",
        ),
        produced_by="agent_coder",
    ))
    review = run(client.submit_review(
        task_id=task.id,
        artifact_id=artifact.id,
        reviewer="user_bob",
        verdict="approved",
    ))
    entry = run(client.write_ledger(
        scope="project:web",
        key="pr.1234.status",
        value="approved",
        by=task.id,
    ))
    history = run(client.replay_audit(task.id))

    assert run_handle.task_id == task.id
    assert run_handle.correlation_id == task.id
    assert adapter.task_of_run(run_handle.run_id) == task.id
    assert adapter.calls[0][1]["capability"] == "code-review"
    assert adapter.calls[0][1]["input"] == {
        "goal": task.spec.goal,
        "repository": "web",
    }
    assert [name for name, _payload in adapter.calls] == [
        "delegate",
        "block",
        "resume",
    ]
    assert review.verdict == "approved"
    assert entry.value == "approved"
    assert [event.action for event in history] == [
        "task.created",
        "task.assigned",
        "task.started",
        "task.checkpoint.raised",
        "task.checkpoint.resolved",
        "artifact.committed",
        "review.submitted",
        "task.completed",
        "ledger.written",
    ]


def test_harness_adapter_projects_human_interaction_events_into_hlp_inbox():
    adapter = FakeHarnessAdapter(capabilities=HarnessCapabilities(
        name="fake-review-harness",
        conformance=("checkpoint-capable", "artifact-aware"),
    ))
    client = HLPClient(adapter=adapter)

    task = run(client.create_task(
        principal="user_alice",
        goal="Wrap an existing code-review harness",
        type="harness-wrap",
    ))
    handle = run(client.delegate(
        task.id,
        "agent_review_harness",
        capability="harness-wrap",
    ))
    run(client.start(task.id))

    adapter.queue_event(handle.run_id, HarnessEvent(
        kind="needs_approval",
        task_id=task.id,
        run_id=handle.run_id,
        agent_id=handle.agent_id,
        prompt="Apply the generated patch?",
    ))
    projected = run(client.project_harness_events(handle.run_id))

    assert projected[0].__class__.__name__ == "Checkpoint"
    inbox = run(client.human_inbox("user_alice"))
    assert [(item.kind, item.action, item.subject_id) for item in inbox] == [
        ("checkpoint", "resolve_checkpoint", projected[0].id),
    ]
    assert inbox[0].title == "Apply the generated patch?"

    run(client.resolve_checkpoint(
        projected[0].id,
        by="user_alice",
        action="approve",
    ))
    adapter.queue_event(handle.run_id, HarnessEvent(
        kind="artifact",
        task_id=task.id,
        run_id=handle.run_id,
        agent_id=handle.agent_id,
        artifact_type="patch",
        artifact_uri="mem://patch-v1",
        artifact_checksum="sha256:patch-v1",
    ))
    projected = run(client.project_harness_events(handle.run_id))

    assert projected[0].__class__.__name__ == "Artifact"
    inbox = run(client.human_inbox("user_alice"))
    assert [(item.kind, item.action, item.subject_id) for item in inbox] == [
        ("review", "submit_review", projected[0].id),
    ]
    assert inbox[0].title == "Review patch v1"


def test_harness_event_projection_rejects_mismatched_task_correlation():
    adapter = FakeHarnessAdapter()
    client = HLPClient(adapter=adapter)

    task = run(client.create_task(
        principal="user_alice",
        goal="Wrap an existing harness",
    ))
    handle = run(client.delegate(task.id, "agent_harness"))
    run(client.start(task.id))

    adapter.queue_event(handle.run_id, HarnessEvent(
        kind="needs_approval",
        task_id="task_other",
        run_id=handle.run_id,
        agent_id=handle.agent_id,
        prompt="This event belongs to a different task.",
    ))

    try:
        run(client.project_harness_events(handle.run_id))
    except ProtocolError as exc:
        assert exc.code == "CONFLICT"
        assert "task correlation" in str(exc)
    else:
        raise AssertionError("expected ProtocolError for mismatched task correlation")


def test_harness_event_projection_peeks_until_successful_ack():
    adapter = FakeHarnessAdapter()
    client = HLPClient(adapter=adapter)

    task = run(client.create_task(
        principal="user_alice",
        goal="Protect event delivery",
    ))
    handle = run(client.delegate(task.id, "agent_harness"))
    run(client.start(task.id))

    adapter.queue_event(handle.run_id, HarnessEvent(
        kind="needs_input",
        task_id="task_other",
        run_id=handle.run_id,
        agent_id=handle.agent_id,
        prompt="This should not be consumed on projection failure.",
    ))

    try:
        run(client.project_harness_events(handle.run_id))
    except ProtocolError as exc:
        assert exc.code == "CONFLICT"
    else:
        raise AssertionError("expected ProtocolError for mismatched task correlation")

    deliveries = run(adapter.peek_events(handle.run_id))
    assert [(delivery.cursor, delivery.event.prompt) for delivery in deliveries] == [
        (
            "evt_000001",
            "This should not be consumed on projection failure.",
        ),
    ]

    run(adapter.ack_events(handle.run_id, through=deliveries[0].cursor))
    adapter.queue_event(handle.run_id, HarnessEvent(
        kind="needs_input",
        task_id=task.id,
        run_id=handle.run_id,
        agent_id=handle.agent_id,
        prompt="Need deployment target.",
    ))

    projected = run(client.project_harness_events(handle.run_id))

    assert projected[0].prompt == "Need deployment target."
    assert run(adapter.peek_events(handle.run_id)) == ()


def test_fake_harness_peek_is_nondestructive_until_ack():
    adapter = FakeHarnessAdapter()
    run_id = run(adapter.delegate(
        task_id="task_delivery",
        agent_id="agent_harness",
        capability="",
        input={"goal": "delivery"},
    ))

    adapter.queue_event(run_id, HarnessEvent(
        kind="needs_approval",
        task_id="task_delivery",
        run_id=run_id,
        agent_id="agent_harness",
        prompt="Approve?",
    ))

    first_peek = run(adapter.peek_events(run_id))
    second_peek = run(adapter.peek_events(run_id))

    assert first_peek == second_peek
    assert [(delivery.cursor, delivery.event.prompt) for delivery in first_peek] == [
        ("evt_000001", "Approve?"),
    ]

    run(adapter.ack_events(run_id, through=first_peek[0].cursor))

    assert run(adapter.peek_events(run_id)) == ()


def test_project_harness_events_acks_only_successful_prefix():
    adapter = FakeHarnessAdapter()
    client = HLPClient(adapter=adapter)

    task = run(client.create_task(
        principal="user_alice",
        goal="Project prefix",
    ))
    handle = run(client.delegate(task.id, "agent_harness"))
    run(client.start(task.id))

    adapter.queue_event(handle.run_id, HarnessEvent(
        kind="needs_input",
        task_id=task.id,
        run_id=handle.run_id,
        agent_id=handle.agent_id,
        prompt="Need region.",
    ))
    adapter.queue_event(handle.run_id, HarnessEvent(
        kind="needs_input",
        task_id="task_other",
        run_id=handle.run_id,
        agent_id=handle.agent_id,
        prompt="This event should remain queued.",
    ))

    try:
        run(client.project_harness_events(handle.run_id))
    except ProtocolError as exc:
        assert exc.code == "CONFLICT"
    else:
        raise AssertionError("expected ProtocolError for mismatched task correlation")

    deliveries = run(adapter.peek_events(handle.run_id))
    assert [(delivery.cursor, delivery.event.prompt) for delivery in deliveries] == [
        ("evt_000002", "This event should remain queued."),
    ]


def test_codex_harness_peek_ack_replays_until_ack():
    async def runner(command, request, timeout):
        return ProcessResult(
            exit_code=0,
            stdout="\n".join((
                json.dumps({
                    "type": "hlp.event",
                    "run_id": "codex_run_delivery",
                    "correlation_id": request["correlation_id"],
                    "hlp": {
                        "kind": "needs_input",
                        "agent_id": request["agent_id"],
                        "prompt": "Need target branch.",
                    },
                }),
                json.dumps({
                    "type": "turn.completed",
                    "run_id": "codex_run_delivery",
                    "correlation_id": request["correlation_id"],
                    "status": "ok",
                }),
            )),
            stderr="",
        )

    adapter = CodexHarnessAdapter(
        command=("codex", "exec", "--json"),
        runner=runner,
    )

    run_id = run(adapter.delegate(
        task_id="task_codex_delivery",
        agent_id="agent_codex",
        capability="event-delivery",
        input={"goal": "delivery"},
    ))
    first_peek = run(adapter.peek_events(run_id))
    second_peek = run(adapter.peek_events(run_id))

    assert [(delivery.cursor, delivery.event.prompt) for delivery in first_peek] == [
        ("evt_000001", "Need target branch."),
    ]
    assert second_peek == first_peek

    run(adapter.ack_events(run_id, through=first_peek[0].cursor))

    assert run(adapter.peek_events(run_id)) == ()
    assert adapter._codex_events == {}


class LegacyObserveHarness(FakeAgentAdapter):
    def __init__(self):
        super().__init__()
        self._events = {}

    def queue_event(self, run_id, event):
        self._require_run(run_id, "queue_event")
        self._events.setdefault(run_id, []).append(event)

    async def observe(self, run_id):
        self._require_run(run_id, "observe")
        return tuple(self._events.pop(run_id, ()))


def test_legacy_observe_adapter_still_projects_without_peek_ack():
    adapter = LegacyObserveHarness()
    client = HLPClient(adapter=adapter)

    task = run(client.create_task(
        principal="user_alice",
        goal="Legacy observe",
    ))
    handle = run(client.delegate(task.id, "agent_legacy"))
    run(client.start(task.id))
    adapter.queue_event(handle.run_id, HarnessEvent(
        kind="needs_approval",
        task_id=task.id,
        run_id=handle.run_id,
        agent_id=handle.agent_id,
        prompt="Approve legacy event?",
    ))

    projected = run(client.project_harness_events(handle.run_id))

    assert projected[0].prompt == "Approve legacy event?"
    assert not hasattr(adapter, "peek_events")


def test_harness_event_projection_does_not_ack_run_correlation_failure():
    adapter = FakeHarnessAdapter()
    client = HLPClient(adapter=adapter)

    task = run(client.create_task(
        principal="user_alice",
        goal="Protect run correlation",
    ))
    handle = run(client.delegate(task.id, "agent_harness"))
    run(client.start(task.id))

    adapter.queue_event(handle.run_id, HarnessEvent(
        kind="needs_input",
        task_id=task.id,
        run_id="run_other",
        agent_id=handle.agent_id,
        prompt="This run mismatch should remain queued.",
    ))

    try:
        run(client.project_harness_events(handle.run_id))
    except ProtocolError as exc:
        assert exc.code == "CONFLICT"
    else:
        raise AssertionError("expected ProtocolError for mismatched run correlation")

    assert [delivery.event.prompt for delivery in run(adapter.peek_events(handle.run_id))] == [
        "This run mismatch should remain queued.",
    ]


def test_fake_agent_adapter_records_contract_calls():
    adapter = FakeAgentAdapter()

    delegate = run(adapter.delegate(
        task_id="task_123",
        agent_id="agent_reviewer",
        capability="code-review",
        input={"goal": "review"},
    ))
    run(adapter.block(delegate, "ckpt_123", "Need approval"))
    run(adapter.resume(delegate, {"action": "approve"}))
    handoff = run(adapter.handoff(delegate, "agent_writer", {"reason": "rewrite"}))
    run(adapter.cancel(handoff, "demo done"))
    health = run(adapter.healthcheck())

    assert adapter.task_of_run(delegate) == "task_123"
    assert adapter.task_of_run(handoff) == "task_123"
    assert health == {
        "status": "ok",
        "adapter": "fake",
        "runs": 2,
    }
    assert [name for name, _payload in adapter.calls] == [
        "delegate",
        "block",
        "resume",
        "handoff",
        "cancel",
        "healthcheck",
    ]


def test_named_adapter_targets_are_available_without_optional_dependencies():
    captured_python_request = {}

    async def handler(request):
        captured_python_request.update(request)
        return {"handled": request["task_id"], "agent": request["agent_id"]}

    python_adapter = PythonCallableAgentAdapter("custom-python", handler)
    openai_agents = OpenAIAgentsSDKAdapter(handler)
    openai_python = OpenAIPythonSDKAdapter(handler)
    langgraph = LangGraphAdapter(handler)
    crewai = CrewAIAdapter(handler)
    codex = CodexCLIAdapter(command=("codex", "exec"))
    codex_harness = CodexHarnessAdapter(command=("codex", "exec", "--json"))
    pi_harness = PiHarnessAdapter()
    claude = ClaudeCodeCLIAdapter(command=("claude", "-p"))
    kimi = KimiCLIAdapter(command=("kimi", "-p"))
    herms = HermsCLIAdapter(command=("herms", "run"))

    run_id = run(python_adapter.delegate(
        task_id="task_custom",
        agent_id="agent_custom",
        capability="demo",
        input={"goal": "demo"},
    ))
    assert python_adapter.results[run_id] == {
        "handled": "task_custom",
        "agent": "agent_custom",
    }
    assert "operation_context" not in captured_python_request

    assert run(openai_agents.healthcheck())["adapter"] == "openai-agents-sdk"
    assert run(openai_python.healthcheck())["adapter"] == "openai-python-sdk"
    assert run(langgraph.healthcheck())["adapter"] == "langgraph"
    assert run(crewai.healthcheck())["adapter"] == "crewai"
    assert run(codex.healthcheck())["command"] == ("codex", "exec")
    assert run(codex_harness.healthcheck())["adapter"] == "codex-harness"
    assert codex_harness.harness_capabilities().conformance == (
        "checkpoint-capable",
        "artifact-aware",
        "event-streaming",
    )
    assert run(pi_harness.healthcheck())["adapter"] == "pi-harness"
    assert pi_harness.harness_capabilities().conformance == (
        "checkpoint-capable",
        "artifact-aware",
        "event-streaming",
    )
    assert run(claude.healthcheck())["adapter"] == "claude-code-cli"
    assert run(kimi.healthcheck())["adapter"] == "kimi-cli"
    assert HermesCLIAdapter is HermsCLIAdapter
    assert run(herms.healthcheck())["adapter"] == "herms-cli"


def test_process_agent_adapter_executes_json_runner_contract():
    captured = {}

    async def runner(command, request, timeout):
        captured["command"] = command
        captured["request"] = request
        captured["timeout"] = timeout
        return ProcessResult(
            exit_code=0,
            stdout='{"run_id": "external_run_1", "metadata": {"provider": "codex"}}',
            stderr="",
        )

    adapter = ProcessAgentAdapter(
        command=("codex", "exec", "--json"),
        name="codex-json-process",
        runner=runner,
        timeout=12.5,
    )

    run_id = run(adapter.delegate(
        task_id="task_proc",
        agent_id="agent_codex",
        capability="code-review",
        input={"goal": "review"},
    ))
    health = run(adapter.healthcheck())

    assert run_id == "external_run_1"
    assert adapter.task_of_run(run_id) == "task_proc"
    assert adapter.process_results[run_id] == {
        "run_id": "external_run_1",
        "metadata": {"provider": "codex"},
    }
    assert captured == {
        "command": ("codex", "exec", "--json"),
        "request": {
            "operation": "delegate",
            "task_id": "task_proc",
            "agent_id": "agent_codex",
            "capability": "code-review",
            "input": {"goal": "review"},
            "parent_run": None,
            "correlation_id": "task_proc",
        },
        "timeout": 12.5,
    }
    assert health["adapter"] == "codex-json-process"
    assert health["executable"] == "codex"


def test_process_agent_adapter_accepts_jsonl_event_stream_stdout():
    async def runner(command, request, timeout):
        return ProcessResult(
            exit_code=0,
            stdout=(
                '{"type":"thread.started","id":"thread_1"}\n'
                '{"type":"turn.completed","run_id":"codex_run_1","correlation_id":"task_proc"}\n'
            ),
            stderr="",
        )

    adapter = CodexCLIAdapter(command=("codex", "exec", "--json"), runner=runner)

    run_id = run(adapter.delegate(
        task_id="task_proc",
        agent_id="agent_codex",
        capability="code-review",
        input={"goal": "review"},
    ))

    assert run_id == "codex_run_1"
    assert adapter.process_results[run_id]["type"] == "turn.completed"


def test_codex_harness_adapter_projects_jsonl_events_into_hlp():
    requests = []

    async def runner(command, request, timeout):
        requests.append({"command": command, "request": request, "timeout": timeout})
        if request["operation"] == "delegate":
            return ProcessResult(
                exit_code=0,
                stdout="\n".join((
                    json.dumps({"type": "session.started", "session_id": "codex_session_1"}),
                    json.dumps({
                        "type": "hlp.event",
                        "run_id": "codex_run_1",
                        "correlation_id": request["correlation_id"],
                        "hlp": {
                            "kind": "needs_approval",
                            "agent_id": "agent_codex",
                            "prompt": "Apply the Codex patch?",
                        },
                    }),
                    json.dumps({
                        "type": "turn.completed",
                        "run_id": "codex_run_1",
                        "correlation_id": request["correlation_id"],
                        "status": "ok",
                    }),
                )),
                stderr="",
            )
        if request["operation"] == "resume":
            return ProcessResult(
                exit_code=0,
                stdout="\n".join((
                    json.dumps({
                        "type": "hlp.event",
                        "run_id": "codex_run_1",
                        "correlation_id": request["correlation_id"],
                        "hlp": {
                            "kind": "artifact",
                            "agent_id": "agent_codex",
                            "artifact_type": "patch",
                            "artifact_uri": "mem://codex.patch",
                            "artifact_checksum": "sha256:codex.patch",
                            "artifact_size": 42,
                        },
                    }),
                    json.dumps({
                        "type": "turn.completed",
                        "run_id": "codex_run_1",
                        "correlation_id": request["correlation_id"],
                        "status": "ok",
                    }),
                )),
                stderr="",
            )
        return ProcessResult(exit_code=0, stdout="{}", stderr="")

    adapter = CodexHarnessAdapter(
        command=("codex", "exec", "--json"),
        runner=runner,
        timeout=8.0,
    )
    client = HLPClient(adapter=adapter)

    task = run(client.create_task(
        principal="user_alice",
        goal="Review a Codex generated patch",
        type="codex-harness",
    ))
    handle = run(client.delegate(
        task.id,
        "agent_codex",
        capability="code-edit",
        input={"goal": task.spec.goal},
    ))
    run(client.start(task.id))

    checkpoint = run(client.project_harness_events(handle.run_id))[0]
    inbox = run(client.human_inbox("user_alice"))

    assert handle.run_id == "codex_run_1"
    assert handle.correlation_id == task.id
    assert checkpoint.prompt == "Apply the Codex patch?"
    assert [(item.kind, item.action, item.subject_id) for item in inbox] == [
        ("checkpoint", "resolve_checkpoint", checkpoint.id),
    ]
    assert requests[0]["command"][:3] == ("codex", "exec", "--json")
    assert requests[0]["command"][-1].startswith("You are executing an HLP adapter operation.")
    assert requests[0]["timeout"] == 8.0

    run(client.resolve_checkpoint(checkpoint.id, by="user_alice", action="approve"))
    artifact = run(client.project_harness_events(handle.run_id))[0]
    inbox = run(client.human_inbox("user_alice"))

    assert artifact.type == "patch"
    assert artifact.payload.uri == "mem://codex.patch"
    assert artifact.payload.checksum == "sha256:codex.patch"
    assert artifact.payload.size == 42
    assert [(item.kind, item.action, item.subject_id) for item in inbox] == [
        ("review", "submit_review", artifact.id),
    ]
    assert [entry["request"]["operation"] for entry in requests] == [
        "delegate",
        "block",
        "resume",
    ]


def test_pi_harness_adapter_projects_pi_jsonl_events_into_hlp():
    requests = []

    async def runner(command, request, timeout):
        requests.append({"command": command, "request": request, "timeout": timeout})
        if request["operation"] == "delegate":
            return ProcessResult(
                exit_code=0,
                stdout="\n".join((
                    json.dumps({
                        "type": "pi.event",
                        "run_id": "pi_run_1",
                        "correlation_id": request["correlation_id"],
                        "pi": {
                            "kind": "needs_approval",
                            "agent_id": "agent_pi",
                            "prompt": "Apply the Pi patch?",
                        },
                    }),
                    json.dumps({
                        "type": "turn.completed",
                        "run_id": "pi_run_1",
                        "correlation_id": request["correlation_id"],
                        "status": "ok",
                    }),
                )),
                stderr="",
            )
        if request["operation"] == "resume":
            return ProcessResult(
                exit_code=0,
                stdout="\n".join((
                    json.dumps({
                        "type": "pi.event",
                        "run_id": "pi_run_1",
                        "correlation_id": request["correlation_id"],
                        "pi": {
                            "kind": "artifact",
                            "agent_id": "agent_pi",
                            "artifact_type": "patch",
                            "artifact_uri": "mem://pi.patch",
                            "artifact_checksum": "sha256:pi.patch",
                            "artifact_size": 7,
                        },
                    }),
                    json.dumps({
                        "type": "turn.completed",
                        "run_id": "pi_run_1",
                        "correlation_id": request["correlation_id"],
                        "status": "ok",
                    }),
                )),
                stderr="",
            )
        return ProcessResult(exit_code=0, stdout="{}", stderr="")

    adapter = PiHarnessAdapter(
        runner=runner,
        timeout=9.0,
    )
    client = HLPClient(adapter=adapter)

    task = run(client.create_task(
        principal="user_alice",
        goal="Review a Pi generated patch",
        type="pi-harness",
    ))
    handle = run(client.delegate(
        task.id,
        "agent_pi",
        capability="code-edit",
        input={"goal": task.spec.goal},
    ))
    run(client.start(task.id))

    checkpoint = run(client.project_harness_events(handle.run_id))[0]
    inbox = run(client.human_inbox("user_alice"))

    assert handle.run_id == "pi_run_1"
    assert checkpoint.prompt == "Apply the Pi patch?"
    assert [(item.kind, item.action, item.subject_id) for item in inbox] == [
        ("checkpoint", "resolve_checkpoint", checkpoint.id),
    ]
    assert requests[0]["command"][:5] == ("pi", "--mode", "json", "-p", "--no-session")
    assert requests[0]["command"][-1].startswith("You are executing an HLP adapter operation.")
    assert requests[0]["timeout"] == 9.0

    run(client.resolve_checkpoint(checkpoint.id, by="user_alice", action="approve"))
    artifact = run(client.project_harness_events(handle.run_id))[0]
    inbox = run(client.human_inbox("user_alice"))

    assert artifact.type == "patch"
    assert artifact.payload.uri == "mem://pi.patch"
    assert artifact.payload.checksum == "sha256:pi.patch"
    assert artifact.payload.size == 7
    assert [(item.kind, item.action, item.subject_id) for item in inbox] == [
        ("review", "submit_review", artifact.id),
    ]
    assert [entry["request"]["operation"] for entry in requests] == [
        "delegate",
        "block",
        "resume",
    ]


def test_pi_harness_adapter_rejects_mismatched_event_correlation():
    async def runner(command, request, timeout):
        return ProcessResult(
            exit_code=0,
            stdout=json.dumps({
                "type": "pi.event",
                "run_id": "pi_run_1",
                "correlation_id": "task_other",
                "pi": {
                    "kind": "needs_input",
                    "agent_id": "agent_pi",
                    "prompt": "Need context",
                },
            }),
            stderr="",
        )

    adapter = PiHarnessAdapter(runner=runner)

    try:
        run(adapter.delegate(
            task_id="task_pi",
            agent_id="agent_pi",
            capability="code-edit",
            input={"goal": "edit"},
        ))
    except AgentAdapterError as exc:
        assert exc.adapter == "pi-harness"
        assert exc.operation == "delegate"
        assert "correlation" in str(exc)
        assert exc.details == {"expected": "task_pi", "actual": "task_other"}
    else:
        raise AssertionError("expected AgentAdapterError")


def test_codex_harness_adapter_projects_real_agent_message_jsonl_shape():
    async def runner(command, request, timeout):
        return ProcessResult(
            exit_code=0,
            stdout="\n".join((
                json.dumps({
                    "type": "thread.started",
                    "thread_id": "019efd48-85a1-7501-bc61-da75d1e60a79",
                }),
                json.dumps({"type": "turn.started"}),
                json.dumps({
                    "type": "item.completed",
                    "item": {
                        "id": "item_0",
                        "type": "agent_message",
                        "text": json.dumps({
                            "run_id": "real_codex_run_1",
                            "correlation_id": request["correlation_id"],
                            "status": "ok",
                            "summary": "actual codex json probe",
                            "hlp": {
                                "kind": "needs_approval",
                                "agent_id": "agent_codex",
                                "prompt": "Approve actual Codex harness projection?",
                            },
                        }),
                    },
                }),
                json.dumps({
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 16814,
                        "cached_input_tokens": 2432,
                        "output_tokens": 120,
                        "reasoning_output_tokens": 57,
                    },
                }),
            )),
            stderr="",
        )

    adapter = CodexHarnessAdapter(
        command=("codex", "exec", "--json"),
        runner=runner,
    )

    run_id = run(adapter.delegate(
        task_id="task_real_probe",
        agent_id="agent_codex",
        capability="real-codex-harness",
        input={"goal": "probe"},
    ))
    events = run(adapter.observe(run_id))

    assert run_id == "real_codex_run_1"
    assert adapter.process_results[run_id]["summary"] == "actual codex json probe"
    assert [(event.kind, event.prompt, event.task_id) for event in events] == [
        (
            "needs_approval",
            "Approve actual Codex harness projection?",
            "task_real_probe",
        ),
    ]


def test_codex_harness_adapter_rejects_mismatched_event_correlation():
    async def runner(command, request, timeout):
        return ProcessResult(
            exit_code=0,
            stdout=(
                '{"type":"hlp.event","run_id":"codex_run_1","correlation_id":"task_other",'
                '"hlp":{"kind":"needs_input","agent_id":"agent_codex",'
                '"prompt":"Need more context"}}\n'
                '{"type":"turn.completed","run_id":"codex_run_1","status":"ok"}\n'
            ),
            stderr="",
        )

    adapter = CodexHarnessAdapter(
        command=("codex", "exec", "--json"),
        runner=runner,
    )

    try:
        run(adapter.delegate(
            task_id="task_codex",
            agent_id="agent_codex",
            capability="code-edit",
            input={"goal": "edit"},
        ))
    except AgentAdapterError as exc:
        assert exc.adapter == "codex-harness"
        assert exc.operation == "delegate"
        assert "correlation" in str(exc)
        assert exc.details == {"expected": "task_codex", "actual": "task_other"}
    else:
        raise AssertionError("expected AgentAdapterError")


def test_kimi_cli_adapter_executes_one_shot_prompt_and_extracts_json():
    captured = {}

    async def runner(command, request, timeout):
        captured["command"] = command
        captured["request"] = request
        captured["timeout"] = timeout
        return ProcessResult(
            exit_code=0,
            stdout=(
                "Kimi completed the task.\n"
                '{"run_id": "kimi_run_1", "correlation_id": "task_kimi", "status": "ok"}\n'
            ),
            stderr="",
        )

    adapter = KimiCLIAdapter(command=("kimi", "-p"), runner=runner, timeout=9.0)

    run_id = run(adapter.delegate(
        task_id="task_kimi",
        agent_id="agent_kimi",
        capability="local-cli-smoke",
        input={"goal": "Confirm HLP adapter compatibility"},
    ))

    assert run_id == "kimi_run_1"
    assert adapter.task_of_run(run_id) == "task_kimi"
    assert adapter.process_results[run_id]["status"] == "ok"
    assert captured["command"][:2] == ("kimi", "-p")
    assert captured["command"][-1].startswith("You are executing an HLP adapter operation.")
    assert '"operation": "delegate"' in captured["command"][-1]
    assert '"correlation_id": "task_kimi"' in captured["command"][-1]
    assert captured["request"]["correlation_id"] == "task_kimi"
    assert captured["timeout"] == 9.0


def test_claude_cli_adapter_extracts_json_from_result_field():
    async def runner(command, request, timeout):
        return ProcessResult(
            exit_code=0,
            stdout=json.dumps({
                "type": "result",
                "result": (
                    "Here is the HLP result:\n"
                    '{"run_id": "claude_run_1", "correlation_id": "task_claude", "status": "ok"}'
                ),
            }),
            stderr="",
        )

    adapter = ClaudeCodeCLIAdapter(
        command=("claude", "-p", "--output-format", "json"),
        runner=runner,
    )

    run_id = run(adapter.delegate(
        task_id="task_claude",
        agent_id="agent_claude",
        capability="local-cli-smoke",
        input={"goal": "Confirm HLP adapter compatibility"},
    ))

    assert run_id == "claude_run_1"
    assert adapter.process_results[run_id]["status"] == "ok"


def test_process_agent_adapter_rejects_mismatched_correlation_id():
    async def runner(command, request, timeout):
        return ProcessResult(
            exit_code=0,
            stdout='{"run_id": "external_run_1", "correlation_id": "task_other"}',
            stderr="",
        )

    adapter = CodexCLIAdapter(command=("codex", "exec", "--json"), runner=runner)

    try:
        run(adapter.delegate(
            task_id="task_proc",
            agent_id="agent_codex",
            capability="code-review",
            input={"goal": "review"},
        ))
    except AgentAdapterError as exc:
        assert exc.operation == "delegate"
        assert "correlation" in str(exc)
    else:
        raise AssertionError("expected AgentAdapterError")


def test_process_agent_adapter_requires_delegate_run_id():
    async def runner(command, request, timeout):
        return ProcessResult(exit_code=0, stdout="{}", stderr="")

    adapter = ProcessAgentAdapter(
        command=("agent", "run", "--json"),
        name="strict-process",
        runner=runner,
    )

    try:
        run(adapter.delegate(
            task_id="task_proc",
            agent_id="agent_proc",
            capability="code-review",
            input={"goal": "review"},
        ))
    except AgentAdapterError as exc:
        assert exc.operation == "delegate"
        assert "run_id" in str(exc)
    else:
        raise AssertionError("expected AgentAdapterError")


def test_process_agent_adapter_wraps_unknown_run_for_resume():
    async def runner(command, request, timeout):
        return ProcessResult(exit_code=0, stdout="{}", stderr="")

    adapter = CodexCLIAdapter(command=("codex", "exec", "--json"), runner=runner)

    try:
        run(adapter.resume("missing_run", {"action": "approve"}))
    except AgentAdapterError as exc:
        assert exc.operation == "resume"
        assert exc.details["run_id"] == "missing_run"
    else:
        raise AssertionError("expected AgentAdapterError")


def test_process_agent_adapter_raises_structured_error_on_failure():
    async def runner(command, request, timeout):
        return ProcessResult(exit_code=2, stdout="", stderr="boom")

    adapter = ClaudeCodeCLIAdapter(command=("claude", "-p"), runner=runner)

    try:
        run(adapter.delegate(
            task_id="task_proc",
            agent_id="agent_claude",
            capability="code-review",
            input={"goal": "review"},
        ))
    except AgentAdapterError as exc:
        assert exc.adapter == "claude-code-cli"
        assert exc.operation == "delegate"
        assert exc.details["exit_code"] == 2
        assert exc.details["stderr"] == "boom"
    else:
        raise AssertionError("expected AgentAdapterError")


def test_process_agent_adapter_wraps_runner_exception():
    async def runner(command, request, timeout):
        raise FileNotFoundError("missing cli")

    adapter = CodexCLIAdapter(command=("missing-codex",), runner=runner)

    try:
        run(adapter.delegate(
            task_id="task_proc",
            agent_id="agent_codex",
            capability="code-review",
            input={"goal": "review"},
        ))
    except AgentAdapterError as exc:
        assert exc.adapter == "codex-cli"
        assert exc.operation == "delegate"
        assert exc.details["error_type"] == "FileNotFoundError"
        assert "missing cli" in exc.details["error"]
    else:
        raise AssertionError("expected AgentAdapterError")


def test_openai_python_sdk_adapter_uses_responses_client():
    class FakeResponses:
        def __init__(self):
            self.requests = []

        async def create(self, **kwargs):
            self.requests.append(kwargs)
            return {
                "id": "resp_123",
                "output_text": "review completed",
            }

    class FakeClient:
        def __init__(self):
            self.responses = FakeResponses()

    client = FakeClient()
    adapter = OpenAIPythonSDKAdapter(client=client, model="gpt-test")

    run_id = run(adapter.delegate(
        task_id="task_openai",
        agent_id="agent_openai",
        capability="analysis",
        input={"goal": "summarize"},
    ))

    assert run_id == "resp_123"
    assert adapter.task_of_run(run_id) == "task_openai"
    assert adapter.results[run_id] == {
        "id": "resp_123",
        "output_text": "review completed",
    }
    assert client.responses.requests == [{
        "model": "gpt-test",
        "input": "summarize",
        "metadata": {
            "hlp_task_id": "task_openai",
            "hlp_agent_id": "agent_openai",
            "hlp_capability": "analysis",
            "hlp_parent_run": "",
        },
    }]


def test_openai_python_sdk_adapter_preserves_context_when_goal_has_siblings():
    class FakeResponses:
        def __init__(self):
            self.requests = []

        async def create(self, **kwargs):
            self.requests.append(kwargs)
            return {"id": "resp_123"}

    class FakeClient:
        def __init__(self):
            self.responses = FakeResponses()

    client = FakeClient()
    adapter = OpenAIPythonSDKAdapter(client=client, model="gpt-test")

    run(adapter.delegate(
        task_id="task_openai",
        agent_id="agent_openai",
        capability="analysis",
        input={"goal": "summarize", "repository": "web"},
    ))

    assert json.loads(client.responses.requests[0]["input"]) == {
        "goal": "summarize",
        "repository": "web",
    }


def test_openai_python_sdk_adapter_wraps_client_exception():
    class BrokenResponses:
        async def create(self, **kwargs):
            raise RuntimeError("api unavailable")

    class BrokenClient:
        responses = BrokenResponses()

    adapter = OpenAIPythonSDKAdapter(client=BrokenClient(), model="gpt-test")

    try:
        run(adapter.delegate(
            task_id="task_openai",
            agent_id="agent_openai",
            capability="analysis",
            input={"goal": "summarize"},
        ))
    except AgentAdapterError as exc:
        assert exc.adapter == "openai-python-sdk"
        assert exc.operation == "delegate"
        assert exc.details["error_type"] == "RuntimeError"
        assert exc.details["error"] == "api unavailable"
    else:
        raise AssertionError("expected AgentAdapterError")


def test_openai_agents_sdk_adapter_uses_runner_contract():
    class FakeRunner:
        def __init__(self):
            self.calls = []

        def run_sync(self, agent, input, run_config=None):
            self.calls.append({
                "agent": agent,
                "input": input,
                "run_config": run_config,
            })
            return {
                "id": "agents_run_123",
                "final_output": "agents done",
            }

    runner = FakeRunner()
    adapter = OpenAIAgentsSDKAdapter(
        agent="agent-object",
        runner=runner,
        run_config={"trace": "hlp"},
    )

    run_id = run(adapter.delegate(
        task_id="task_agents",
        agent_id="agent_openai_agents",
        capability="multi-agent",
        input={"goal": "coordinate work"},
    ))

    assert run_id == "agents_run_123"
    assert adapter.task_of_run(run_id) == "task_agents"
    assert adapter.results[run_id] == {
        "id": "agents_run_123",
        "final_output": "agents done",
    }
    assert runner.calls == [{
        "agent": "agent-object",
        "input": "coordinate work",
        "run_config": {"trace": "hlp"},
    }]


def test_openai_agents_sdk_adapter_wraps_runner_exception():
    class BrokenRunner:
        def run_sync(self, agent, input, run_config=None):
            raise RuntimeError("agents failed")

    adapter = OpenAIAgentsSDKAdapter(agent="agent-object", runner=BrokenRunner())

    try:
        run(adapter.delegate(
            task_id="task_agents",
            agent_id="agent_openai_agents",
            capability="multi-agent",
            input={"goal": "coordinate work"},
        ))
    except AgentAdapterError as exc:
        assert exc.adapter == "openai-agents-sdk"
        assert exc.operation == "delegate"
        assert exc.details["error_type"] == "RuntimeError"
        assert exc.details["error"] == "agents failed"
    else:
        raise AssertionError("expected AgentAdapterError")


def test_langgraph_adapter_invokes_compiled_graph():
    class FakeGraph:
        def __init__(self):
            self.calls = []

        async def ainvoke(self, input, config=None):
            self.calls.append({"input": input, "config": config})
            return {"messages": ["done"], "run_id": "graph_run_123"}

    graph = FakeGraph()
    adapter = LangGraphAdapter(graph=graph, config={"thread_id": "thread-1"})

    run_id = run(adapter.delegate(
        task_id="task_graph",
        agent_id="agent_langgraph",
        capability="workflow",
        input={"goal": "run graph", "state": {"foo": "bar"}},
    ))

    assert run_id == "graph_run_123"
    assert adapter.task_of_run(run_id) == "task_graph"
    assert adapter.results[run_id] == {"messages": ["done"], "run_id": "graph_run_123"}
    assert graph.calls == [{
        "input": {
            "messages": [{
                "role": "user",
                "content": '{"goal": "run graph", "state": {"foo": "bar"}}',
            }],
            "hlp": {
                "task_id": "task_graph",
                "agent_id": "agent_langgraph",
                "capability": "workflow",
                "parent_run": None,
            },
            "state": {"foo": "bar"},
        },
        "config": {
            "configurable": {"thread_id": "thread-1"},
            "metadata": {
                "hlp_task_id": "task_graph",
                "hlp_agent_id": "agent_langgraph",
                "hlp_capability": "workflow",
                "hlp_parent_run": "",
            },
        },
    }]


def test_langgraph_adapter_wraps_graph_exception():
    class BrokenGraph:
        async def ainvoke(self, input, config=None):
            raise RuntimeError("graph failed")

    adapter = LangGraphAdapter(graph=BrokenGraph())

    try:
        run(adapter.delegate(
            task_id="task_graph",
            agent_id="agent_langgraph",
            capability="workflow",
            input={"goal": "run graph"},
        ))
    except AgentAdapterError as exc:
        assert exc.adapter == "langgraph"
        assert exc.operation == "delegate"
        assert exc.details["error_type"] == "RuntimeError"
        assert exc.details["error"] == "graph failed"
    else:
        raise AssertionError("expected AgentAdapterError")


def test_crewai_adapter_uses_async_kickoff_contract():
    class FakeCrew:
        def __init__(self):
            self.calls = []

        async def akickoff(self, inputs):
            self.calls.append(inputs)
            return {"id": "crew_run_123", "raw": "crew done"}

    crew = FakeCrew()
    adapter = CrewAIAdapter(crew=crew)

    run_id = run(adapter.delegate(
        task_id="task_crew",
        agent_id="agent_crewai",
        capability="crew",
        input={"goal": "research topic", "topic": "HLP"},
    ))

    assert run_id == "crew_run_123"
    assert adapter.task_of_run(run_id) == "task_crew"
    assert adapter.results[run_id] == {"id": "crew_run_123", "raw": "crew done"}
    assert crew.calls == [{
        "goal": "research topic",
        "topic": "HLP",
        "hlp_task_id": "task_crew",
        "hlp_agent_id": "agent_crewai",
        "hlp_capability": "crew",
        "hlp_parent_run": "",
    }]


def test_crewai_adapter_wraps_crew_exception():
    class BrokenCrew:
        async def akickoff(self, inputs):
            raise RuntimeError("crew failed")

    adapter = CrewAIAdapter(crew=BrokenCrew())

    try:
        run(adapter.delegate(
            task_id="task_crew",
            agent_id="agent_crewai",
            capability="crew",
            input={"goal": "research topic"},
        ))
    except AgentAdapterError as exc:
        assert exc.adapter == "crewai"
        assert exc.operation == "delegate"
        assert exc.details["error_type"] == "RuntimeError"
        assert exc.details["error"] == "crew failed"
    else:
        raise AssertionError("expected AgentAdapterError")


def test_hlp_client_drives_process_adapter_block_and_resume():
    requests = []

    async def runner(command, request, timeout):
        requests.append(request)
        if request["operation"] == "delegate":
            return ProcessResult(exit_code=0, stdout='{"run_id": "proc_run_1"}', stderr="")
        return ProcessResult(exit_code=0, stdout="{}", stderr="")

    adapter = CodexCLIAdapter(command=("codex", "exec", "--json"), runner=runner)
    client = HLPClient(adapter=adapter)

    task = run(client.create_task(principal="user_alice", goal="Use Codex adapter"))
    run_handle = run(client.delegate(task.id, "agent_codex", capability="code-review"))
    run(client.start(task.id))
    checkpoint = run(client.raise_checkpoint(
        task_id=task.id,
        kind="approval",
        prompt="Apply patch?",
        raised_by="agent_codex",
    ))
    run(client.resolve_checkpoint(checkpoint.id, by="user_alice", action="approve"))

    assert run_handle.run_id == "proc_run_1"
    assert [request["operation"] for request in requests] == [
        "delegate",
        "block",
        "resume",
    ]
    assert requests[1]["checkpoint_id"] == checkpoint.id
    assert requests[2]["resolution"] == {
        "by": "user_alice",
        "action": "approve",
        "choice": None,
        "input": None,
        "reassign_to": None,
        "approved_actions": (),
        "denied_actions": (),
        "state_patch": None,
        "edited_artifact_ref": None,
        "comment": None,
    }


def test_hlp_client_emits_lifecycle_events_in_order():
    bus = InMemoryEventBus()
    client = HLPClient(adapter=FakeAgentAdapter(), event_bus=bus)

    task = run(client.create_task(principal="user_alice", goal="Ship release notes"))
    run_handle = run(client.delegate(task.id, "agent_writer"))
    run(client.start(task.id))
    checkpoint = run(client.raise_checkpoint(
        task_id=task.id,
        kind="approval",
        prompt="Publish draft?",
        raised_by="agent_writer",
    ))
    run(client.resolve_checkpoint(checkpoint.id, by="user_alice", action="approve"))
    artifact = run(client.commit_artifact(
        task_id=task.id,
        type="release-notes",
        payload=ArtifactPayload(
            kind="inline",
            uri="mem://release-notes-v1",
            checksum="sha256:release-notes-v1",
        ),
        produced_by="agent_writer",
    ))
    run(client.submit_review(
        task_id=task.id,
        artifact_id=artifact.id,
        reviewer="user_alice",
        verdict="approved",
    ))
    run(client.write_ledger("project:demo", "release.status", "approved", by=task.id))
    run(client.replay_audit(task.id))

    assert run_handle.run_id
    assert [event.action for event in bus.events] == [
        "task.created",
        "task.delegated",
        "task.started",
        "checkpoint.raised",
        "checkpoint.resolved",
        "artifact.committed",
        "review.submitted",
        "ledger.written",
        "audit.replayed",
    ]
    assert all(event.task_id == task.id for event in bus.events)


def test_hlp_client_accepts_event_bus_publish_protocol_without_emit():
    bus = PublishOnlyEventBus()
    client = HLPClient(adapter=FakeAgentAdapter(), event_bus=bus)

    task = run(client.create_task(principal="user_alice", goal="Publish via protocol"))

    assert [event.action for event in bus.events] == ["task.created"]
    assert bus.events[0].task_id == task.id


def test_hlp_client_returns_snapshots_that_cannot_mutate_store():
    client = HLPClient(adapter=FakeAgentAdapter())

    task = run(client.create_task(principal="user_alice", goal="Protect state"))
    task.state = "completed"
    task.ownership = task.ownership.transfer("agent_intruder", via="handoff")

    restored = run(client.get_task(task.id))
    assert restored.state == "created"
    assert restored.ownership.assignee == "user_alice"


def test_store_read_api_returns_snapshots_that_cannot_mutate_internal_state():
    client = HLPClient(adapter=FakeAgentAdapter())

    task = run(client.create_task(principal="user_alice", goal="Store snapshot"))
    stored = client.store.get_task(task.id)
    stored.state = "completed"

    restored = client.store.get_task(task.id)
    assert restored.state == "created"


def test_sqlite_store_persists_hlp_state_across_restart(tmp_path):
    db_path = tmp_path / "hlp.db"
    first = HLPClient(
        store=SQLiteHumanLoopStore(db_path),
        adapter=FakeAgentAdapter(),
    )

    task = run(first.create_task(principal="user_alice", goal="Persist HLP state"))
    run(first.delegate(task.id, "agent_persistent"))
    run(first.start(task.id))
    checkpoint = run(first.raise_checkpoint(
        task_id=task.id,
        kind="approval",
        prompt="Continue?",
        raised_by="agent_persistent",
    ))
    run(first.resolve_checkpoint(checkpoint.id, by="user_alice", action="approve"))
    artifact = run(first.commit_artifact(
        task_id=task.id,
        type="report",
        payload=ArtifactPayload(
            kind="inline",
            uri="mem://persisted-report",
            checksum="sha256:persisted-report",
        ),
        produced_by="agent_persistent",
    ))
    review = run(first.submit_review(
        task_id=task.id,
        artifact_id=artifact.id,
        reviewer="user_alice",
        verdict="approved",
    ))
    run(first.write_ledger("project:persist", "status", "approved", by=task.id))

    second = HLPClient(
        store=SQLiteHumanLoopStore(db_path),
        adapter=FakeAgentAdapter(),
    )

    restored_task = run(second.get_task(task.id))
    restored_checkpoint = second.store.get_checkpoint(checkpoint.id)
    restored_artifact = second.store.get_artifact(artifact.id)
    restored_review = second.store.get_review(review.id)
    restored_ledger_value = run(second.read_ledger("project:persist", "status"))
    restored_history = run(second.replay_audit(task.id))

    assert restored_task.id == task.id
    assert restored_task.state == "completed"
    assert restored_checkpoint.state == "resolved"
    assert restored_artifact.version == "v1"
    assert restored_review.verdict == "approved"
    assert restored_ledger_value == "approved"
    assert [event.action for event in restored_history][-4:] == [
        "artifact.committed",
        "review.submitted",
        "task.completed",
        "ledger.written",
    ]


def test_sqlite_store_persists_idempotency_records_across_restart(tmp_path):
    db_path = tmp_path / "hlp-idempotency.db"
    first_adapter = FakeAgentAdapter()
    first_bus = InMemoryEventBus()
    first = HLPClient(
        store=SQLiteHumanLoopStore(db_path),
        adapter=first_adapter,
        event_bus=first_bus,
    )

    task = run(first.create_task(
        principal="user_alice",
        goal="Persist idempotency",
    ))
    handle = run(first.delegate(
        task.id,
        "agent_persistent",
        expected_task_revision=task.revision,
        idempotency_key="delegate-once",
    ))
    run(first.start(task.id))
    revision = run(first.get_task(task.id)).revision
    amended = run(first.amend(
        task.id,
        by="user_alice",
        text="Replay must not steer twice.",
        expected_task_revision=revision,
        idempotency_key="amend-once",
    ))

    second_adapter = FakeAgentAdapter()
    second_bus = InMemoryEventBus()
    second = HLPClient(
        store=SQLiteHumanLoopStore(db_path),
        adapter=second_adapter,
        event_bus=second_bus,
    )
    replayed_handle = run(second.delegate(
        task.id,
        "agent_persistent",
        expected_task_revision=task.revision,
        idempotency_key="delegate-once",
    ))
    replayed = run(second.amend(
        task.id,
        by="user_alice",
        text="Replay must not steer twice.",
        expected_task_revision=revision,
        idempotency_key="amend-once",
    ))

    assert replayed_handle == handle
    assert replayed == amended
    assert len(first_adapter.calls_of("delegate")) == 1
    assert second_adapter.calls_of("delegate") == []
    assert len(first_adapter.calls_of("steer")) == 1
    assert second_adapter.calls_of("steer") == []
    assert [event.action for event in first_bus.events].count("task.delegated") == 1
    assert [event.action for event in first_bus.events].count("task.amended") == 1
    assert second_bus.events == []


def test_sdk_replay_covers_primary_task_mutations_without_duplicate_events():
    adapter = FakeAgentAdapter()
    bus = InMemoryEventBus()
    client = HLPClient(adapter=adapter, event_bus=bus)

    task = run(client.create_task(principal="user_alice", goal="Replay SDK operations"))
    handle = run(client.delegate(
        task.id,
        "agent_worker",
        expected_task_revision=task.revision,
        idempotency_key="sdk-delegate",
    ))
    replayed_handle = run(client.delegate(
        task.id,
        "agent_worker",
        expected_task_revision=task.revision,
        idempotency_key="sdk-delegate",
    ))
    assert replayed_handle == handle

    assigned_revision = run(client.get_task(task.id)).revision
    started = run(client.start(
        task.id,
        expected_task_revision=assigned_revision,
        idempotency_key="sdk-start",
    ))
    replayed_start = run(client.start(
        task.id,
        expected_task_revision=assigned_revision,
        idempotency_key="sdk-start",
    ))
    assert replayed_start == started

    in_progress_revision = run(client.get_task(task.id)).revision
    checkpoint = run(client.raise_checkpoint(
        task_id=task.id,
        kind="approval",
        prompt="Approve SDK replay?",
        raised_by="agent_worker",
        expected_task_revision=in_progress_revision,
        idempotency_key="sdk-raise",
    ))
    replayed_checkpoint = run(client.raise_checkpoint(
        task_id=task.id,
        kind="approval",
        prompt="Approve SDK replay?",
        raised_by="agent_worker",
        expected_task_revision=in_progress_revision,
        idempotency_key="sdk-raise",
    ))
    assert replayed_checkpoint == checkpoint

    run(client.resolve_checkpoint(checkpoint.id, by="user_alice", action="approve"))
    artifact = run(client.commit_artifact(
        task_id=task.id,
        type="report",
        payload=ArtifactPayload(
            kind="inline",
            uri="mem://sdk-replay",
            checksum="sha256:sdk-replay",
        ),
        produced_by="agent_worker",
    ))
    review_revision = run(client.get_task(task.id)).revision
    review = run(client.submit_review(
        task_id=task.id,
        artifact_id=artifact.id,
        reviewer="user_alice",
        verdict="approved",
        expected_task_revision=review_revision,
        idempotency_key="sdk-review",
    ))
    replayed_review = run(client.submit_review(
        task_id=task.id,
        artifact_id=artifact.id,
        reviewer="user_alice",
        verdict="approved",
        expected_task_revision=review_revision,
        idempotency_key="sdk-review",
    ))
    assert replayed_review == review

    actions = [event.action for event in bus.events]
    assert actions.count("task.delegated") == 1
    assert actions.count("task.started") == 1
    assert actions.count("checkpoint.raised") == 1
    assert actions.count("review.submitted") == 1
    assert len(adapter.calls_of("delegate")) == 1
    assert len(adapter.calls_of("block")) == 1


def test_sdk_delayed_replay_returns_first_mutation_result():
    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter, event_bus=InMemoryEventBus())

    delegate_task = run(client.create_task(
        principal="user_alice",
        goal="Replay delegate after handoff",
    ))
    handle = run(client.delegate(
        delegate_task.id,
        "agent_worker",
        expected_task_revision=delegate_task.revision,
        idempotency_key="sdk-delayed-delegate",
    ))
    run(client.operations.ownership_transfer(
        delegate_task.id,
        "agent_writer",
        "handoff",
        actor="agent_worker",
    ))
    assert client.store.run_of_task(delegate_task.id) != handle.run_id
    replayed_handle = run(client.delegate(
        delegate_task.id,
        "agent_worker",
        expected_task_revision=delegate_task.revision,
        idempotency_key="sdk-delayed-delegate",
    ))
    assert replayed_handle.run_id == handle.run_id

    start_task = run(client.create_task(
        principal="user_alice",
        goal="Replay start after blocking",
    ))
    run(client.delegate(start_task.id, "agent_worker"))
    assigned_revision = run(client.get_task(start_task.id)).revision
    started = run(client.start(
        start_task.id,
        expected_task_revision=assigned_revision,
        idempotency_key="sdk-delayed-start",
    ))
    run(client.raise_checkpoint(
        task_id=start_task.id,
        kind="approval",
        prompt="Block after start.",
        raised_by="agent_worker",
    ))
    replayed_start = run(client.start(
        start_task.id,
        expected_task_revision=assigned_revision,
        idempotency_key="sdk-delayed-start",
    ))
    assert replayed_start == started
    assert replayed_start.state == "in_progress"
    assert run(client.get_task(start_task.id)).state == "blocked"

    amend_task = run(client.create_task(
        principal="user_alice",
        goal="Replay amend after blocking",
    ))
    run(client.delegate(amend_task.id, "agent_worker"))
    run(client.start(amend_task.id))
    amend_revision = run(client.get_task(amend_task.id)).revision
    amended = run(client.amend(
        amend_task.id,
        by="user_alice",
        text="Keep this result stable.",
        expected_task_revision=amend_revision,
        idempotency_key="sdk-delayed-amend",
    ))
    run(client.raise_checkpoint(
        task_id=amend_task.id,
        kind="approval",
        prompt="Block after amend.",
        raised_by="agent_worker",
    ))
    replayed_amend = run(client.amend(
        amend_task.id,
        by="user_alice",
        text="Keep this result stable.",
        expected_task_revision=amend_revision,
        idempotency_key="sdk-delayed-amend",
    ))
    assert replayed_amend == amended
    assert replayed_amend.state == "in_progress"
    assert run(client.get_task(amend_task.id)).state == "blocked"

    interrupt_task = run(client.create_task(
        principal="user_alice",
        goal="Replay interrupt after resolve",
    ))
    run(client.delegate(interrupt_task.id, "agent_worker"))
    run(client.start(interrupt_task.id))
    interrupt_revision = run(client.get_task(interrupt_task.id)).revision
    interrupted = run(client.interrupt(
        interrupt_task.id,
        by="user_alice",
        prompt="Pause once.",
        expected_task_revision=interrupt_revision,
        idempotency_key="sdk-delayed-interrupt",
    ))
    run(client.resolve_checkpoint(
        interrupted.id,
        by="user_alice",
        action="approve",
    ))
    replayed_interrupt = run(client.interrupt(
        interrupt_task.id,
        by="user_alice",
        prompt="Pause once.",
        expected_task_revision=interrupt_revision,
        idempotency_key="sdk-delayed-interrupt",
    ))
    assert replayed_interrupt == interrupted
    assert replayed_interrupt.state == "pending"
    assert client.store.get_checkpoint(interrupted.id).state == "resolved"

    raise_task = run(client.create_task(
        principal="user_alice",
        goal="Replay checkpoint after resolve",
    ))
    run(client.delegate(raise_task.id, "agent_worker"))
    run(client.start(raise_task.id))
    raise_revision = run(client.get_task(raise_task.id)).revision
    checkpoint = run(client.raise_checkpoint(
        task_id=raise_task.id,
        kind="approval",
        prompt="Raise once.",
        raised_by="agent_worker",
        expected_task_revision=raise_revision,
        idempotency_key="sdk-delayed-raise",
    ))
    run(client.resolve_checkpoint(
        checkpoint.id,
        by="user_alice",
        action="approve",
    ))
    replayed_checkpoint = run(client.raise_checkpoint(
        task_id=raise_task.id,
        kind="approval",
        prompt="Raise once.",
        raised_by="agent_worker",
        expected_task_revision=raise_revision,
        idempotency_key="sdk-delayed-raise",
    ))
    assert replayed_checkpoint == checkpoint
    assert replayed_checkpoint.state == "pending"
    assert client.store.get_checkpoint(checkpoint.id).state == "resolved"


def _local_cli_runner(name):
    async def runner(command, request, timeout):
        run_id = request.get("run_id") or f"{name}_{request['operation']}_run"
        if request["operation"] == "handoff":
            run_id = f"{name}_handoff_run"
        return ProcessResult(
            exit_code=0,
            stdout=json.dumps({
                "run_id": run_id,
                "correlation_id": request["correlation_id"],
                "status": "ok",
                "summary": f"{name} {request['operation']} passed",
            }),
            stderr="",
        )

    return runner


def test_hlp_e2e_demo_runs_through_real_adapter_path_without_external_services():
    result = run(run_demo(runner=_local_cli_runner("codex"), timeout=7.0))

    assert result["task_id"].startswith("task_")
    assert result["adapter"] == "codex"
    assert result["run_id"] == "codex_delegate_run"
    assert result["correlation_id"] == result["task_id"]
    assert result["returned_correlation_id"] == result["task_id"]
    assert result["checkpoint_decision"] == "safe"
    assert result["artifact_version"] == "v1"
    assert result["review_verdict"] == "approved"
    assert result["ledger_status"] == "approved"
    assert result["final_task_state"] == "completed"
    assert result["adapter_operations"] == [
        "delegate",
        "steer",
        "block",
        "resume",
        "delegate",
        "handoff",
        "cancel",
    ]
    assert result["audit_actions"] == [
        "task.created",
        "task.assigned",
        "task.started",
        "task.amended",
        "task.checkpoint.raised",
        "task.checkpoint.resolved",
        "artifact.committed",
        "review.submitted",
        "task.completed",
        "ledger.written",
    ]


def test_hlp_adapter_compat_demo_covers_named_targets_without_external_services():
    result = run(run_adapter_demo())

    assert set(result) == {
        "openai_python_sdk",
        "openai_agents_sdk",
        "langgraph",
        "crewai",
        "codex_cli",
        "codex_harness",
        "pi_harness",
        "claude_code_cli",
        "herms_cli",
    }
    for name, entry in result.items():
        assert entry["status"] == "ok", name
        assert entry["task_id"].startswith("task_"), name
        assert entry["run_id"], name
        assert entry["correlation_id"] == entry["task_id"], name

    assert result["openai_python_sdk"]["run_id"] == "resp_demo"
    assert result["openai_agents_sdk"]["run_id"] == "agents_demo"
    assert result["langgraph"]["run_id"] == "graph_demo"
    assert result["crewai"]["run_id"] == "crew_demo"
    assert result["codex_cli"]["run_id"] == "codex_demo"
    assert result["codex_harness"]["run_id"] == "codex_harness_demo"
    assert result["pi_harness"]["run_id"] == "pi_harness_demo"
    assert result["claude_code_cli"]["run_id"] == "claude_demo"
    assert result["herms_cli"]["run_id"] == "herms_demo"


def test_hlp_harness_wrap_demo_runs_without_external_services():
    result = run(run_harness_wrap_demo())

    assert result["task_id"].startswith("task_")
    assert result["run_id"] == "codex_wrap_run"
    assert result["checkpoint_prompt"] == "Apply the generated patch?"
    assert result["checkpoint_decision"] == "approve"
    assert result["artifact_version"] == "v1"
    assert result["review_verdict"] == "approved"
    assert result["inbox_after_checkpoint"] == ["resolve_checkpoint"]
    assert result["inbox_after_artifact"] == ["submit_review"]
    assert result["harness_conformance"] == [
        "checkpoint-capable",
        "artifact-aware",
    ]


def test_pr_review_desk_host_runs_full_offline_lifecycle(tmp_path):
    db_path = tmp_path / "pr-desk.db"
    result = run(run_desk_demo(db_path=db_path))

    assert result["mode"] == "offline"
    assert result["session"]["pr"]["repository"] == "acme/payments-api"
    assert result["session"]["pr"]["number"] == 1234
    assert result["session"]["task_id"].startswith("task_")
    assert result["session"]["run_id"]
    assert result["checkpoint"]["action"] == "approve"
    assert result["checkpoint"]["state"] == "resolved"
    assert result["artifact_id"].startswith("art_")
    assert result["review_id"].startswith("rev_")

    report = result["report"]
    assert report["pr_ref"] == "acme/payments-api#1234"
    assert report["task_state"] == "completed"
    assert report["review_verdict"] == "approved"
    assert report["steered"] is True
    assert report["inbox_remaining"] == []
    assert report["ledger_status"]["verdict"] == "approved"
    assert "task.amended" in report["audit_actions"]
    assert "review.submitted" in report["audit_actions"]
    assert "task.completed" in report["audit_actions"]
    assert result["host_events"][0] == "task.created"
    assert "review.submitted" in result["host_events"]
    assert db_path.exists()


def test_pr_review_desk_live_command_and_adapter_error_report():
    assert live_codex_command()[:3] == ("codex", "exec", "--json")
    assert "--skip-git-repo-check" in live_codex_command()
    assert live_codex_command(model="gpt-5.4")[-2:] == ("-m", "gpt-5.4")

    exc = AgentAdapterError(
        "codex-harness",
        "delegate",
        "process command failed",
        details={
            "exit_code": 1,
            "command": ("codex", "exec", "--json"),
            "stdout": json.dumps({
                "type": "error",
                "message": json.dumps({
                    "type": "error",
                    "status": 400,
                    "error": {
                        "type": "invalid_request_error",
                        "message": (
                            "The 'gpt-5.6-sol' model requires a newer version of Codex. "
                            "Please upgrade to the latest app or CLI and try again."
                        ),
                    },
                }),
            }),
            "stderr": "Reading additional input from stdin...\n",
        },
    )
    report = adapter_error_report(exc, live=True)
    assert report["status"] == "error"
    assert report["mode"] == "live"
    assert "newer version of Codex" in (report["codex_message"] or "")
    assert any("Upgrade Codex CLI" in hint for hint in report["hints"])
    assert any("offline" in hint for hint in report["hints"])


def test_pr_review_desk_maps_domain_inbox_and_rejects_side_effects():
    desk = build_desk(principal="user_alice", reviewer="user_carol")
    pr = PullRequest(
        repository="acme/web",
        number=9,
        title="Tighten CORS",
        author="dev_dave",
    )
    session = run(desk.open_review(pr))
    session = run(desk.dispatch(session))
    projected = run(desk.sync_harness(session))
    assert len(projected) == 1

    cards = run(desk.list_inbox())
    assert len(cards) == 1
    assert cards[0].pr_ref == "acme/web#9"
    assert cards[0].action == "resolve_checkpoint"
    assert "post findings" in cards[0].title.lower() or "PR comments" in cards[0].title

    checkpoint = run(desk.decide_checkpoint(
        cards[0],
        decision="reject",
        comment="No external comments without security lead",
    ))
    assert checkpoint.resolution is not None
    assert checkpoint.resolution.action == "reject"

    # Rejected side effects: no deliverable artifact projection expected.
    more = run(desk.sync_harness(session))
    assert more == []
    remaining = run(desk.list_inbox())
    assert remaining == []

    report = run(desk.report(session))
    assert report.checkpoint_decision == "reject"
    assert report.artifact_id is None
    assert report.review_id is None
    # HLP: rejecting a checkpoint completes the task (abort path).
    assert report.task_state == "completed"


def test_hlp_codex_harness_demo_runs_without_external_services():
    result = run(run_codex_harness_demo())

    assert result["task_id"].startswith("task_")
    assert result["run_id"] == "codex_demo_run"
    assert result["adapter"] == "codex-harness"
    assert result["harness_conformance"] == [
        "checkpoint-capable",
        "artifact-aware",
        "event-streaming",
    ]
    assert result["checkpoint_prompt"] == "Apply the Codex patch?"
    assert result["checkpoint_decision"] == "approve"
    assert result["artifact_version"] == "v1"
    assert result["artifact_uri"] == "mem://codex-demo.patch"
    assert result["review_verdict"] == "approved"
    assert result["final_task_state"] == "completed"
    assert result["inbox_after_checkpoint"] == ["resolve_checkpoint"]
    assert result["inbox_after_artifact"] == ["submit_review"]


def test_hlp_local_cli_demo_runs_selected_adapters_full_lifecycle_with_injected_runners():
    captured = {}

    def make_runner(name):
        async def runner(command, request, timeout):
            captured.setdefault(name, []).append({
                "command": command,
                "request": request,
                "timeout": timeout,
            })
            run_id = request.get("run_id") or f"{name}_{request['operation']}_run"
            if request["operation"] == "handoff":
                run_id = f"{name}_handoff_run"
            return ProcessResult(
                exit_code=0,
                stdout=json.dumps({
                    "run_id": run_id,
                    "correlation_id": request["correlation_id"],
                    "status": "ok",
                    "summary": f"{name} {request['operation']} passed",
                }),
                stderr="",
            )

        return runner

    result = run(run_local_cli_demo(
        adapters=("codex", "kimi", "claude"),
        runners={
            "codex": make_runner("codex"),
            "kimi": make_runner("kimi"),
            "claude": make_runner("claude"),
        },
        timeout=7.0,
    ))

    assert set(result) == {"codex", "kimi", "claude"}
    for name, entry in result.items():
        assert entry["status"] == "ok", name
        assert entry["task_id"].startswith("task_"), name
        assert entry["run_id"] == f"{name}_delegate_run", name
        assert entry["correlation_id"] == entry["task_id"], name
        assert entry["returned_correlation_id"] == entry["task_id"], name
        assert entry["adapter_operations"] == [
            "delegate",
            "steer",
            "block",
            "resume",
            "delegate",
            "handoff",
            "cancel",
        ]
        assert entry["final_task_state"] == "completed", name
        assert entry["review_verdict"] == "approved", name
        assert entry["ledger_status"] == "approved", name
        assert entry["control_final_task_state"] == "completed", name
        assert entry["handoff_run_id"] == f"{name}_handoff_run", name
        assert [call["request"]["operation"] for call in captured[name]] == entry["adapter_operations"]
        assert all(call["timeout"] == 7.0 for call in captured[name])

    assert captured["codex"][0]["command"][:2] == ("codex", "exec")
    assert captured["kimi"][0]["command"][0] == "kimi"
    assert "-p" in captured["kimi"][0]["command"]
    assert captured["claude"][0]["command"][:2] == ("claude", "-p")


def test_examples_and_site_quickstarts_do_not_use_fake_adapters():
    root = Path(__file__).resolve().parents[1]
    checked = [
        *root.glob("examples/*.py"),
        root / "README.md",
        root / "docs/site/index.md",
        root / "docs/site/reading-routes.md",
    ]

    offenders = {
        str(path.relative_to(root)): text
        for path in checked
        if (
            (text := path.read_text())
            and ("FakeAgentAdapter" in text or "FakeHarnessAdapter" in text)
        )
    }

    assert offenders == {}


def test_hlp_local_cli_demo_can_use_metaworker_kimi_config(tmp_path):
    metaworker_config = tmp_path / "config.yaml"
    metaworker_config.write_text(
        """
providers:
  moonshot:
    api_key: test-key
    base_url: https://api.moonshot.cn/v1
    model: kimi-k2.6
    type: auto
""".strip()
    )
    captured = {}

    async def runner(command, request, timeout):
        captured["command"] = command
        config_path = command[2]
        captured["config_text"] = open(config_path).read()
        return ProcessResult(
            exit_code=0,
            stdout=json.dumps({
                "run_id": "kimi_run",
                "correlation_id": request["correlation_id"],
                "status": "ok",
            }),
            stderr="",
        )

    result = run(run_local_cli_demo(
        adapters=("kimi",),
        runners={"kimi": runner},
        metaworker_config=metaworker_config,
        timeout=7.0,
    ))

    assert result["kimi"]["status"] == "ok"
    assert result["kimi"]["returned_correlation_id"] == result["kimi"]["task_id"]
    assert captured["command"][:2] == ("kimi-cli", "--config-file")
    assert captured["command"][3:5] == ("--quiet", "-p")
    assert 'default_model = "hlp-kimi"' in captured["config_text"]
    assert 'type = "openai_legacy"' in captured["config_text"]
    assert 'base_url = "https://api.moonshot.cn/v1"' in captured["config_text"]
    assert 'model = "kimi-k2.6"' in captured["config_text"]
