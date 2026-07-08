from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Iterable

from loops.hlp import CodexCLIAdapter, FakeAgentAdapter, HLPClient, PiHarnessAdapter

from .controller import TUIController
from .session import SessionStore


_SUPPORTED_ADAPTERS = frozenset({"fake", "codex", "pi"})


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


def build_client(adapter_name: str) -> HLPClient:
    _validate_adapter_name(adapter_name)
    if adapter_name == "fake":
        return HLPClient(adapter=FakeAgentAdapter())
    if adapter_name == "codex":
        return HLPClient(adapter=CodexCLIAdapter())
    if adapter_name == "pi":
        return HLPClient(adapter=PiHarnessAdapter())
    raise AssertionError("unreachable adapter branch")


def _validate_adapter_name(adapter_name: str) -> None:
    if adapter_name not in _SUPPORTED_ADAPTERS:
        raise ValueError(f"unsupported adapter: {adapter_name}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the HLP TUI channel.")
    parser.add_argument("--adapter", choices=("codex", "fake", "pi"), default="codex")
    parser.add_argument("--session-path", default=".hlp-tui-sessions.json")
    parser.add_argument("--principal", default="user_local")
    args = parser.parse_args(argv)

    client = build_client(args.adapter)
    sessions = SessionStore(args.session_path)
    session = sessions.create(
        cwd=str(Path.cwd()),
        adapter=args.adapter,
        principal=args.principal,
    )
    controller = TUIController(client=client, sessions=sessions)
    active_session_id = session.id

    print(f"HLP TUI session {session.id}. Type /help for commands.")
    try:
        while True:
            line = input("> ")
            result = asyncio.run(controller.handle(active_session_id, line))
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
