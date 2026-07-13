from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Awaitable, Iterable
from pathlib import Path
from typing import TypeVar

from loops.hlp import (
    CodexHarnessAdapter,
    FakeAgentAdapter,
    HLPClient,
    PiHarnessAdapter,
)
from loops.hlp.adapters.process import make_streaming_prompt_runner

from .controller import TUIController
from .session import SessionStore
from .stream import StreamPrinter


_SUPPORTED_ADAPTERS = frozenset({"fake", "codex", "pi"})
_DEFAULT_TIMEOUT_S = 60.0
_PROGRESS_EVERY_S = 2.0
T = TypeVar("T")


async def run_lines(
    *,
    lines: Iterable[str],
    client: HLPClient,
    session_path: str | Path,
    cwd: str,
    adapter_name: str,
    principal: str = "user_local",
) -> list[str]:
    _validate_adapter_name(adapter_name)
    sessions = SessionStore(session_path)
    session = sessions.create(cwd=cwd, adapter=adapter_name, principal=principal)
    active_session_id = session.id
    controller = TUIController(client=client, sessions=sessions)
    outputs: list[str] = []

    for line in lines:
        result = await controller.handle(active_session_id, line)
        outputs.append(result.output)
        if result.active_session_id:
            active_session_id = result.active_session_id
        if result.should_exit:
            break

    return outputs


def build_client(
    adapter_name: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT_S,
    stream: bool = True,
    stream_printer=print,
) -> HLPClient:
    _validate_adapter_name(adapter_name)
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if adapter_name == "fake":
        return HLPClient(adapter=FakeAgentAdapter())

    runner = None
    if stream:
        printer = StreamPrinter(printer=stream_printer)

        def on_chunk(chunk) -> None:
            printer(chunk)

        runner = make_streaming_prompt_runner(on_chunk=on_chunk)

    if adapter_name == "codex":
        # Harness-capable path so JSONL human events project into checkpoints/artifacts.
        return HLPClient(adapter=CodexHarnessAdapter(
            command=(
                "codex",
                "exec",
                "--json",
                "--sandbox",
                "read-only",
                "--ephemeral",
                "--skip-git-repo-check",
            ),
            runner=runner,
            timeout=timeout,
            # TUI free-text is chat-first; block/resume stay protocol-shaped.
            prompt_mode="chat",
        ))
    if adapter_name == "pi":
        # Current Pi CLI: `pi --mode json -p --no-session <prompt>`.
        # `--no-tools` keeps the HLP adapter contract non-interactive and avoids
        # long tool loops while the TUI is blocked on one prompt.
        return HLPClient(adapter=PiHarnessAdapter(
            command=(
                "pi",
                "--mode",
                "json",
                "-p",
                "--no-session",
                "--no-tools",
            ),
            runner=runner,
            timeout=timeout,
            prompt_mode="chat",
        ))
    raise AssertionError("unreachable adapter branch")


def _validate_adapter_name(adapter_name: str) -> None:
    if adapter_name not in _SUPPORTED_ADAPTERS:
        raise ValueError(f"unsupported adapter: {adapter_name}")


async def run_with_progress(
    awaitable: Awaitable[T],
    *,
    label: str,
    timeout: float,
    every: float = _PROGRESS_EVERY_S,
    printer=print,
    quiet_after_stream: bool = True,
) -> T:
    """Await work while printing heartbeat lines for interactive TUI use.

    When harness streaming is active, heartbeats are less frequent once the
    first few seconds pass so stream chunks stay readable.
    """
    task = asyncio.ensure_future(awaitable)
    started = time.monotonic()
    printer(f"… {label} (timeout {timeout:.0f}s)", flush=True)
    ticks = 0
    while True:
        done, _pending = await asyncio.wait({task}, timeout=every)
        if done:
            return task.result()
        ticks += 1
        elapsed = time.monotonic() - started
        # After 6s, only ping every other interval if streaming is noisy.
        if quiet_after_stream and elapsed >= 6 and ticks % 2 == 0:
            continue
        printer(
            f"… still waiting on {label} ({elapsed:.0f}s / {timeout:.0f}s)",
            flush=True,
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the HLP TUI channel.")
    parser.add_argument("--adapter", choices=("codex", "fake", "pi"), default="codex")
    parser.add_argument("--session-path", default=".hlp-tui-sessions.json")
    parser.add_argument("--principal", default="user_local")
    parser.add_argument(
        "--timeout",
        type=float,
        default=_DEFAULT_TIMEOUT_S,
        help=(
            "Seconds to wait for the live adapter process before failing "
            f"(default: {_DEFAULT_TIMEOUT_S:.0f}). Offline/fake ignores process wait."
        ),
    )
    args = parser.parse_args(argv)

    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    client = build_client(args.adapter, timeout=args.timeout)
    sessions = SessionStore(args.session_path)
    session = sessions.create(
        cwd=str(Path.cwd()),
        adapter=args.adapter,
        principal=args.principal,
    )
    controller = TUIController(client=client, sessions=sessions)
    active_session_id = session.id
    adapter_timeout = float(getattr(client.adapter, "timeout", args.timeout) or args.timeout)

    print(f"HLP TUI session {session.id}. Type /help for commands.")
    if args.adapter != "fake":
        print(
            f"Live adapter={args.adapter}; first prompt may take up to "
            f"{adapter_timeout:.0f}s while the external CLI runs.",
            flush=True,
        )
    try:
        while True:
            line = input("> ")
            if not line.strip():
                continue
            if args.adapter == "fake":
                result = asyncio.run(controller.handle(active_session_id, line))
            else:
                result = asyncio.run(run_with_progress(
                    controller.handle(active_session_id, line),
                    label=f"{args.adapter} adapter",
                    timeout=adapter_timeout,
                ))
            print(result.output)
            if result.active_session_id:
                active_session_id = result.active_session_id
            if result.should_exit:
                return
    except (EOFError, KeyboardInterrupt):
        print()
        return


if __name__ == "__main__":
    main(sys.argv[1:])
