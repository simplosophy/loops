from __future__ import annotations

import json
from io import StringIO
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loops import (
    AgentEvent,
    AgentPolicy,
    InMemoryEventLogger,
    InMemoryEventSink,
    InteractionContext,
    PromptTemplate,
    ToolCall,
    agent,
)
from loops.loop0.components import Component, Contribution
from loops.loop0.profiles import ComponentProfile, ProviderProfile, ToolProfile
from loops.loop0.providers.adapter import (
    AdapterBackedProvider,
    ProviderAdapter,
    ProviderModel,
    ProviderOptions,
    get_provider_adapter,
    register_provider_adapter,
    unregister_provider_adapters,
)
from loops.loop0.providers.base import Provider, ProviderEvent, ProviderRequest, ProviderResponse
from loops.loop0.providers.openai import (
    OPENAI_CHAT_API,
    OpenAIChatAdapter,
    OpenAICompatibleProvider,
    _message_to_openai,
    _response_from_openai,
)
from loops.loop0.tools import BaseTool, ShellTool, ToolContext, ToolResult
from loops.loop0.types import Message, UserInput


@dataclass
class FakeProvider(Provider):
    responses: list[ProviderResponse]
    requests: list[ProviderRequest] = field(default_factory=list)

    @property
    def profile(self) -> ProviderProfile:
        return ProviderProfile(name="fake", model="fake-model", capabilities=frozenset({"tool_calling"}))

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        if not self.responses:
            return ProviderResponse(content="")
        return self.responses.pop(0)


@dataclass
class FakeStreamingProvider(Provider):
    requests: list[ProviderRequest] = field(default_factory=list)

    @property
    def profile(self) -> ProviderProfile:
        return ProviderProfile(name="fake-stream", model="fake-stream-model", capabilities=frozenset({"streaming"}))

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        raise AssertionError("streaming runtime should call stream(), not generate()")

    async def stream(self, request: ProviderRequest):
        self.requests.append(request)
        yield ProviderEvent(type="delta", payload={"text": "hel"})
        yield ProviderEvent(type="delta", payload={"text": "lo"})
        yield ProviderEvent(type="response", payload={"response": ProviderResponse(content="hello")})


class TextOnlyAdapter(ProviderAdapter):
    api = "test-text-only"

    def __init__(self) -> None:
        self.requests: list[ProviderRequest] = []
        self.options: list[ProviderOptions] = []

    async def stream(self, model: ProviderModel, request: ProviderRequest, options: ProviderOptions):
        del model
        self.requests.append(request)
        self.options.append(options)
        yield ProviderEvent(type="text_delta", payload={"text": "hel"})
        yield ProviderEvent(type="text_delta", payload={"text": "lo"})
        yield ProviderEvent(type="reasoning_delta", payload={"text": "thinking"})


class NewEventStreamingAdapter(ProviderAdapter):
    api = "test-new-stream-events"

    async def stream(self, model: ProviderModel, request: ProviderRequest, options: ProviderOptions):
        del model, request, options
        yield ProviderEvent(type="text_delta", payload={"text": "hel"})
        yield ProviderEvent(type="text_delta", payload={"text": "lo"})
        yield ProviderEvent(type="response_finished", payload={"response": ProviderResponse(content="hello")})


class EchoTool(BaseTool):
    profile = ToolProfile(
        name="echo",
        description="Echo a value.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        effects=frozenset({"read"}),
        risk="low",
        source="test",
    )

    async def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        del ctx
        return ToolResult.success(args.get("value", ""))


class SleepEchoTool(BaseTool):
    profile = ToolProfile(
        name="sleep_echo",
        description="Sleep briefly and echo a value.",
        input_schema={
            "type": "object",
            "properties": {
                "value": {"type": "string"},
                "delay": {"type": "number"},
            },
            "required": ["value"],
        },
        effects=frozenset({"read"}),
        risk="low",
        source="test",
    )

    async def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        del ctx
        import asyncio

        await asyncio.sleep(float(args.get("delay", 0) or 0))
        return ToolResult.success(args.get("value", ""))


class EchoComponent(Component):
    profile = ComponentProfile(name="echo-component", kind="tool_provider", priority=10)

    def __init__(self) -> None:
        self.events = []

    async def contribute(self, run_context: Any) -> Contribution:
        del run_context
        return Contribution(prompt_blocks=["component prompt block"], tools=[EchoTool()])

    async def handle_event(self, event: Any) -> None:
        self.events.append(event.type)


async def _noop_emit(event: AgentEvent) -> None:
    del event


def _tool_context(tmp_path: Path, *, policy: AgentPolicy | None = None) -> ToolContext:
    return ToolContext(
        agent_id="agent-test",
        run_id="run-test",
        workspace=tmp_path,
        policy=policy or AgentPolicy(),
        state=None,
        emit=_noop_emit,
    )


def test_prompt_template_injects_interaction_tool_provider_profiles(tmp_path: Path):
    provider = FakeProvider([ProviderResponse(content="ok")])
    app = agent(
        PromptTemplate(
            system=(
                "provider={{ provider.name }}/{{ provider.model }}\n"
                "interaction={{ interaction.source }} streaming={{ interaction.stream | json }}\n"
                "{% for tool in tools %}tool={{ tool.name }} risk={{ tool.risk }} {% endfor %}\n"
                "tool_names={{ tools | map(attribute='name') | join(',') }}\n"
                "missing={{ missing.profile.name | default('empty') }}\n"
                "interactive={{ interaction.interactive | json }}"
            )
        ),
        provider=provider,
        tools=[ShellTool()],
        workspace=tmp_path,
    )

    import asyncio

    user_input = UserInput("hello", interaction_context=InteractionContext(source="tui", interactive=True))
    result = asyncio.run(app.run(user_input, stream=True))

    assert result.output == "ok"
    system_prompt = provider.requests[0].messages[0].content
    assert "provider=fake/fake-model" in system_prompt
    assert "interaction=tui streaming=true" in system_prompt
    assert "tool=shell risk=medium" in system_prompt
    assert "tool_names=shell" in system_prompt
    assert "missing=empty" in system_prompt
    assert "interactive=true" in system_prompt


def test_top_level_imports_remain_compatible():
    from loops.providers.adapter import AdapterBackedProvider as CompatAdapterBackedProvider
    from loops.providers.openai import OpenAICompatibleProvider as CompatOpenAICompatibleProvider
    from loops.tools import ShellTool as CompatShellTool
    from loops.types import Message as CompatMessage

    assert CompatAdapterBackedProvider is AdapterBackedProvider
    assert CompatOpenAICompatibleProvider is OpenAICompatibleProvider
    assert CompatShellTool is ShellTool
    assert CompatMessage is Message


def test_top_level_channel_alias_is_removed():
    try:
        __import__("loops.channels")
    except ModuleNotFoundError:
        return
    raise AssertionError("loops.channels should not exist in loop0")


def test_loop0_cli_accepts_full_command_line_config(tmp_path: Path):
    from loops.loop0.cli import parse_run_config

    system_file = tmp_path / "system.md"
    system_file.write_text("System from file", encoding="utf-8")
    extra_body = tmp_path / "extra.json"
    extra_body.write_text('{"temperature": 0.2}', encoding="utf-8")

    config = parse_run_config(
        [
            "--system-file",
            str(system_file),
            "--user",
            "{{ input.text }}!",
            "--provider",
            "openai-compatible",
            "--provider-name",
            "deepseek",
            "--model",
            "deepseek-chat",
            "--api-key-env",
            "TEST_LOOP0_KEY",
            "--base-url",
            "https://api.deepseek.com",
            "--timeout-seconds",
            "12",
            "--disable-verify-ssl",
            "--header",
            "X-Test=1",
            "--reasoning-effort",
            "low",
            "--extra-body-file",
            str(extra_body),
            "--agent-name",
            "cli-agent",
            "--agent-description",
            "CLI agent",
            "--workspace",
            str(tmp_path / "workspace"),
            "--metadata",
            "team=loop0",
            "--no-tools",
            "--max-turns",
            "3",
            "--no-allow-tool-errors",
            "--parallel-tool-calls",
            "--max-parallel-tool-calls",
            "2",
            "--auto-approve",
            "--shell-timeout-seconds",
            "5",
            "--shell-max-output-chars",
            "100",
            "--no-shell-require-approval-for-background",
            "--shell-external-path-policy",
            "deny",
            "--input",
            "hello",
            "--thread-id",
            "thread-cli",
            "--stream",
            "--log-level",
            "INFO",
            "--source",
            "terminal",
            "--session-id",
            "session-cli",
            "--actor-id",
            "actor-cli",
            "--reply-to",
            "msg-cli",
            "--audience",
            "user",
            "--interactive",
            "--locale",
            "zh-CN",
            "--interaction-raw",
            "raw_key=raw_value",
            "--output",
            "json",
            "--show-events",
            "--events-file",
            str(tmp_path / "events.jsonl"),
        ],
        env={"TEST_LOOP0_KEY": "secret"},
    )

    assert config.prompt.system_file == str(system_file)
    assert config.prompt.user == "{{ input.text }}!"
    assert config.provider.name == "deepseek"
    assert config.provider.model == "deepseek-chat"
    assert config.provider.api_key == "secret"
    assert config.provider.base_url == "https://api.deepseek.com"
    assert config.provider.timeout_seconds == 12
    assert config.provider.disable_verify_ssl is True
    assert config.provider.headers == {"X-Test": "1"}
    assert config.provider.extra_body == {"temperature": 0.2}
    assert config.agent.name == "cli-agent"
    assert config.agent.tools == []
    assert config.policy.max_turns == 3
    assert config.policy.allow_tool_errors is False
    assert config.policy.parallel_tool_calls is True
    assert config.policy.max_parallel_tool_calls == 2
    assert config.policy.auto_approve is True
    assert config.policy.shell_require_approval_for_background is False
    assert config.policy.shell_external_path_policy == "deny"
    assert config.run.input == "hello"
    assert config.run.thread_id == "thread-cli"
    assert config.run.stream is True
    assert config.interaction.source == "terminal"
    assert config.interaction.raw == {"raw_key": "raw_value"}
    assert config.output.format == "json"
    assert config.output.show_events is True


def test_loop0_cli_runs_from_config_file(tmp_path: Path):
    import asyncio

    from loops.loop0.cli import parse_run_config, run_loop0

    (tmp_path / "system.md").write_text("source={{ interaction.source }}", encoding="utf-8")
    config_path = tmp_path / "loop0.toml"
    config_path.write_text(
        """
tools = []

[prompt]
system_file = "system.md"

[provider]
model = "fake-model"
api_key = "dummy"

[agent]
name = "config-agent"
workspace = "workspace"

[run]
input = "hello from config"
thread_id = "config-thread"
stream = true

[interaction]
source = "config-file"

[output]
format = "text"
show_events = true
events_file = "events.jsonl"
""".strip(),
        encoding="utf-8",
    )
    provider = FakeProvider([ProviderResponse(content="ok")])
    config = parse_run_config(["--config", str(config_path)])
    output = StringIO()
    errors = StringIO()

    result = asyncio.run(run_loop0(config, provider=provider, output_stream=output, error_stream=errors))

    assert result.output == "ok"
    assert output.getvalue() == "ok\n"
    assert "provider_started" in errors.getvalue()
    assert provider.requests[0].stream is True
    assert provider.requests[0].tools == []
    assert provider.requests[0].messages[0].content == "source=config-file"
    assert provider.requests[0].messages[-1].content == "hello from config"
    assert provider.requests[0].metadata["thread_id"] == "config-thread"
    assert (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()


def test_provider_adapter_registry_and_stream_folding():
    import asyncio

    adapter = TextOnlyAdapter()
    source_id = "test-text-only-source"
    register_provider_adapter(adapter, source_id=source_id)
    try:
        provider = AdapterBackedProvider(
            provider_model=ProviderModel(
                provider="test-provider",
                model="test-model",
                api=adapter.api,
                capabilities=frozenset({"streaming"}),
            ),
            options=ProviderOptions(api_key="secret", metadata={"purpose": "test"}),
        )
        response = asyncio.run(provider.generate(ProviderRequest(messages=[Message(role="user", content="hi")])))
    finally:
        unregister_provider_adapters(source_id)

    assert get_provider_adapter(adapter.api) is None
    assert provider.profile.name == "test-provider"
    assert provider.profile.model == "test-model"
    assert "streaming" in provider.profile.capabilities
    assert adapter.options[0].api_key == "secret"
    assert response.content == "hello"
    assert response.message_metadata["reasoning_content"] == "thinking"


def test_openai_chat_adapter_is_registered():
    assert isinstance(get_provider_adapter(OPENAI_CHAT_API), OpenAIChatAdapter)


def test_shell_tool_accepts_command_sequences_and_records_structured_outputs(tmp_path: Path):
    import asyncio

    tool = ShellTool()
    result = asyncio.run(
        tool.execute(
            _tool_context(tmp_path),
            {"op": "run", "commands": ["printf one", "printf two"]},
        )
    )

    assert result.is_success
    assert result.output == "$ printf one\none\n\n$ printf two\ntwo"
    assert result.metadata["command_count"] == 2
    assert result.metadata["returncode"] == 0
    assert [entry["stdout"] for entry in result.metadata["outputs"]] == ["one", "two"]


def test_shell_tool_command_sequences_fail_fast(tmp_path: Path):
    import asyncio

    tool = ShellTool()
    result = asyncio.run(
        tool.execute(
            _tool_context(tmp_path),
            {
                "op": "run",
                "commands": ["printf before", "sh -c 'exit 7'", "printf after"],
            },
        )
    )

    assert not result.is_success
    assert result.status == "error"
    assert "exit code: 7" in (result.error or "")
    assert "after" not in (result.error or "")
    assert result.metadata["returncode"] == 7
    assert len(result.metadata["outputs"]) == 2


def test_shell_tool_supports_openai_style_aliases_cwd_and_env(tmp_path: Path):
    import asyncio

    workdir = tmp_path / "work"
    workdir.mkdir()
    tool = ShellTool()
    result = asyncio.run(
        tool.execute(
            _tool_context(tmp_path),
            {
                "op": "run",
                "command": "printf \"$LOOPS_TEST\"",
                "cwd": "work",
                "env": {"LOOPS_TEST": "ok"},
                "timeout_ms": 5000,
                "maxOutputLength": 10,
            },
        )
    )

    assert result.is_success
    assert result.output == "ok"
    assert result.metadata["cwd"] == str(workdir)
    assert result.metadata["timeout_seconds"] == 5
    assert result.metadata["env_keys"] == ["LOOPS_TEST"]


def test_shell_tool_rejects_string_like_commands(tmp_path: Path):
    import asyncio

    result = asyncio.run(
        ShellTool().execute(
            _tool_context(tmp_path),
            {"op": "run", "commands": "printf bad"},
        )
    )

    assert result.status == "invalid_args"
    assert "commands must be a sequence" in (result.error or "")


def test_shell_tool_timeout_returns_structured_timeout(tmp_path: Path):
    import asyncio

    result = asyncio.run(
        ShellTool().execute(
            _tool_context(tmp_path),
            {"op": "run", "command": "sleep 1", "timeout_ms": 10},
        )
    )

    assert result.status == "timeout"
    assert result.metadata["outputs"][0]["status"] == "timeout"
    assert "status: timeout" in (result.error or "")


def test_shell_tool_lists_and_logs_background_sessions(tmp_path: Path):
    import asyncio

    async def run_case():
        tool = ShellTool()
        ctx = _tool_context(
            tmp_path,
            policy=AgentPolicy(shell_require_approval_for_background=False),
        )
        started = await tool.execute(
            ctx,
            {"op": "run", "command": "printf out; printf err >&2", "background": True},
        )
        session_id = json.loads(started.output)["session_id"]
        await asyncio.sleep(0.05)

        sessions = json.loads((await tool.execute(ctx, {"op": "list"})).output)["sessions"]
        log_payload = json.loads((await tool.execute(ctx, {"op": "log", "session_id": session_id})).output)
        return session_id, sessions, log_payload

    session_id, sessions, log_payload = asyncio.run(run_case())

    assert any(session["session_id"] == session_id for session in sessions)
    assert log_payload["total"] >= 2
    assert {line["stream"] for line in log_payload["lines"]} == {"stdout", "stderr"}
    assert all("index" in line and "created_at" in line for line in log_payload["lines"])


def test_provider_tool_loop_executes_shell_and_commits_state(tmp_path: Path):
    provider = FakeProvider(
        [
            ProviderResponse(
                tool_calls=[
                    ToolCall(name="shell", arguments={"op": "run", "command": "printf loops"})
                ]
            ),
            ProviderResponse(content="done"),
        ]
    )
    app = agent("Use tools when useful.", provider=provider, workspace=tmp_path)

    import asyncio

    result = asyncio.run(app.run("say loops", thread_id="thread-a"))

    assert result.output == "done"
    assert result.stats.tool_calls == 1
    assert len(provider.requests) == 2
    second_request = provider.requests[1]
    assert any(message.role == "tool" and message.content == "loops" for message in second_request.messages)
    history = app.state.get_history("thread-a")
    assert [message.role for message in history] == ["user", "assistant"]
    assert history[-1].content == "done"


def test_agent_logger_receives_structured_tool_events(tmp_path: Path):
    logger = InMemoryEventLogger()
    provider = FakeProvider(
        [
            ProviderResponse(
                tool_calls=[
                    ToolCall(name="shell", arguments={"op": "run", "command": "printf loops"})
                ]
            ),
            ProviderResponse(content="done"),
        ]
    )
    app = agent("Use tools when useful.", provider=provider, logger=logger, workspace=tmp_path)

    import asyncio

    asyncio.run(app.run("say loops", thread_id="thread-a"))

    event_types = [event.type for event in logger.events]
    assert event_types[:2] == ["run_started", "provider_started"]
    assert "tool_started" in event_types
    assert "tool_finished" in event_types
    tool_started = [event for event in logger.events if event.type == "tool_started"][0]
    assert tool_started.payload["arguments"]["command"] == "printf loops"
    tool_finished = [event for event in logger.events if event.type == "tool_finished"][0]
    assert tool_finished.payload["status"] == "success"
    assert tool_finished.payload["metadata"]["returncode"] == 0
    assert tool_finished.payload["duration_ms"] >= 0
    assert tool_finished.payload["output"] == "loops"


def test_parallel_tool_calls_execute_concurrently_and_preserve_message_order(tmp_path: Path):
    logger = InMemoryEventLogger()
    provider = FakeProvider(
        [
            ProviderResponse(
                tool_calls=[
                    ToolCall(
                        name="sleep_echo",
                        arguments={"value": "first", "delay": 0.05},
                        id="call_first",
                    ),
                    ToolCall(
                        name="sleep_echo",
                        arguments={"value": "second", "delay": 0.001},
                        id="call_second",
                    ),
                ]
            ),
            ProviderResponse(content="done"),
        ]
    )
    app = agent(
        "Use tools when useful.",
        provider=provider,
        tools=[SleepEchoTool()],
        policy=AgentPolicy(parallel_tool_calls=True, max_parallel_tool_calls=2),
        logger=logger,
        workspace=tmp_path,
    )

    import asyncio

    result = asyncio.run(app.run("run both tools", thread_id="thread-a"))

    assert result.output == "done"
    assert provider.requests[0].parallel_tool_calls is True
    finished_outputs = [
        event.payload["output"] for event in logger.events if event.type == "tool_finished"
    ]
    assert finished_outputs == ["second", "first"]
    second_request_tool_messages = [
        message.content for message in provider.requests[1].messages if message.role == "tool"
    ]
    assert second_request_tool_messages == ["first", "second"]


def test_openai_provider_serializes_parallel_tool_calls_flag():
    provider = OpenAICompatibleProvider(model="test-model", api_key="test-key")
    tool = ToolProfile(
        name="echo",
        description="Echo.",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    )

    enabled = provider._build_payload(
        ProviderRequest(
            messages=[Message(role="user", content="hi")],
            tools=[tool],
            parallel_tool_calls=True,
        ),
        stream=False,
    )
    disabled = provider._build_payload(
        ProviderRequest(
            messages=[Message(role="user", content="hi")],
            tools=[tool],
            parallel_tool_calls=False,
        ),
        stream=False,
    )
    omitted_without_tools = provider._build_payload(
        ProviderRequest(messages=[Message(role="user", content="hi")], parallel_tool_calls=True),
        stream=False,
    )

    assert enabled["parallel_tool_calls"] is True
    assert disabled["parallel_tool_calls"] is False
    assert "parallel_tool_calls" not in omitted_without_tools


def test_shell_blocks_dangerous_and_external_path_without_approval(tmp_path: Path):
    provider = FakeProvider(
        [
            ProviderResponse(
                tool_calls=[ToolCall(name="shell", arguments={"op": "run", "command": "rm -rf /"})]
            ),
            ProviderResponse(content="blocked"),
        ]
    )
    app = agent("Use shell.", provider=provider, workspace=tmp_path)

    import asyncio

    result = asyncio.run(app.run("try dangerous command"))

    assert result.output == "blocked"
    tool_message = [message for message in provider.requests[1].messages if message.role == "tool"][0]
    assert "Blocked:" in tool_message.content

    external_provider = FakeProvider(
        [
            ProviderResponse(
                tool_calls=[ToolCall(name="shell", arguments={"op": "run", "command": "cat /etc/passwd"})]
            ),
            ProviderResponse(content="external blocked"),
        ]
    )
    external_app = agent("Use shell.", provider=external_provider, workspace=tmp_path)
    asyncio.run(external_app.run("try external path"))
    external_tool_message = [message for message in external_provider.requests[1].messages if message.role == "tool"][0]
    assert "outside the workspace" in external_tool_message.content


def test_shell_background_session_requires_and_uses_approval(tmp_path: Path):
    approvals = []

    async def approve(request):
        approvals.append(request)
        return True

    provider = FakeProvider(
        [
            ProviderResponse(
                tool_calls=[
                    ToolCall(
                        name="shell",
                        arguments={"op": "run", "command": "sleep 2", "background": True},
                    )
                ]
            ),
            ProviderResponse(content="started"),
        ]
    )
    app = agent("Use shell.", provider=provider, policy=AgentPolicy(approval_handler=approve), workspace=tmp_path)

    import asyncio

    asyncio.run(app.run("start background job"))
    assert approvals
    tool_message = [message for message in provider.requests[1].messages if message.role == "tool"][0]
    payload = json.loads(tool_message.content)
    assert payload["status"] == "started"
    assert payload["session_id"].startswith("sh_")


def test_event_sink_receives_streaming_events_when_requested(tmp_path: Path):
    provider = FakeProvider([ProviderResponse(content="stream me")])
    sink = InMemoryEventSink()
    app = agent("Reply.", provider=provider, workspace=tmp_path)

    import asyncio

    result = asyncio.run(app.run("hello", event_sink=sink, stream=True))

    assert result.output == "stream me"
    assert provider.requests[0].stream is True
    assert [event.payload["text"] for event in sink.events if event.type == "provider_delta"] == ["stream me"]
    assert "run_finished" in [event.type for event in sink.events]


def test_non_stream_run_uses_generate_and_does_not_emit_provider_delta(tmp_path: Path):
    provider = FakeProvider([ProviderResponse(content="message me")])
    sink = InMemoryEventSink()
    app = agent("Reply.", provider=provider, workspace=tmp_path)

    import asyncio

    result = asyncio.run(app.run("hello", event_sink=sink))

    assert result.output == "message me"
    assert provider.requests[0].stream is False
    assert "provider_delta" not in [event.type for event in sink.events]
    assert "run_finished" in [event.type for event in sink.events]


def test_interaction_context_controls_prompt_state(tmp_path: Path):
    provider = FakeProvider([ProviderResponse(content="scheduled")])
    app = agent(
        PromptTemplate(system="source={{ interaction.source }} interactive={{ interaction.interactive | json }}"),
        provider=provider,
        workspace=tmp_path,
    )
    user_input = UserInput("cron", interaction_context=InteractionContext(source="scheduled", interactive=False))

    import asyncio

    asyncio.run(app.run(user_input))

    assert "source=scheduled interactive=false" in provider.requests[0].messages[0].content

    dict_provider = FakeProvider([ProviderResponse(content="web")])
    dict_app = agent(
        PromptTemplate(system="source={{ interaction.source }} interactive={{ interaction.interactive | json }}"),
        provider=dict_provider,
        workspace=tmp_path / "dict",
    )
    dict_input = UserInput("web", interaction_context={"source": "web", "interactive": True})

    asyncio.run(dict_app.run(dict_input))

    assert "source=web interactive=true" in dict_provider.requests[0].messages[0].content


def test_stream_run_uses_true_provider_streaming(tmp_path: Path):
    provider = FakeStreamingProvider()
    sink = InMemoryEventSink()
    app = agent("Reply.", provider=provider, workspace=tmp_path)

    import asyncio

    result = asyncio.run(app.run("hello", event_sink=sink, stream=True))

    assert result.output == "hello"
    assert provider.requests[0].stream is True
    deltas = [event.payload["text"] for event in sink.events if event.type == "provider_delta"]
    assert deltas == ["hel", "lo"]


def test_runtime_accepts_new_provider_stream_events(tmp_path: Path):
    provider = AdapterBackedProvider(
        provider_model=ProviderModel(
            provider="new-events",
            model="new-events-model",
            api=NewEventStreamingAdapter.api,
            capabilities=frozenset({"streaming"}),
        ),
        adapter=NewEventStreamingAdapter(),
    )
    sink = InMemoryEventSink()
    app = agent("Reply.", provider=provider, workspace=tmp_path)

    import asyncio

    result = asyncio.run(app.run("hello", event_sink=sink, stream=True))

    assert result.output == "hello"
    deltas = [event.payload["text"] for event in sink.events if event.type == "provider_delta"]
    assert deltas == ["hel", "lo"]


def test_callable_event_sink_receives_events(tmp_path: Path):
    import asyncio

    provider = FakeProvider([ProviderResponse(content="ok")])
    app = agent("Reply.", provider=provider, workspace=tmp_path)
    seen = []

    async def collect(event: AgentEvent) -> None:
        seen.append(event.type)

    result = asyncio.run(app.run("hello", event_sink=collect))

    assert result.output == "ok"
    assert seen[0] == "run_started"
    assert "run_finished" in seen


def test_start_agent_interactive_loop_reuses_thread(monkeypatch):
    import argparse
    import asyncio

    from examples import start_agent

    provider = FakeProvider([ProviderResponse(content="first"), ProviderResponse(content="second")])
    monkeypatch.setattr(start_agent, "build_provider", lambda args: provider)
    args = argparse.Namespace(
        message=[],
        show_events=False,
        thread_id="console-test",
    )
    output = StringIO()
    asyncio.run(
        start_agent.run_demo(
            args,
            input_stream=StringIO("hello\nagain\n/quit\n"),
            output_stream=output,
        )
    )

    assert len(provider.requests) == 2
    assert provider.requests[0].metadata["thread_id"] == "console-test"
    assert provider.requests[1].metadata["thread_id"] == "console-test"
    assert [message.content for message in provider.requests[1].messages if message.role == "user"] == [
        "hello",
        "again",
    ]
    assert [message.content for message in provider.requests[1].messages if message.role == "assistant"] == [
        "first"
    ]
    assert "first" in output.getvalue()
    assert "second" in output.getvalue()


def test_agent_run_without_event_sink_is_quiet_and_returns_result(tmp_path: Path):
    import asyncio

    provider = FakeProvider([ProviderResponse(content="ok")])
    app = agent("Reply.", provider=provider, workspace=tmp_path)

    result = asyncio.run(app.run("hello"))

    assert result.output == "ok"
    assert [event.type for event in result.events] == [
        "run_started",
        "provider_started",
        "provider_finished",
        "run_finished",
    ]


def test_component_contributes_prompt_block_tool_and_events(tmp_path: Path):
    component = EchoComponent()
    provider = FakeProvider(
        [
            ProviderResponse(tool_calls=[ToolCall(name="echo", arguments={"value": "from component"})]),
            ProviderResponse(content="finished"),
        ]
    )
    app = agent(
        PromptTemplate(
            system="{% for block in components.prompt_blocks %}{{ block }}{% endfor %}",
        ),
        provider=provider,
        tools=[],
        components=[component],
        workspace=tmp_path,
    )

    import asyncio

    result = asyncio.run(app.run("use component"))

    assert result.output == "finished"
    assert "component prompt block" in provider.requests[0].messages[0].content
    assert any(tool.name == "echo" for tool in provider.requests[0].tools)
    assert "tool_finished" in component.events


def test_openai_provider_preserves_reasoning_content_for_next_turn():
    response = _response_from_openai(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "thinking trace",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "shell",
                                    "arguments": "{\"op\":\"run\",\"command\":\"pwd\"}",
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }
    )

    assert response.message_metadata["reasoning_content"] == "thinking trace"
    message = Message(
        role="assistant",
        content=response.content,
        tool_calls=response.tool_calls,
        metadata=response.message_metadata,
    )
    projected = _message_to_openai(message)
    assert projected["reasoning_content"] == "thinking trace"
    assert projected["tool_calls"][0]["function"]["name"] == "shell"
