from __future__ import annotations

import asyncio
import importlib
import json

from loops.hlp import (
    AgentAdapterError,
    ArtifactPayload,
    ClaudeCodeCLIAdapter,
    CheckpointOption,
    CodexCLIAdapter,
    CrewAIAdapter,
    FakeAgentAdapter,
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
    ProcessAgentAdapter,
    PythonCallableAgentAdapter,
    ProcessResult,
    SQLiteHumanLoopStore,
)
from examples.hlp_e2e_demo import run_demo
from examples.hlp_adapter_compat_demo import run_demo as run_adapter_demo
from examples.hlp_local_cli_e2e import run_demo as run_local_cli_demo


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
    async def handler(request):
        return {"handled": request["task_id"], "agent": request["agent_id"]}

    python_adapter = PythonCallableAgentAdapter("custom-python", handler)
    openai_agents = OpenAIAgentsSDKAdapter(handler)
    openai_python = OpenAIPythonSDKAdapter(handler)
    langgraph = LangGraphAdapter(handler)
    crewai = CrewAIAdapter(handler)
    codex = CodexCLIAdapter(command=("codex", "exec"))
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

    assert run(openai_agents.healthcheck())["adapter"] == "openai-agents-sdk"
    assert run(openai_python.healthcheck())["adapter"] == "openai-python-sdk"
    assert run(langgraph.healthcheck())["adapter"] == "langgraph"
    assert run(crewai.healthcheck())["adapter"] == "crewai"
    assert run(codex.healthcheck())["command"] == ("codex", "exec")
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


def test_hlp_e2e_demo_runs_without_external_services():
    result = run(run_demo())

    assert result["task_id"].startswith("task_")
    assert result["run_id"].startswith("run_")
    assert result["checkpoint_decision"] == "safe"
    assert result["artifact_version"] == "v1"
    assert result["review_verdict"] == "approved"
    assert result["ledger_status"] == "approved"
    assert result["audit_actions"] == [
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


def test_hlp_adapter_compat_demo_covers_named_targets_without_external_services():
    result = run(run_adapter_demo())

    assert set(result) == {
        "openai_python_sdk",
        "openai_agents_sdk",
        "langgraph",
        "crewai",
        "codex_cli",
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
    assert result["claude_code_cli"]["run_id"] == "claude_demo"
    assert result["herms_cli"]["run_id"] == "herms_demo"


def test_hlp_local_cli_demo_runs_selected_adapters_with_injected_runners():
    captured = {}

    def make_runner(name):
        async def runner(command, request, timeout):
            captured[name] = {
                "command": command,
                "request": request,
                "timeout": timeout,
            }
            return ProcessResult(
                exit_code=0,
                stdout=json.dumps({
                    "run_id": f"{name}_run",
                    "correlation_id": request["correlation_id"],
                    "status": "ok",
                    "summary": f"{name} smoke passed",
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
        assert entry["run_id"] == f"{name}_run", name
        assert entry["correlation_id"] == entry["task_id"], name
        assert entry["returned_correlation_id"] == entry["task_id"], name
        assert captured[name]["request"]["operation"] == "delegate"
        assert captured[name]["request"]["correlation_id"] == entry["task_id"]
        assert captured[name]["timeout"] == 7.0

    assert captured["codex"]["command"][:2] == ("codex", "exec")
    assert captured["kimi"]["command"][0] == "kimi"
    assert "-p" in captured["kimi"]["command"]
    assert captured["claude"]["command"][:2] == ("claude", "-p")


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
