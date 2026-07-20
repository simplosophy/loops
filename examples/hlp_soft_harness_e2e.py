"""Soft-control E2E through real or injected harness adapters.

Industrial soft bar for this entrypoint:
- Multi soft signals merge on the host (D2)
- ``task.amend`` / adapter ``steer`` with promotion provenance
- Soft alone does not change Task.state (D1)
- BCI-alone high-risk hard resolve denied (D3, offline guard)
- Task.id preserved as correlation_id on adapter I/O

Default CI uses injected runners (no network). Live PATH harnesses run when no
runner is injected and the binary exists (see ``HLP_RUN_EXTERNAL_CLI_E2E=1``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from typing import Any

from loops.hlp import (
    AgentAdapterError,
    ClaudeCodeHarnessAdapter,
    CodexCLIAdapter,
    CodexHarnessAdapter,
    ControlSignal,
    HLPClient,
    InteractionRef,
    KimiHarnessAdapter,
    PiHarnessAdapter,
    ProcessResult,
    ProtocolError,
    assert_soft_does_not_change_task_state,
    merge_soft_control_signals,
    require_hard_resolve_allowed,
)

Runner = Any

_DEFAULT_ADAPTERS = ("codex", "pi", "claude", "kimi")


async def run_soft_e2e(
    *,
    adapters: tuple[str, ...] = ("codex", "pi"),
    runners: dict[str, Runner] | None = None,
    timeout: float = 120.0,
    prompt_mode: str = "chat",
) -> dict[str, dict[str, Any]]:
    """Run soft multi-merge + amend/steer for each adapter.

    When ``runners`` provides a name, that adapter is offline/injected.
    When missing, the installed CLI is used (live).
    """
    runners = runners or {}
    result: dict[str, dict[str, Any]] = {}
    for name in adapters:
        adapter: Any | None = None
        try:
            if name not in runners and not _binary_available(name):
                result[name] = {
                    "status": "skipped",
                    "adapter": name,
                    "error": f"{name} not on PATH",
                    "mode": "live",
                }
                continue
            adapter = _build_adapter(
                name,
                runner=runners.get(name),
                timeout=timeout,
                prompt_mode=prompt_mode,
            )
            mode = "offline" if name in runners else "live"
            result[name] = await _run_soft_lifecycle(name, adapter, mode=mode)
        except AgentAdapterError as exc:
            result[name] = _error_entry(
                name,
                adapter=adapter,
                error=str(exc),
                details=dict(exc.details or {}),
                mode="offline" if name in runners else "live",
            )
        except Exception as exc:
            result[name] = _error_entry(
                name,
                adapter=adapter,
                error=str(exc),
                details={"error_type": exc.__class__.__name__},
                mode="offline" if name in runners else "live",
            )
    return result


def inventory_harnesses() -> dict[str, dict[str, Any]]:
    """Report which supported harness binaries are installed."""
    return {
        name: {
            "available": _binary_available(name),
            "path": shutil.which(_binary_name(name)),
        }
        for name in _DEFAULT_ADAPTERS
    }


async def _run_soft_lifecycle(
    name: str,
    adapter: Any,
    *,
    mode: str,
) -> dict[str, Any]:
    client = HLPClient(adapter=adapter)
    interaction = InteractionRef(
        channel=f"soft-e2e-{name}",
        session_id=f"sess_{name}",
        episode_id="soft_multi",
    )

    task = await client.create_task(
        principal="user_local",
        goal=(
            f"Soft-control E2E for {name}: respond with one JSON object only; "
            "preserve correlation_id; do not edit workspace files."
        ),
        type="soft-harness-e2e",
        acceptance_criteria=(
            "JSON-only adapter boundary response",
            "Preserve HLP correlation_id",
            "Accept soft steering without blocking",
        ),
    )
    run = await client.delegate(
        task.id,
        agent_id=f"agent_{name}",
        capability="soft-e2e",
        input={
            "goal": task.spec.goal,
            "instructions": (
                "HLP soft E2E probe. Return one JSON object with run_id, "
                "correlation_id, status, and summary. Do not modify files."
            ),
        },
    )
    await client.start(task.id)
    started = await client.get_task(task.id)
    state_before = started.state
    correlation = adapter.task_of_run(run.run_id) or task.id

    soft_burst = (
        ControlSignal(
            strength="soft",
            intent="constrain",
            principal_binding="user_local",
            confidence=0.91,
            source_kind="speech",
            text="Keep the answer JSON-only",
            interaction=interaction,
            run_id=run.run_id,
        ),
        ControlSignal(
            strength="soft",
            intent="constrain",
            principal_binding="user_local",
            confidence=0.93,
            source_kind="speech",
            text="Preserve the supplied correlation_id exactly",
            interaction=interaction,
            run_id=run.run_id,
        ),
        ControlSignal(
            strength="soft",
            intent="clarify",
            principal_binding="user_local",
            confidence=0.15,
            source_kind="speech",
            text="uh-huh",
            interaction=interaction,
            run_id=run.run_id,
        ),
    )
    promoted = merge_soft_control_signals(
        soft_burst,
        by="user_local",
        intent="constrain",
    )
    amended = await client.amend(
        task.id,
        by="user_local",
        text=promoted.amendment.text,
        intent="constrain",
        promotion_provenance=promoted.provenance,
    )
    assert_soft_does_not_change_task_state(state_before, amended.state)

    # D3 offline guard (always; no BCI hardware).
    bci = ControlSignal(
        strength="hard",
        intent="affirm",
        principal_binding="user_local",
        confidence=0.99,
        source_kind="bci",
        text="approve",
    )
    bci_alone_denied = False
    bci_error = ""
    try:
        require_hard_resolve_allowed(
            bci,
            high_risk=True,
            second_factor_present=False,
        )
    except ProtocolError as exc:
        bci_alone_denied = True
        bci_error = f"{exc.code}: {exc.message}"

    history = await client.replay_audit(task.id)
    amended_events = [e for e in history if e.action == "task.amended"]
    promotion = {}
    if amended_events and isinstance(amended_events[-1].after, dict):
        promotion = amended_events[-1].after.get("promotion") or {}

    ops = [
        op
        for op, _payload in getattr(adapter, "calls", ())
        if op in {"delegate", "steer", "block", "resume", "handoff", "cancel"}
    ]
    process_payload = dict(getattr(adapter, "process_results", {}).get(run.run_id, {}))

    return {
        "status": "ok",
        "mode": mode,
        "adapter": name,
        "adapter_class": adapter.__class__.__name__,
        "task_id": task.id,
        "run_id": run.run_id,
        "correlation_id": correlation,
        "returned_correlation_id": str(process_payload.get("correlation_id") or ""),
        "task_state_before_soft": state_before,
        "task_state_after_soft": amended.state,
        "steering_text": amended.steering_log[-1].text if amended.steering_log else "",
        "soft_signals_in": len(soft_burst),
        "soft_signals_promoted": len(promoted.signals),
        "promotion_profile": promotion.get("profile"),
        "promotion_signal_count": promotion.get("signal_count"),
        "adapter_operations": ops,
        "steer_called": "steer" in ops,
        "summary": process_payload.get("summary", ""),
        "bci_alone_high_risk_denied": bci_alone_denied,
        "bci_alone_error": bci_error,
        "decisions": {
            "D1_soft_no_state_change": (
                state_before == amended.state and amended.state == "in_progress"
            ),
            "D2_host_merge": (
                len(promoted.signals) == 2 and "uh-huh" not in promoted.amendment.text
            ),
            "D3_bci_alone_denied": bci_alone_denied,
            "correlation_preserved": correlation == task.id,
        },
    }


def _error_entry(
    name: str,
    *,
    adapter: Any | None,
    error: str,
    details: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    ops = (
        [
            op
            for op, _payload in getattr(adapter, "calls", ())
            if op in {"delegate", "steer", "block", "resume", "handoff", "cancel"}
        ]
        if adapter is not None
        else []
    )
    return {
        "status": "error",
        "mode": mode,
        "adapter": name,
        "adapter_class": adapter.__class__.__name__ if adapter else "",
        "adapter_operations": ops,
        "error": error,
        "details": details,
        "decisions": {},
    }


def _build_adapter(
    name: str,
    *,
    runner: Runner | None,
    timeout: float,
    prompt_mode: str,
):
    if name == "codex":
        # Prefer harness adapter for soft/chat steer path when live or injected.
        return CodexHarnessAdapter(
            runner=runner,
            timeout=timeout,
            prompt_mode=prompt_mode,
        )
    if name == "pi":
        return PiHarnessAdapter(
            runner=runner,
            timeout=timeout,
            prompt_mode=prompt_mode,
        )
    if name == "claude":
        return ClaudeCodeHarnessAdapter(
            runner=runner,
            timeout=timeout,
            prompt_mode=prompt_mode,
        )
    if name == "kimi":
        return KimiHarnessAdapter(
            runner=runner,
            timeout=timeout,
            prompt_mode=prompt_mode,
        )
    # Fallback codex-cli (protocol-only) if explicitly requested as "codex-cli"
    if name == "codex-cli":
        return CodexCLIAdapter(runner=runner, timeout=timeout)
    raise ValueError(f"unknown soft e2e adapter: {name}")


def _binary_name(adapter: str) -> str:
    return {
        "codex": "codex",
        "pi": "pi",
        "claude": "claude",
        "kimi": "kimi",
        "codex-cli": "codex",
    }.get(adapter, adapter)


def _binary_available(adapter: str) -> bool:
    return shutil.which(_binary_name(adapter)) is not None


def _soft_injected_runner(name: str):
    """Deterministic runner for offline soft E2E (industrial CI)."""

    async def runner(command, request, timeout):
        correlation = str(request.get("correlation_id") or "")
        run_id = str(request.get("run_id") or f"{name}_soft_run")
        op = request.get("operation")
        if op == "delegate":
            return ProcessResult(
                exit_code=0,
                stdout=json.dumps(
                    {
                        "run_id": run_id,
                        "correlation_id": correlation,
                        "status": "ok",
                        "summary": f"{name} soft e2e delegate accepted",
                    }
                ),
                stderr="",
            )
        if op == "steer":
            # Chat-mode steer should carry merged soft text in the prompt arg.
            prompt = command[-1] if command else ""
            assert (
                "Keep the answer JSON-only" in prompt
                or "JSON-only" in prompt
                or (
                    isinstance(request.get("amendment"), dict)
                    and "JSON-only" in str(request.get("amendment"))
                )
                or "correlation_id" in prompt
            )
            return ProcessResult(
                exit_code=0,
                stdout=json.dumps(
                    {
                        "run_id": run_id,
                        "correlation_id": correlation,
                        "status": "ok",
                        "summary": f"{name} soft steer applied",
                    }
                ),
                stderr="",
            )
        return ProcessResult(
            exit_code=0,
            stdout=json.dumps(
                {
                    "run_id": run_id,
                    "correlation_id": correlation,
                    "status": "ok",
                }
            ),
            stderr="",
        )

    return runner


def default_offline_runners(
    adapters: tuple[str, ...] = ("codex", "pi"),
) -> dict[str, Runner]:
    return {name: _soft_injected_runner(name) for name in adapters}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Soft-control E2E for HLP SDK (multi soft → merge → amend/steer). "
            "Default is offline injected runners; use --live for PATH harnesses."
        ),
    )
    parser.add_argument(
        "--adapters",
        default="codex,pi",
        help="Comma-separated: codex,pi,claude,kimi",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use real installed CLIs (no injected runners).",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any adapter is not status=ok (skipped is not ok).",
    )
    parser.add_argument(
        "--inventory",
        action="store_true",
        help="Print installed harness inventory and exit.",
    )
    args = parser.parse_args()

    if args.inventory:
        print(json.dumps(inventory_harnesses(), indent=2, sort_keys=True))
        return

    selected = tuple(item.strip() for item in args.adapters.split(",") if item.strip())
    runners = None if args.live else default_offline_runners(selected)
    result = asyncio.run(
        run_soft_e2e(
            adapters=selected,
            runners=runners,
            timeout=args.timeout,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.strict:
        bad = {name: entry for name, entry in result.items() if entry.get("status") != "ok"}
        if bad:
            sys.exit(1)


if __name__ == "__main__":
    main()
