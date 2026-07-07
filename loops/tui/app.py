from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Iterable

from loops.hlp import CodexCLIAdapter, FakeAgentAdapter, HLPClient

from .controller import TUIController
from .session import SessionStore


async def run_lines(
    *,
    lines: Iterable[str],
    client: HLPClient,
    session_path: str | Path,
    cwd: str,
    adapter_name: str,
    principal: str = "user_local",
) -> list[str]:
    sessions = SessionStore(session_path)
    session = sessions.create(cwd=cwd, adapter=adapter_name, principal=principal)
    controller = TUIController(client=client, sessions=sessions)
    outputs: list[str] = []

    for line in lines:
        result = await controller.handle(session.id, line)
        outputs.append(result.output)
        if result.should_exit:
            break

    return outputs


def build_client(adapter_name: str) -> HLPClient:
    if adapter_name == "fake":
        return HLPClient(adapter=FakeAgentAdapter())
    if adapter_name == "codex":
        return HLPClient(adapter=CodexCLIAdapter())
    raise ValueError(f"unsupported adapter: {adapter_name}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the HLP TUI channel.")
    parser.add_argument("--adapter", choices=("codex", "fake"), default="codex")
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

    print(f"HLP TUI session {session.id}. Type /help for commands.")
    try:
        while True:
            line = input("> ")
            result = asyncio.run(controller.handle(session.id, line))
            print(result.output)
            if result.should_exit:
                return
    except (EOFError, KeyboardInterrupt):
        print()
        return


if __name__ == "__main__":
    main(sys.argv[1:])
