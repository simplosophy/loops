from __future__ import annotations

import argparse
import asyncio
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from loops.hlp import (
    AgentAdapterError,
    ClaudeCodeCLIAdapter,
    CodexCLIAdapter,
    HLPClient,
    KimiCLIAdapter,
)

Runner = Any


async def run_demo(
    *,
    adapters: tuple[str, ...] = ("codex", "kimi", "claude"),
    runners: dict[str, Runner] | None = None,
    metaworker_config: str | Path | None = None,
    timeout: float = 180.0,
) -> dict[str, dict[str, Any]]:
    """Run HLP delegate through selected local CLI adapters.

    Tests inject runners so this stays dependency-free. Without injected
    runners, the function uses the user's installed Codex, Kimi, and Claude Code
    commands.
    """

    runners = runners or {}
    result: dict[str, dict[str, Any]] = {}
    temp_configs: list[Path] = []
    try:
        for name in adapters:
            adapter = _build_adapter(
                name,
                runner=runners.get(name),
                timeout=timeout,
                metaworker_config=metaworker_config,
                temp_configs=temp_configs,
            )
            client = HLPClient(adapter=adapter)
            task = await client.create_task(
                principal="user_local",
                goal=f"Run {name} local CLI HLP adapter smoke test",
                type="local-cli-smoke",
                acceptance_criteria=(
                    "Return one JSON object",
                    "Preserve the provided HLP correlation_id",
                    "Do not modify workspace files",
                ),
            )
            try:
                run = await client.delegate(
                    task.id,
                    agent_id=f"agent_{name}",
                    capability="local-cli-smoke",
                    input={
                        "goal": task.spec.goal,
                        "instructions": (
                            "This is a smoke test. Do not edit files or run tools. "
                            "Return the required HLP JSON object only."
                        ),
                    },
                )
                payload = adapter.process_results.get(run.run_id, {})
                result[name] = {
                    "status": str(payload.get("status") or "ok"),
                    "task_id": task.id,
                    "run_id": run.run_id,
                    "correlation_id": adapter.task_of_run(run.run_id) or "",
                    "returned_correlation_id": str(payload.get("correlation_id") or ""),
                    "summary": payload.get("summary", ""),
                }
            except AgentAdapterError as exc:
                result[name] = {
                    "status": "error",
                    "task_id": task.id,
                    "run_id": "",
                    "correlation_id": task.id,
                    "error": str(exc),
                    "details": exc.details,
                }
    finally:
        for path in temp_configs:
            path.unlink(missing_ok=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local HLP CLI adapter smoke tests.")
    parser.add_argument(
        "--adapters",
        default="codex,kimi,claude",
        help="Comma-separated adapter names: codex,kimi,claude",
    )
    parser.add_argument(
        "--metaworker-config",
        default=str(Path.home() / ".metaworker/config.yaml"),
        help="Optional metaworker config used to build a temporary kimi-cli config.",
    )
    parser.add_argument(
        "--no-metaworker-config",
        action="store_true",
        help="Do not use metaworker config for Kimi.",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    selected = tuple(
        item.strip()
        for item in args.adapters.split(",")
        if item.strip()
    )
    print(json.dumps(
        asyncio.run(run_demo(
            adapters=selected,
            metaworker_config=None if args.no_metaworker_config else args.metaworker_config,
            timeout=args.timeout,
        )),
        indent=2,
        sort_keys=True,
    ))


def _build_adapter(
    name: str,
    *,
    runner: Runner | None,
    timeout: float,
    metaworker_config: str | Path | None,
    temp_configs: list[Path],
):
    if name == "codex":
        return CodexCLIAdapter(runner=runner, timeout=timeout)
    if name == "kimi":
        command = _kimi_command_from_metaworker(metaworker_config, temp_configs)
        if command is not None:
            return KimiCLIAdapter(command=command, runner=runner, timeout=timeout)
        return KimiCLIAdapter(runner=runner, timeout=timeout)
    if name == "claude":
        return ClaudeCodeCLIAdapter(runner=runner, timeout=timeout)
    raise ValueError(f"unknown local CLI adapter: {name}")


def _kimi_command_from_metaworker(
    config: str | Path | None,
    temp_configs: list[Path],
) -> tuple[str, ...] | None:
    if config is None:
        return None
    path = Path(config).expanduser()
    if not path.exists():
        return None
    values = _read_moonshot_provider(path)
    if values is None:
        return None
    handle = tempfile.NamedTemporaryFile(
        "w",
        prefix="hlp-kimi-",
        suffix=".toml",
        dir="/private/tmp",
        delete=False,
    )
    temp_path = Path(handle.name)
    with handle:
        handle.write(_kimi_cli_config_text(values))
    temp_path.chmod(0o600)
    temp_configs.append(temp_path)
    return ("kimi-cli", "--config-file", str(temp_path), "--quiet", "-p")


def _read_moonshot_provider(path: Path) -> dict[str, str] | None:
    text = path.read_text()
    match = re.search(r"(?ms)^  moonshot:\n(?P<body>.*?)(?=^  \S|\Z)", text)
    if match is None:
        return None
    values: dict[str, str] = {}
    for line in match.group("body").splitlines():
        field = re.match(r"\s+([A-Za-z0-9_-]+):\s*(.*?)\s*$", line)
        if field is None:
            continue
        key, value = field.group(1), field.group(2).strip().strip("\"'")
        values[key] = value
    api_key = values.get("api_key") or values.get("key") or values.get("token")
    base_url = values.get("base_url")
    model = values.get("model")
    if not api_key or not base_url or not model:
        return None
    return {"api_key": api_key, "base_url": base_url, "model": model}


def _kimi_cli_config_text(values: dict[str, str]) -> str:
    return (
        'default_model = "hlp-kimi"\n'
        "default_thinking = false\n"
        "default_yolo = false\n"
        "default_plan_mode = false\n\n"
        '[models."hlp-kimi"]\n'
        'provider = "hlp-moonshot"\n'
        f"model = {json.dumps(values['model'])}\n"
        "max_context_size = 262144\n\n"
        '[providers."hlp-moonshot"]\n'
        'type = "openai_legacy"\n'
        f"base_url = {json.dumps(values['base_url'])}\n"
        f"api_key = {json.dumps(values['api_key'])}\n"
    )


if __name__ == "__main__":
    main()
