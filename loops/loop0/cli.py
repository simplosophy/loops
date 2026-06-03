"""Command line runner for a single loop0 Agent run."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from loops.loop0.agent import Agent, agent
from loops.loop0.events import AgentEvent
from loops.loop0.logging import get_logger
from loops.loop0.policy import AgentPolicy
from loops.loop0.profiles import InteractionContext
from loops.loop0.prompt import PromptTemplate
from loops.loop0.providers import OpenAICompatibleProvider, Provider
from loops.loop0.runtime import AgentResult
from loops.loop0.tools import ShellTool
from loops.loop0.types import UserInput


DEFAULT_SYSTEM_PROMPT = "You are a helpful agent."
DEFAULT_API_KEY_ENV = "LOOPS_OPENAI_API_KEY"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


@dataclass
class PromptConfig:
    system: str = DEFAULT_SYSTEM_PROMPT
    system_file: str | None = None
    user: str = "{{ input.text }}"
    user_file: str | None = None
    engine: str = "jinja"


@dataclass
class ProviderConfig:
    type: str = "openai-compatible"
    name: str = "openai-compatible"
    model: str = ""
    api_key: str = ""
    api_key_env: str = DEFAULT_API_KEY_ENV
    base_url: str = DEFAULT_BASE_URL
    timeout_seconds: float = 60.0
    disable_verify_ssl: bool = False
    headers: dict[str, str] = field(default_factory=dict)
    reasoning_effort: str | None = None
    extra_body: dict[str, Any] = field(default_factory=dict)


@dataclass
class PolicyConfig:
    max_turns: int = 20
    allow_tool_errors: bool = True
    parallel_tool_calls: bool | None = None
    max_parallel_tool_calls: int | None = 1
    auto_approve: bool = False
    shell_timeout_seconds: float = 60.0
    shell_max_output_chars: int = 30_000
    shell_require_approval_for_background: bool = True
    shell_external_path_policy: str = "ask"


@dataclass
class AgentConfig:
    name: str = "loop0-cli"
    description: str = ""
    workspace: str = ".loops-workspace"
    metadata: dict[str, Any] = field(default_factory=dict)
    tools: list[str] = field(default_factory=lambda: ["shell"])


@dataclass
class RunConfig:
    input: str | None = None
    input_file: str | None = None
    thread_id: str = "default"
    stream: bool = False
    log_level: str = ""


@dataclass
class InteractionConfig:
    source: str = "cli"
    session_id: str | None = None
    actor_id: str | None = None
    reply_to: str | None = None
    audience: str = "user"
    interactive: bool = False
    locale: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutputConfig:
    format: str = "text"
    show_events: bool = False
    events_file: str | None = None


@dataclass
class Loop0RunConfig:
    prompt: PromptConfig = field(default_factory=PromptConfig)
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    run: RunConfig = field(default_factory=RunConfig)
    interaction: InteractionConfig = field(default_factory=InteractionConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    env_file: str | None = None
    base_dir: Path = field(default_factory=Path.cwd)


class CliEventSink:
    """Event sink used by the one-shot CLI runner."""

    def __init__(self, *, output_stream, stream_text: bool) -> None:
        self.output_stream = output_stream
        self.stream_text = stream_text
        self.events: list[AgentEvent] = []
        self.saw_delta = False

    async def send(self, event: AgentEvent) -> None:
        self.events.append(event)
        if not self.stream_text or event.type != "provider_delta":
            return
        text = str(event.payload.get("text") or "")
        if not text:
            return
        self.saw_delta = True
        print(text, end="", file=self.output_stream, flush=True)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one loop0 Agent turn.")
    parser.add_argument("message", nargs="*", help="Input message. Omit when using --input, --input-file, or config.")
    parser.add_argument("--config", help="JSON or TOML config file. CLI flags override config values.")
    parser.add_argument("--env-file", help="Dotenv-style file to load. Default: .env when present.")

    prompt = parser.add_argument_group("prompt")
    prompt.add_argument("--system", help="System prompt text.")
    prompt.add_argument("--system-file", help="Read system prompt from file.")
    prompt.add_argument("--user", help="User prompt template text. Default: {{ input.text }}")
    prompt.add_argument("--user-file", help="Read user prompt template from file.")
    prompt.add_argument("--prompt-engine", choices=["jinja"], help="Prompt engine.")

    provider = parser.add_argument_group("provider")
    provider.add_argument("--provider", choices=["openai-compatible"], help="Provider type.")
    provider.add_argument("--provider-name", help="Provider profile name.")
    provider.add_argument("--model", help="Model name.")
    provider.add_argument("--api-key", help="Provider API key.")
    provider.add_argument("--api-key-env", help=f"Environment variable for provider API key. Default: {DEFAULT_API_KEY_ENV}")
    provider.add_argument("--base-url", help=f"OpenAI-compatible base URL. Default: {DEFAULT_BASE_URL}")
    provider.add_argument("--timeout-seconds", type=float, help="Provider HTTP timeout in seconds.")
    provider.add_argument("--disable-verify-ssl", action="store_true", default=None, help="Disable provider SSL verification.")
    provider.add_argument("--verify-ssl", action="store_true", default=None, help="Enable provider SSL verification.")
    provider.add_argument("--header", action="append", default=None, metavar="KEY=VALUE", help="Provider HTTP header.")
    provider.add_argument("--reasoning-effort", help="Reasoning effort option for compatible providers.")
    provider.add_argument("--extra-body", help="JSON object merged into provider request body.")
    provider.add_argument("--extra-body-file", help="Read provider extra body JSON object from file.")

    agent_group = parser.add_argument_group("agent")
    agent_group.add_argument("--agent-name", help="Agent profile name.")
    agent_group.add_argument("--agent-description", help="Agent profile description.")
    agent_group.add_argument("--workspace", help="Agent workspace path.")
    agent_group.add_argument("--metadata", action="append", default=None, metavar="KEY=VALUE", help="Agent metadata entry.")
    agent_group.add_argument("--tool", action="append", choices=["shell"], default=None, help="Enable a tool. May repeat.")
    agent_group.add_argument("--no-tools", action="store_true", default=None, help="Disable all tools.")

    policy = parser.add_argument_group("policy")
    policy.add_argument("--max-turns", type=int, help="Maximum provider/tool loop turns.")
    policy.add_argument("--allow-tool-errors", action=argparse.BooleanOptionalAction, default=None)
    policy.add_argument("--parallel-tool-calls", action=argparse.BooleanOptionalAction, default=None)
    policy.add_argument("--max-parallel-tool-calls", type=int, help="Maximum concurrent tool executions.")
    policy.add_argument("--auto-approve", action=argparse.BooleanOptionalAction, default=None, help="Automatically approve tool approval requests.")
    policy.add_argument("--shell-timeout-seconds", type=float, help="Default shell command timeout.")
    policy.add_argument("--shell-max-output-chars", type=int, help="Maximum shell output chars preserved.")
    policy.add_argument("--shell-require-approval-for-background", action=argparse.BooleanOptionalAction, default=None)
    policy.add_argument(
        "--shell-external-path-policy",
        choices=["ask", "deny", "allow"],
        help="Policy for shell access outside workspace.",
    )

    run = parser.add_argument_group("run")
    run.add_argument("--input", dest="input_text", help="Input message text.")
    run.add_argument("--input-file", help="Read input message from file.")
    run.add_argument("--thread-id", help="Agent thread id.")
    run.add_argument("--stream", action=argparse.BooleanOptionalAction, default=None, help="Request provider streaming.")
    run.add_argument("--log-level", help="Enable loop0 runtime logging level, e.g. INFO or DEBUG.")

    interaction = parser.add_argument_group("interaction")
    interaction.add_argument("--source", help="Interaction source injected into prompt context.")
    interaction.add_argument("--session-id", help="Interaction session id.")
    interaction.add_argument("--actor-id", help="Interaction actor id.")
    interaction.add_argument("--reply-to", help="Interaction reply target.")
    interaction.add_argument("--audience", choices=["user", "group", "system"], help="Interaction audience.")
    interaction.add_argument("--interactive", action=argparse.BooleanOptionalAction, default=None)
    interaction.add_argument("--locale", help="Interaction locale.")
    interaction.add_argument("--interaction-raw", action="append", default=None, metavar="KEY=VALUE", help="Raw interaction metadata.")

    output = parser.add_argument_group("output")
    output.add_argument("--output", choices=["text", "json"], help="Output format.")
    output.add_argument("--show-events", action=argparse.BooleanOptionalAction, default=None, help="Include or print event data.")
    output.add_argument("--events-file", help="Write AgentEvent records as JSONL.")
    return parser


def parse_run_config(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Loop0RunConfig:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config_data, base_dir = _load_config(args.config)
    config = _config_from_mapping(config_data, base_dir=base_dir)
    _apply_cli_args(config, args)
    _apply_env(config, _load_env(config, base_env=env or os.environ))
    return config


def build_provider(config: ProviderConfig, *, env: Mapping[str, str] | None = None) -> OpenAICompatibleProvider:
    if config.type != "openai-compatible":
        raise ValueError(f"Unsupported provider type: {config.type}")
    api_key = config.api_key or (env or os.environ).get(config.api_key_env, "")
    if not api_key:
        raise ValueError(f"Missing provider API key. Pass --api-key or set {config.api_key_env}.")
    if not config.model:
        raise ValueError("Missing provider model. Pass --model or set provider.model in config.")
    return OpenAICompatibleProvider(
        name=config.name,
        model=config.model,
        api_key=api_key,
        base_url=config.base_url,
        timeout_seconds=config.timeout_seconds,
        disable_verify_ssl=config.disable_verify_ssl,
        headers=dict(config.headers),
        reasoning_effort=config.reasoning_effort,
        extra_body=dict(config.extra_body),
    )


def build_loop0_agent(config: Loop0RunConfig, *, provider: Provider | None = None) -> Agent:
    prompt = PromptTemplate(
        system=_resolve_text(config.prompt.system, config.prompt.system_file, base_dir=config.base_dir),
        user=_resolve_text(config.prompt.user, config.prompt.user_file, base_dir=config.base_dir),
        engine=config.prompt.engine,
    )
    metadata = dict(config.agent.metadata)
    metadata.setdefault("name", config.agent.name)
    metadata.setdefault("description", config.agent.description)
    return agent(
        prompt,
        provider=provider or build_provider(config.provider),
        tools=_build_tools(config.agent.tools),
        policy=_build_policy(config.policy),
        metadata=metadata,
        logger=_build_logger(config.run.log_level),
        workspace=_resolve_path(config.agent.workspace, base_dir=config.base_dir),
    )


async def run_loop0(
    config: Loop0RunConfig,
    *,
    provider: Provider | None = None,
    output_stream=None,
    error_stream=None,
    input_stream=None,
) -> AgentResult:
    output_stream = output_stream or sys.stdout
    error_stream = error_stream or sys.stderr
    input_text = _resolve_input(config, input_stream=input_stream)
    sink = CliEventSink(
        output_stream=output_stream,
        stream_text=config.run.stream and config.output.format == "text",
    )
    loop_agent = build_loop0_agent(config, provider=provider)
    result = await loop_agent.run(
        UserInput(
            text=input_text,
            interaction_context=InteractionContext(
                source=config.interaction.source,
                session_id=config.interaction.session_id,
                thread_id=config.run.thread_id,
                actor_id=config.interaction.actor_id,
                reply_to=config.interaction.reply_to,
                audience=config.interaction.audience,  # type: ignore[arg-type]
                interactive=config.interaction.interactive,
                stream=config.run.stream,
                locale=config.interaction.locale,
                raw=dict(config.interaction.raw),
            ),
        ),
        thread_id=config.run.thread_id,
        event_sink=sink,
        stream=config.run.stream,
    )
    _write_events_file(config, result.events)
    _write_output(config, result, sink=sink, output_stream=output_stream, error_stream=error_stream)
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        config = parse_run_config(argv)
        asyncio.run(run_loop0(config))
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"loops-loop0 failed: {exc}", file=sys.stderr)
        return 1


def _load_config(path: str | None) -> tuple[dict[str, Any], Path]:
    if not path:
        return {}, Path.cwd()
    config_path = Path(path).expanduser().resolve(strict=False)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    if config_path.suffix.lower() == ".json":
        return json.loads(config_path.read_text(encoding="utf-8")), config_path.parent
    if config_path.suffix.lower() in {".toml", ".tml"}:
        with config_path.open("rb") as handle:
            return tomllib.load(handle), config_path.parent
    raise ValueError("Config file must be .json or .toml")


def _config_from_mapping(data: Mapping[str, Any], *, base_dir: Path) -> Loop0RunConfig:
    prompt = _mapping(data.get("prompt"))
    provider = _mapping(data.get("provider"))
    policy = _mapping(data.get("policy"))
    agent_data = _mapping(data.get("agent"))
    run = _mapping(data.get("run"))
    interaction = _mapping(data.get("interaction"))
    output = _mapping(data.get("output"))

    return Loop0RunConfig(
        prompt=PromptConfig(
            system=str(prompt.get("system", DEFAULT_SYSTEM_PROMPT)),
            system_file=_optional_str(prompt.get("system_file")),
            user=str(prompt.get("user", "{{ input.text }}")),
            user_file=_optional_str(prompt.get("user_file")),
            engine=str(prompt.get("engine", "jinja")),
        ),
        provider=ProviderConfig(
            type=str(provider.get("type", "openai-compatible")),
            name=str(provider.get("name", "openai-compatible")),
            model=str(provider.get("model", "")),
            api_key=str(provider.get("api_key", "")),
            api_key_env=str(provider.get("api_key_env", DEFAULT_API_KEY_ENV)),
            base_url=str(provider.get("base_url", DEFAULT_BASE_URL)),
            timeout_seconds=float(provider.get("timeout_seconds", 60.0)),
            disable_verify_ssl=bool(provider.get("disable_verify_ssl", False)),
            headers={str(key): str(value) for key, value in _mapping(provider.get("headers")).items()},
            reasoning_effort=_optional_str(provider.get("reasoning_effort")),
            extra_body=dict(_mapping(provider.get("extra_body"))),
        ),
        policy=PolicyConfig(
            max_turns=int(policy.get("max_turns", 20)),
            allow_tool_errors=bool(policy.get("allow_tool_errors", True)),
            parallel_tool_calls=_optional_bool(policy.get("parallel_tool_calls")),
            max_parallel_tool_calls=_optional_int(policy.get("max_parallel_tool_calls", 1)),
            auto_approve=bool(policy.get("auto_approve", False)),
            shell_timeout_seconds=float(policy.get("shell_timeout_seconds", 60.0)),
            shell_max_output_chars=int(policy.get("shell_max_output_chars", 30_000)),
            shell_require_approval_for_background=bool(policy.get("shell_require_approval_for_background", True)),
            shell_external_path_policy=str(policy.get("shell_external_path_policy", "ask")),
        ),
        agent=AgentConfig(
            name=str(agent_data.get("name", "loop0-cli")),
            description=str(agent_data.get("description", "")),
            workspace=str(agent_data.get("workspace", data.get("workspace", ".loops-workspace"))),
            metadata=dict(_mapping(agent_data.get("metadata"))),
            tools=_string_list(agent_data.get("tools", data.get("tools", ["shell"]))),
        ),
        run=RunConfig(
            input=_optional_str(run.get("input")),
            input_file=_optional_str(run.get("input_file")),
            thread_id=str(run.get("thread_id", "default")),
            stream=bool(run.get("stream", False)),
            log_level=str(run.get("log_level", "")),
        ),
        interaction=InteractionConfig(
            source=str(interaction.get("source", "cli")),
            session_id=_optional_str(interaction.get("session_id")),
            actor_id=_optional_str(interaction.get("actor_id")),
            reply_to=_optional_str(interaction.get("reply_to")),
            audience=str(interaction.get("audience", "user")),
            interactive=bool(interaction.get("interactive", False)),
            locale=_optional_str(interaction.get("locale")),
            raw=dict(_mapping(interaction.get("raw"))),
        ),
        output=OutputConfig(
            format=str(output.get("format", "text")),
            show_events=bool(output.get("show_events", False)),
            events_file=_optional_str(output.get("events_file")),
        ),
        env_file=_optional_str(data.get("env_file")),
        base_dir=base_dir,
    )


def _apply_cli_args(config: Loop0RunConfig, args: argparse.Namespace) -> None:
    if args.env_file is not None:
        config.env_file = _cli_path(args.env_file)
    if args.system is not None:
        config.prompt.system = args.system
        config.prompt.system_file = None
    if args.system_file is not None:
        config.prompt.system_file = _cli_path(args.system_file)
    if args.user is not None:
        config.prompt.user = args.user
        config.prompt.user_file = None
    if args.user_file is not None:
        config.prompt.user_file = _cli_path(args.user_file)
    if args.prompt_engine is not None:
        config.prompt.engine = args.prompt_engine

    _set_if(config.provider, "type", args.provider)
    _set_if(config.provider, "name", args.provider_name)
    _set_if(config.provider, "model", args.model)
    _set_if(config.provider, "api_key", args.api_key)
    _set_if(config.provider, "api_key_env", args.api_key_env)
    _set_if(config.provider, "base_url", args.base_url)
    _set_if(config.provider, "timeout_seconds", args.timeout_seconds)
    if args.disable_verify_ssl is not None:
        config.provider.disable_verify_ssl = True
    if args.verify_ssl is not None:
        config.provider.disable_verify_ssl = False
    if args.header:
        config.provider.headers.update(_parse_key_values(args.header))
    _set_if(config.provider, "reasoning_effort", args.reasoning_effort)
    if args.extra_body is not None:
        config.provider.extra_body.update(_json_object(args.extra_body, "--extra-body"))
    if args.extra_body_file is not None:
        config.provider.extra_body.update(_json_object(_read_file(args.extra_body_file), "--extra-body-file"))

    _set_if(config.agent, "name", args.agent_name)
    _set_if(config.agent, "description", args.agent_description)
    if args.workspace is not None:
        config.agent.workspace = args.workspace
    if args.metadata:
        config.agent.metadata.update(_parse_key_values(args.metadata))
    if args.no_tools:
        config.agent.tools = []
    elif args.tool is not None:
        config.agent.tools = list(args.tool)

    _set_if(config.policy, "max_turns", args.max_turns)
    _set_if(config.policy, "allow_tool_errors", args.allow_tool_errors)
    _set_if(config.policy, "parallel_tool_calls", args.parallel_tool_calls)
    _set_if(config.policy, "max_parallel_tool_calls", args.max_parallel_tool_calls)
    _set_if(config.policy, "auto_approve", args.auto_approve)
    _set_if(config.policy, "shell_timeout_seconds", args.shell_timeout_seconds)
    _set_if(config.policy, "shell_max_output_chars", args.shell_max_output_chars)
    _set_if(config.policy, "shell_require_approval_for_background", args.shell_require_approval_for_background)
    _set_if(config.policy, "shell_external_path_policy", args.shell_external_path_policy)

    if args.input_text is not None:
        config.run.input = args.input_text
        config.run.input_file = None
    if args.input_file is not None:
        config.run.input_file = _cli_path(args.input_file)
    if args.message:
        config.run.input = " ".join(args.message).strip()
        config.run.input_file = None
    _set_if(config.run, "thread_id", args.thread_id)
    _set_if(config.run, "stream", args.stream)
    _set_if(config.run, "log_level", args.log_level)

    _set_if(config.interaction, "source", args.source)
    _set_if(config.interaction, "session_id", args.session_id)
    _set_if(config.interaction, "actor_id", args.actor_id)
    _set_if(config.interaction, "reply_to", args.reply_to)
    _set_if(config.interaction, "audience", args.audience)
    _set_if(config.interaction, "interactive", args.interactive)
    _set_if(config.interaction, "locale", args.locale)
    if args.interaction_raw:
        config.interaction.raw.update(_parse_key_values(args.interaction_raw))

    _set_if(config.output, "format", args.output)
    _set_if(config.output, "show_events", args.show_events)
    if args.events_file is not None:
        config.output.events_file = args.events_file


def _apply_env(config: Loop0RunConfig, env: Mapping[str, str]) -> None:
    if not config.provider.api_key:
        config.provider.api_key = env.get(config.provider.api_key_env, "")


def _load_env(config: Loop0RunConfig, *, base_env: Mapping[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in _env_paths(config):
        if path.exists():
            values.update(_read_dotenv(path))
    values.update({str(key): str(value) for key, value in base_env.items()})
    return values


def _env_paths(config: Loop0RunConfig) -> list[Path]:
    if config.env_file:
        return [_resolve_path(config.env_file, base_dir=config.base_dir)]
    paths = [Path.cwd() / ".env"]
    config_env = config.base_dir / ".env"
    if config_env != paths[0]:
        paths.append(config_env)
    return paths


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            raise ValueError(f"Invalid env line in {path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid env line in {path}:{line_number}: empty key")
        values[key] = _strip_env_value(value.strip())
    return values


def _strip_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _build_policy(config: PolicyConfig) -> AgentPolicy:
    def approve_all(_request):
        return True

    return AgentPolicy(
        max_turns=config.max_turns,
        allow_tool_errors=config.allow_tool_errors,
        parallel_tool_calls=config.parallel_tool_calls,
        max_parallel_tool_calls=config.max_parallel_tool_calls,
        approval_handler=approve_all if config.auto_approve else None,
        shell_timeout_seconds=config.shell_timeout_seconds,
        shell_max_output_chars=config.shell_max_output_chars,
        shell_require_approval_for_background=config.shell_require_approval_for_background,
        shell_external_path_policy=config.shell_external_path_policy,
    )


def _build_tools(names: list[str]):
    tools = []
    for name in names:
        if name == "shell":
            tools.append(ShellTool())
        else:
            raise ValueError(f"Unsupported tool: {name}")
    return tools


def _build_logger(level_name: str):
    if not level_name:
        return None
    level = getattr(logging, level_name.upper(), None)
    if not isinstance(level, int):
        raise ValueError(f"Unknown log level: {level_name}")
    return get_logger("loops.loop0.cli", level=level)


def _resolve_input(config: Loop0RunConfig, *, input_stream=None) -> str:
    if config.run.input_file:
        return _read_resolved_file(config.run.input_file, base_dir=config.base_dir)
    if config.run.input is not None:
        return config.run.input
    stream = input_stream if input_stream is not None else sys.stdin
    if not stream.isatty():
        return stream.read()
    raise ValueError("Missing input. Pass a message, --input, --input-file, or run.input in config.")


def _resolve_text(default_text: str, file_path: str | None, *, base_dir: Path) -> str:
    if file_path:
        return _read_resolved_file(file_path, base_dir=base_dir)
    return default_text


def _write_output(
    config: Loop0RunConfig,
    result: AgentResult,
    *,
    sink: CliEventSink,
    output_stream,
    error_stream,
) -> None:
    if config.output.format == "json":
        print(
            json.dumps(_result_to_dict(result, include_events=config.output.show_events), ensure_ascii=False),
            file=output_stream,
        )
        return
    if not sink.saw_delta and result.output:
        print(result.output, file=output_stream, flush=True)
    elif sink.saw_delta:
        print(file=output_stream, flush=True)
    if config.output.show_events:
        print("--- events ---", file=error_stream)
        for event in result.events:
            print(event.type, file=error_stream)


def _write_events_file(config: Loop0RunConfig, events: list[AgentEvent]) -> None:
    if not config.output.events_file:
        return
    path = _resolve_path(config.output.events_file, base_dir=config.base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(_event_to_dict(event), ensure_ascii=False) + "\n")


def _result_to_dict(result: AgentResult, *, include_events: bool) -> dict[str, Any]:
    data = {
        "output": result.output,
        "run_id": result.run_id,
        "thread_id": result.thread_id,
        "stop_reason": result.stop_reason,
        "stats": _jsonable(result.stats),
    }
    if include_events:
        data["events"] = [_event_to_dict(event) for event in result.events]
    return data


def _event_to_dict(event: AgentEvent) -> dict[str, Any]:
    return {
        "type": event.type,
        "run_id": event.run_id,
        "payload": _jsonable(event.payload),
        "event_id": event.event_id,
        "timestamp": event.timestamp.isoformat(),
    }


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _set_if(target: Any, field_name: str, value: Any) -> None:
    if value is not None:
        setattr(target, field_name, value)


def _mapping(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"Expected mapping, got {type(value).__name__}")
    return value


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item) for item in value]
    raise TypeError("Expected string or list for tools")


def _parse_key_values(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Expected KEY=VALUE, got: {value}")
        key, item = value.split("=", 1)
        if not key:
            raise ValueError(f"Expected non-empty KEY in: {value}")
        parsed[key] = item
    return parsed


def _json_object(raw: str, label: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _read_file(path: str) -> str:
    return Path(path).expanduser().read_text(encoding="utf-8")


def _read_resolved_file(path: str, *, base_dir: Path) -> str:
    return _resolve_path(path, base_dir=base_dir).read_text(encoding="utf-8")


def _resolve_path(path: str, *, base_dir: Path) -> Path:
    resolved = Path(path).expanduser()
    if resolved.is_absolute():
        return resolved
    return (base_dir / resolved).resolve(strict=False)


def _cli_path(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


if __name__ == "__main__":
    raise SystemExit(main())
