"""`loops-hlp-serve` console entry: serve HLP over the HTTP reference binding."""

from __future__ import annotations

import argparse

from loops.hlp import (
    ClaudeCodeHarnessAdapter,
    CodexHarnessAdapter,
    FakeAgentAdapter,
    KimiHarnessAdapter,
    PiHarnessAdapter,
)
from loops.hlp.operations import HumanLoopOperations
from loops.hlp.sqlite_store import SQLiteHumanLoopStore
from loops.hlp.store import HumanLoopStore
from loops.hlp.transport import HLPHttpServer

_ADAPTERS = {
    "fake": FakeAgentAdapter,
    "codex": CodexHarnessAdapter,
    "pi": PiHarnessAdapter,
    "claude": ClaudeCodeHarnessAdapter,
    "kimi": KimiHarnessAdapter,
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Serve HLP over the HTTP reference binding.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8471)
    parser.add_argument(
        "--adapter",
        choices=tuple(_ADAPTERS),
        default="fake",
        help="Harness adapter wired into the served operations (default: fake).",
    )
    parser.add_argument(
        "--store",
        default="",
        help="SQLite snapshot path for persistence; empty means in-memory.",
    )
    args = parser.parse_args(argv)

    store = SQLiteHumanLoopStore(args.store) if args.store else HumanLoopStore()
    operations = HumanLoopOperations(store=store, adapter=_ADAPTERS[args.adapter]())
    server = HLPHttpServer(operations, host=args.host, port=args.port).start()
    print(f"HLP HTTP transport listening on {server.address} (adapter={args.adapter})")
    print("Endpoints: POST /v1/ops/<object.verb>, GET /v1/events, /v1/version, /v1/health")
    try:
        import time

        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


if __name__ == "__main__":
    main()
