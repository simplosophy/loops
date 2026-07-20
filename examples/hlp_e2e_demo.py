from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from examples.hlp_local_cli_e2e import run_demo as run_local_cli_demo


async def run_demo(
    *,
    adapter: str = "codex",
    runner: Any | None = None,
    timeout: float = 180.0,
    strict: bool = False,
) -> dict[str, Any]:
    runners = {adapter: runner} if runner is not None else None
    result = await run_local_cli_demo(
        adapters=(adapter,),
        runners=runners,
        metaworker_config=None,
        timeout=timeout,
        strict=strict,
    )
    return result[adapter]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run an HLP lifecycle demo through local CLI adapters."
    )
    parser.add_argument(
        "--adapters",
        default="codex",
        help="Comma-separated adapter names: codex,kimi,claude",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when any selected adapter reports an error.",
    )
    args = parser.parse_args()

    selected = tuple(item.strip() for item in args.adapters.split(",") if item.strip())
    if len(selected) == 1:
        result = asyncio.run(
            run_demo(
                adapter=selected[0],
                timeout=args.timeout,
                strict=args.strict,
            )
        )
        failed = result.get("status") != "ok"
    else:
        result = asyncio.run(
            run_local_cli_demo(
                adapters=selected,
                metaworker_config=None,
                timeout=args.timeout,
                strict=args.strict,
            )
        )
        failed = any(entry.get("status") != "ok" for entry in result.values())
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.strict and failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
