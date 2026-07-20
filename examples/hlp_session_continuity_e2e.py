"""Live session-continuity E2E for the four first-party CLI harness adapters.

Per CLI, proves true native-session continuity with the local installed CLIs:
delegate asks the model to remember a codeword; block/resume/steer then resume
the same native session (codex exec resume / claude --resume / kimi --session /
pi --session) and the model must recite the codeword from session context —
impossible if a fresh process were spawned.

Run directly:  uv run python examples/hlp_session_continuity_e2e.py
Via pytest:    HLP_RUN_EXTERNAL_CLI_E2E=1 uv run pytest \
               tests/external/test_hlp_session_continuity_real_cli.py -q
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loops.hlp import (
    ClaudeCodeHarnessAdapter,
    CodexHarnessAdapter,
    KimiHarnessAdapter,
    PiHarnessAdapter,
)
from loops.hlp.adapters.process import run_prompt_process

CODEWORD = "XJ42-QZ-2026"


def _adapters() -> dict[str, Any]:
    return {
        "codex": CodexHarnessAdapter(timeout=150.0),
        "claude": ClaudeCodeHarnessAdapter(timeout=150.0),
        "kimi": KimiHarnessAdapter(timeout=150.0),
        "pi": PiHarnessAdapter(timeout=150.0),
    }


def _spy(commands: list[tuple[str, ...]]):
    async def runner(command, request, timeout):
        commands.append(command)
        return await run_prompt_process(command, request, timeout)

    return runner


async def probe_one(name: str, adapter: Any, *, codeword: str = CODEWORD) -> dict[str, Any]:
    """Run the codeword continuity probe against one live CLI harness adapter."""
    commands: list[tuple[str, ...]] = []
    # Rebuild the adapter with a spying runner so resume commands are captured.
    adapter = adapter.__class__(
        runner=_spy(commands),
        timeout=getattr(adapter, "timeout", 150.0),
    )
    entry: dict[str, Any] = {"adapter": name, "status": "ok"}
    try:
        run_id = await adapter.delegate(
            f"task_live_{name}_continuity",
            f"agent_{name}",
            "continuity-probe",
            input={
                "goal": (
                    f"记住暗号 {codeword}。只回 HLP JSON 信封"
                    "（run_id/correlation_id/status/summary/error），summary 写 ack。"
                ),
            },
        )
        session_id = adapter.session_of_run(run_id)

        await adapter.block(run_id, f"ckpt_live_{name}", "continuity pause")
        await adapter.resume(run_id, {"action": "approve", "by": "user_local"})
        await adapter.steer(
            run_id,
            {
                "text": ("复述你之前记住的暗号。仍回 JSON 信封，summary 里只写暗号本身。"),
            },
        )
        payload = adapter.process_results.get(run_id, {})
        summary = str(payload.get("summary") or "")
        found = codeword in summary or codeword in json.dumps(payload, ensure_ascii=False)

        resume_marks = {
            "codex": ("codex", "exec", "resume"),
            "claude": ("claude", "--resume"),
            "kimi": ("kimi", "--output-format", "stream-json", "--session"),
            "pi": ("pi", "--mode", "json", "--session"),
        }[name]
        followups = commands[1:]
        resumed = [c for c in followups if c[: len(resume_marks)] == resume_marks]

        entry.update(
            {
                "run_id": run_id,
                "session_id": session_id,
                "followup_ops": len(followups),
                "resumed_ops": len(resumed),
                "codeword_found": found,
                "summary": summary[:200],
            }
        )
        if not session_id:
            entry["status"] = "error"
            entry["error"] = "no native session id captured from wire"
        elif not found:
            entry["status"] = "error"
            entry["error"] = "codeword not recited after session resume"
        elif len(resumed) != len(followups) or not followups:
            entry["status"] = "error"
            entry["error"] = (
                f"only {len(resumed)}/{len(followups)} follow-up ops used the resume command"
            )
    except Exception as exc:  # noqa: BLE001 - probe reports instead of raising
        entry["status"] = "error"
        entry["error"] = f"{exc.__class__.__name__}: {exc}"
    return entry


async def run_demo(*, adapters: tuple[str, ...] = ("codex", "claude", "kimi", "pi")) -> dict:
    available = _adapters()
    result = {}
    for name in adapters:
        result[name] = await probe_one(name, available[name])
    return result


def main() -> None:
    import sys

    result = asyncio.run(run_demo())
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    if any(entry["status"] != "ok" for entry in result.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
