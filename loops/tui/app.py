from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path

from loops.hlp import (
    ClaudeCodeHarnessAdapter,
    CodexHarnessAdapter,
    FakeAgentAdapter,
    HLPClient,
    HumanLoopStore,
    KimiHarnessAdapter,
    PiHarnessAdapter,
    ProtocolError,
)
from loops.hlp.adapters.process import StreamChunk, make_streaming_prompt_runner

from .console import Console, adapter_completions
from .controller import TUIController
from .render import render_inbox, render_status
from .session import SessionStore
from .stream import StreamPrinter

_SUPPORTED_ADAPTERS = frozenset({"fake", "codex", "pi", "claude", "kimi"})
_DEFAULT_TIMEOUT_S = 60.0
_PROGRESS_EVERY_S = 2.0


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
    controller = TUIController(
        client=client,
        sessions=sessions,
        adapter_builder=lambda name, model, store: build_client(name, model=model, store=store),
    )
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
    stream_printer: Callable[..., None] = print,
    model: str = "",
    store: HumanLoopStore | None = None,
) -> HLPClient:
    _validate_adapter_name(adapter_name)
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    store = store or HumanLoopStore()
    if adapter_name == "fake":
        return HLPClient(store=store, adapter=FakeAgentAdapter())

    runner = None
    if stream:
        printer = StreamPrinter(printer=stream_printer)

        def on_chunk(chunk: StreamChunk) -> None:
            printer(chunk)

        runner = make_streaming_prompt_runner(on_chunk=on_chunk)

    if adapter_name == "codex":
        # Harness-capable path so JSONL human events project into checkpoints/artifacts.
        # No --ephemeral: sessions must be recorded for resume continuity.
        command: tuple[str, ...] = (
            "codex",
            "exec",
            "--json",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
        )
        if model:
            command = (*command, "-m", model)
        return HLPClient(
            store=store,
            adapter=CodexHarnessAdapter(
                command=command,
                runner=runner,
                timeout=timeout,
                # TUI free-text is chat-first; block/resume stay protocol-shaped.
                prompt_mode="chat",
            ),
        )
    if adapter_name == "pi":
        # Current Pi CLI: `pi --mode json -p --no-session <prompt>`.
        # `--no-tools` keeps the HLP adapter contract non-interactive and avoids
        # long tool loops while the TUI is blocked on one prompt.
        command = (
            "pi",
            "--mode",
            "json",
            "-p",
            "--no-session",
            "--no-tools",
        )
        if model:
            command = (*command, "--model", model)
        return HLPClient(
            store=store,
            adapter=PiHarnessAdapter(
                command=command,
                runner=runner,
                timeout=timeout,
                prompt_mode="chat",
            ),
        )
    if adapter_name == "claude":
        # Claude Code stream-json: system/assistant/result JSONL envelopes.
        command = (
            "claude",
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "dontAsk",
        )
        if model:
            command = (*command, "--model", model)
        return HLPClient(
            store=store,
            adapter=ClaudeCodeHarnessAdapter(
                command=command,
                runner=runner,
                timeout=timeout,
                prompt_mode="chat",
            ),
        )
    if adapter_name == "kimi":
        # Kimi stream-json: role-shaped assistant/meta lines.
        command = ("kimi", "--output-format", "stream-json", "-p")
        if model:
            command = (*command, "-m", model)
        return HLPClient(
            store=store,
            adapter=KimiHarnessAdapter(
                command=command,
                runner=runner,
                timeout=timeout,
                prompt_mode="chat",
            ),
        )
    raise AssertionError("unreachable adapter branch")


def _validate_adapter_name(adapter_name: str) -> None:
    if adapter_name not in _SUPPORTED_ADAPTERS:
        raise ValueError(f"unsupported adapter: {adapter_name}")


async def run_with_progress[T](
    awaitable: Awaitable[T],
    *,
    label: str,
    timeout: float,
    every: float = _PROGRESS_EVERY_S,
    printer: Callable[..., None] = print,
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
    parser.add_argument(
        "--adapter",
        choices=("codex", "fake", "pi", "claude", "kimi"),
        default="codex",
    )
    parser.add_argument("--session-path", default=".hlp-tui-sessions.json")
    parser.add_argument("--principal", default="user_local")
    parser.add_argument("--model", default="", help="Model name passed to the CLI harness.")
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colors (also honored: NO_COLOR env and non-TTY output).",
    )
    parser.add_argument(
        "--resume",
        default="",
        help="Resume an existing session id instead of starting a new one.",
    )
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

    client = build_client(args.adapter, timeout=args.timeout, model=args.model)
    sessions = SessionStore(args.session_path)
    if args.resume:
        try:
            session = sessions.resume(args.resume)
        except KeyError:
            parser.error(f"unknown session: {args.resume}")
    else:
        session = sessions.create(
            cwd=str(Path.cwd()),
            adapter=args.adapter,
            principal=args.principal,
        )
    controller = TUIController(
        client=client,
        sessions=sessions,
        adapter_builder=lambda name, model, store: build_client(
            name,
            timeout=args.timeout,
            model=model,
            store=store,
        ),
    )
    active_session_id = session.id
    adapter_timeout = float(getattr(client.adapter, "timeout", args.timeout) or args.timeout)
    console = Console(
        history_path=f"{args.session_path}.history",
        color=not args.no_color,
        completer_extra=lambda command: adapter_completions() if command == "adapter" else [],
    )

    inbox_count = len(asyncio.run(client.human_inbox(session.principal)))
    console.print(
        f"HLP TUI session {session.id} | adapter={args.adapter} "
        f"principal={session.principal} | inbox={inbox_count} open | /help for commands",
        role="dim",
    )
    if inbox_count:
        console.print(asyncio.run(_render_open_inbox(client, session.principal)), role="warn")
    if args.adapter != "fake":
        console.print(
            f"Live adapter={args.adapter}; first prompt may take up to "
            f"{adapter_timeout:.0f}s while the external CLI runs.",
            role="dim",
        )
    try:
        while True:
            line = console.input(console.style("> ", "accent"))
            if not line.strip():
                continue
            try:
                current_adapter = sessions.resume(active_session_id).adapter
                if args.adapter == "fake":
                    result = asyncio.run(controller.handle(active_session_id, line))
                else:
                    result = asyncio.run(
                        run_with_progress(
                            controller.handle(active_session_id, line),
                            label=f"{current_adapter} adapter",
                            timeout=adapter_timeout,
                        )
                    )
            except KeyboardInterrupt:
                console.print(
                    asyncio.run(
                        _interrupt_active(controller, active_session_id, session.principal)
                    ),
                    role="warn",
                )
                continue
            print(result.output)
            if result.active_session_id:
                active_session_id = result.active_session_id
            console.print(
                asyncio.run(_status_snapshot(controller, active_session_id)),
                role="dim",
            )
            if result.should_exit:
                return
    except (EOFError, KeyboardInterrupt):
        print()
        return


async def _render_open_inbox(client: HLPClient, principal: str) -> str:
    return render_inbox(await client.human_inbox(principal))


async def _status_snapshot(controller: TUIController, session_id: str) -> str:
    """Dim per-turn status line: adapter, active task state, open inbox."""
    session = controller.sessions.resume(session_id)
    task_state = "none"
    if session.active_task_id:
        task_state = (await controller.client.get_task(session.active_task_id)).state
    inbox = await controller.client.human_inbox(session.principal)
    return render_status(session, task_state=task_state, inbox_count=len(inbox))


async def _interrupt_active(
    controller: TUIController,
    session_id: str,
    principal: str,
) -> str:
    """Ctrl+C semantics: seize control — interrupt the active task instead of dying."""
    try:
        session = controller.sessions.resume(session_id)
    except KeyError:
        return "interrupted (unknown session)"
    if not session.active_task_id:
        return "interrupted (no active task to interrupt)"
    try:
        checkpoint = await controller.client.interrupt(
            session.active_task_id,
            by=principal,
            prompt="user interrupt (Ctrl+C)",
        )
    except ProtocolError as exc:
        return f"interrupt failed: {exc}"
    return (
        f"interrupted: checkpoint {checkpoint.id} raised, task blocked. "
        "Resolve with /approve, /reject, or free text to steer."
    )


if __name__ == "__main__":
    main(sys.argv[1:])
