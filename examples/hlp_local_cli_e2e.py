from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from loops.hlp import (
    AgentAdapterError,
    ArtifactPayload,
    CheckpointOption,
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
    strict: bool = False,
) -> dict[str, dict[str, Any]]:
    """Run full HLP lifecycle probes through selected local CLI adapters.

    Tests inject runners so this stays dependency-free. Without injected
    runners, the function uses the user's installed Codex, Kimi, and Claude Code
    commands.
    """

    runners = runners or {}
    result: dict[str, dict[str, Any]] = {}
    temp_configs: list[Path] = []
    try:
        for name in adapters:
            adapter: Any | None = None
            try:
                adapter = _build_adapter(
                    name,
                    runner=runners.get(name),
                    timeout=timeout,
                    metaworker_config=metaworker_config,
                    temp_configs=temp_configs,
                )
                client = HLPClient(adapter=adapter)
                result[name] = await _run_adapter_lifecycle(name, adapter, client)
            except AgentAdapterError as exc:
                result[name] = _error_entry(
                    name,
                    adapter=adapter,
                    error=str(exc),
                    details=exc.details,
                )
            except Exception as exc:
                result[name] = _error_entry(
                    name,
                    adapter=adapter,
                    error=str(exc),
                    details={"error_type": exc.__class__.__name__},
                )
    finally:
        for path in temp_configs:
            path.unlink(missing_ok=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local HLP CLI adapter lifecycle tests.")
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
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when any selected adapter reports an error.",
    )
    args = parser.parse_args()

    selected = tuple(item.strip() for item in args.adapters.split(",") if item.strip())
    result = asyncio.run(
        run_demo(
            adapters=selected,
            metaworker_config=None if args.no_metaworker_config else args.metaworker_config,
            timeout=args.timeout,
            strict=args.strict,
        )
    )
    print(
        json.dumps(
            result,
            indent=2,
            sort_keys=True,
        )
    )
    if args.strict and any(entry.get("status") != "ok" for entry in result.values()):
        sys.exit(1)


async def _run_adapter_lifecycle(
    name: str,
    adapter: Any,
    client: HLPClient,
) -> dict[str, Any]:
    task_id = ""
    run_id = ""
    correlation_id = ""
    try:
        task = await client.create_task(
            principal="user_local",
            goal=f"Run {name} local CLI HLP adapter full lifecycle",
            type="local-cli-e2e",
            acceptance_criteria=(
                "Return one JSON object",
                "Preserve the provided HLP correlation_id",
                "Do not modify workspace files",
            ),
        )
        task_id = task.id
        correlation_id = task.id
        run = await client.delegate(
            task.id,
            agent_id=f"agent_{name}",
            capability="local-cli-e2e",
            input={
                "goal": task.spec.goal,
                "instructions": (
                    "Exercise the HLP adapter boundary only. Do not edit files or run tools. "
                    "Return the required HLP JSON object only."
                ),
            },
        )
        run_id = run.run_id
        correlation_id = adapter.task_of_run(run.run_id) or task.id
        await client.start(task.id)
        await client.amend(
            task.id,
            by="user_local",
            text="Keep the response JSON-only and preserve the supplied correlation_id.",
        )
        checkpoint = await client.raise_checkpoint(
            task_id=task.id,
            kind="choice",
            prompt="Choose a low-risk execution path for the HLP adapter probe.",
            options=(
                CheckpointOption(id="safe", label="Use read-only validation", risk="low"),
                CheckpointOption(id="fast", label="Skip validation", risk="medium"),
            ),
            raised_by=f"agent_{name}",
        )
        checkpoint = await client.resolve_checkpoint(
            checkpoint.id,
            by="user_local",
            action="choose",
            choice="safe",
            comment="Use the deterministic low-risk path.",
        )
        artifact = await client.commit_artifact(
            task_id=task.id,
            type="report",
            payload=ArtifactPayload(
                kind="inline",
                uri=f"mem://hlp-{name}-report-v1",
                checksum=f"sha256:hlp-{name}-report-v1",
            ),
            produced_by=f"agent_{name}",
        )
        review = await client.submit_review(
            task_id=task.id,
            artifact_id=artifact.id,
            reviewer="user_local",
            verdict="approved",
        )
        ledger_entry = await client.write_ledger(
            f"project:hlp-{name}",
            "local-cli.status",
            "approved",
            by=task.id,
        )
        history = await client.replay_audit(task.id)
        final_task = await client.get_task(task.id)
        payload = dict(adapter.process_results.get(run.run_id, {}))

        control_task = await client.create_task(
            principal="user_local",
            goal=f"Run {name} local CLI HLP handoff/cancel control path",
            type="local-cli-control",
            acceptance_criteria=("Handoff and cancellation are propagated to the adapter",),
        )
        control_run = await client.delegate(
            control_task.id,
            agent_id=f"agent_{name}_primary",
            capability="local-cli-control",
            input={"goal": control_task.spec.goal},
        )
        await client.start(control_task.id)
        await client.operations.ownership_transfer(
            control_task.id,
            to=f"agent_{name}_handoff",
            via="handoff",
            actor="user_local",
        )
        handoff_run_id = client.store.run_of_task(control_task.id) or ""
        control_task = await client.operations.task_cancel(
            control_task.id,
            by="user_local",
        )
    except AgentAdapterError as exc:
        return _error_entry(
            name,
            adapter=adapter,
            task_id=task_id,
            run_id=run_id,
            correlation_id=correlation_id,
            error=str(exc),
            details=exc.details,
        )

    adapter_status = str(payload.get("status") or "ok")
    returned_correlation_id = str(payload.get("correlation_id") or "")
    entry: dict[str, Any] = {
        "status": adapter_status,
        "adapter": name,
        "task_id": task.id,
        "run_id": run.run_id,
        "correlation_id": correlation_id,
        "returned_correlation_id": returned_correlation_id,
        "adapter_operations": _adapter_operations(adapter),
        "final_task_state": final_task.state,
        "checkpoint_id": checkpoint.id,
        "checkpoint_decision": checkpoint.resolution.choice if checkpoint.resolution else None,
        "artifact_id": artifact.id,
        "artifact_version": artifact.version,
        "review_id": review.id,
        "review_verdict": review.verdict,
        "ledger_status": ledger_entry.value,
        "audit_actions": [event.action for event in history],
        "control_task_id": control_task.id,
        "control_run_id": control_run.run_id,
        "handoff_run_id": handoff_run_id,
        "control_final_task_state": control_task.state,
        "summary": payload.get("summary", ""),
    }
    if adapter_status != "ok":
        entry["error"] = str(payload.get("error") or "adapter returned non-ok status")
        entry["details"] = payload.get("details") or payload
    return entry


def _error_entry(
    name: str,
    *,
    adapter: Any | None,
    error: str,
    details: dict[str, Any],
    task_id: str = "",
    run_id: str = "",
    correlation_id: str = "",
) -> dict[str, Any]:
    return {
        "status": "error",
        "adapter": name,
        "task_id": task_id,
        "run_id": run_id,
        "correlation_id": correlation_id,
        "returned_correlation_id": "",
        "adapter_operations": _adapter_operations(adapter),
        "error": error,
        "details": details,
    }


def _adapter_operations(adapter: Any) -> list[str]:
    if adapter is None:
        return []
    return [
        name
        for name, _payload in getattr(adapter, "calls", ())
        if name in {"delegate", "steer", "block", "resume", "handoff", "cancel"}
    ]


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
