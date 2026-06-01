"""Sample startup script for a loops agent using an OpenAI-compatible provider.

DeepSeek defaults:

    base_url: https://api.deepseek.com
    model: deepseek-v4-pro
    disable_verify_ssl: false

Run from the repository root:

    export LOOPS_DEEPSEEK_API_KEY="..."
    uv run loops-demo

or:

    uv run loops-demo "inspect the workspace"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from loops import AgentPolicy, PromptTemplate, agent, get_logger
from loops.channels import ConsoleChannel
from loops.providers import OpenAICompatibleProvider
from loops.types import UserInput

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-pro"


def _env_bool(name: str, *, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_provider(args: argparse.Namespace) -> OpenAICompatibleProvider:
    api_key = args.api_key or os.environ.get("LOOPS_DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "Missing DeepSeek API key. Set LOOPS_DEEPSEEK_API_KEY or pass --api-key."
        )
    return OpenAICompatibleProvider(
        name="deepseek",
        api_key=api_key,
        base_url=args.base_url or os.environ.get("LOOPS_DEEPSEEK_BASE_URL", DEFAULT_BASE_URL),
        model=args.model or os.environ.get("LOOPS_DEEPSEEK_MODEL", DEFAULT_MODEL),
        disable_verify_ssl=args.disable_verify_ssl
        or _env_bool("LOOPS_DEEPSEEK_DISABLE_VERIFY_SSL", default=False),
    )


def build_logger(args: argparse.Namespace):
    level_name = (getattr(args, "log_level", "") or os.environ.get("LOOPS_LOG_LEVEL", "")).strip()
    if not level_name:
        return None
    level = getattr(logging, level_name.upper(), None)
    if not isinstance(level, int):
        raise SystemExit(f"Unknown log level: {level_name}")
    return get_logger("loops.demo", level=level)


def build_policy(args: argparse.Namespace) -> AgentPolicy:
    max_parallel_tool_calls = int(getattr(args, "max_parallel_tool_calls", 1) or 1)
    if max_parallel_tool_calls < 1:
        raise SystemExit("--max-parallel-tool-calls must be >= 1")
    return AgentPolicy(
        parallel_tool_calls=True if getattr(args, "parallel_tool_calls", False) else None,
        max_parallel_tool_calls=max_parallel_tool_calls,
    )


def create_demo_agent(args: argparse.Namespace, channel: ConsoleChannel):
    return agent(
        PromptTemplate(
            system="""
You are {{ agent.name }}.

Provider: {{ provider.name }} / {{ provider.model }}
Channel: {{ channel.profile.name }}
Interactive: {{ channel.profile.interactive | json }}
Output mode: {{ channel.profile.output_mode }}

Use the shell tool when it is useful for inspecting the local workspace.

Available tools:
{% for tool in tools %}
- {{ tool.name }}: {{ tool.description }}
{% endfor %}
""".strip(),
        ),
        provider=build_provider(args),
        channels=[channel],
        policy=build_policy(args),
        metadata={"name": "loops-deepseek-demo"},
        logger=build_logger(args),
        workspace=".loops-demo-workspace",
    )


async def run_once(
    demo_agent,
    channel: ConsoleChannel,
    message: str | UserInput,
    args: argparse.Namespace,
) -> bool:
    channel.saw_delta = False
    try:
        result = await demo_agent.run(message, thread_id=args.thread_id, channel=channel)
    except Exception as exc:
        print(f"loops-demo provider call failed: {exc}", file=sys.stderr)
        return False
    if not channel.saw_delta and result.output:
        print(result.output, file=channel.output_stream, flush=True)
    if channel.saw_delta:
        print(file=channel.output_stream, flush=True)
    if args.show_events:
        print("\n--- events ---", file=channel.output_stream)
        for event in result.events:
            print(event.type, file=channel.output_stream)
        channel.output_stream.flush()
    return True


async def run_demo(args: argparse.Namespace, channel: ConsoleChannel | None = None) -> None:
    message = " ".join(args.message).strip()
    channel = channel or ConsoleChannel(show_events=args.show_events, prompt="" if message else "loops> ")
    demo_agent = create_demo_agent(args, channel)

    if message:
        ok = await run_once(demo_agent, channel, message, args)
        if not ok:
            raise SystemExit(1)
        return

    print("loops demo agent. Type /quit or /exit to leave.", file=channel.output_stream, flush=True)
    async for user_input in channel.receive():
        await run_once(demo_agent, channel, user_input, args)


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the loops DeepSeek sample agent.")
    parser.add_argument(
        "message",
        nargs="*",
        help="Optional one-shot message. Omit it to start the interactive console loop.",
    )
    parser.add_argument("--api-key", default="", help="DeepSeek API key. Prefer LOOPS_DEEPSEEK_API_KEY.")
    parser.add_argument("--base-url", default="", help=f"OpenAI-compatible base URL. Default: {DEFAULT_BASE_URL}")
    parser.add_argument("--model", default="", help=f"Model name. Default: {DEFAULT_MODEL}")
    parser.add_argument(
        "--log-level",
        default="",
        help="Enable runtime logging with this Python log level, e.g. INFO or DEBUG.",
    )
    parser.add_argument(
        "--parallel-tool-calls",
        action="store_true",
        help="Ask the provider to allow multiple tool calls in one model turn.",
    )
    parser.add_argument(
        "--max-parallel-tool-calls",
        type=int,
        default=1,
        help="Runtime tool execution concurrency. Default: 1.",
    )
    parser.add_argument(
        "--thread-id",
        default="console",
        help="Conversation thread id reused by the interactive loop. Default: console",
    )
    parser.add_argument(
        "--disable-verify-ssl",
        action="store_true",
        help="Disable SSL verification for the OpenAI-compatible HTTP client.",
    )
    parser.add_argument(
        "--show-events",
        action="store_true",
        help="Print runtime event names after the streamed response.",
    )
    args = parser.parse_args()
    try:
        asyncio.run(run_demo(args))
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
