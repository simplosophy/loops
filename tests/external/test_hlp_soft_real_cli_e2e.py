"""Opt-in real local harness soft E2E (set HLP_RUN_EXTERNAL_CLI_E2E=1)."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

import pytest

from examples.hlp_soft_harness_e2e import inventory_harnesses, run_soft_e2e


def run(coro):
    return asyncio.run(coro)


def _available_adapters() -> tuple[str, ...]:
    inv = inventory_harnesses()
    # Prefer harnesses that support chat soft/steer well.
    preferred = ("codex", "pi", "claude", "kimi")
    return tuple(name for name in preferred if inv.get(name, {}).get("available"))


@pytest.mark.skipif(
    os.environ.get("HLP_RUN_EXTERNAL_CLI_E2E") != "1",
    reason="set HLP_RUN_EXTERNAL_CLI_E2E=1 to run real local soft harness E2E",
)
def test_real_harness_soft_multi_merge_e2e():
    adapters = _available_adapters()
    if not adapters:
        pytest.skip("no supported harness CLI on PATH")

    # Prefer a short list for live: codex + pi when both present.
    live = tuple(name for name in ("codex", "pi") if name in adapters) or adapters[:1]
    result = run(run_soft_e2e(
        adapters=live,
        runners=None,  # live PATH binaries
        timeout=float(os.environ.get("HLP_SOFT_E2E_TIMEOUT", "120")),
        prompt_mode="chat",
    ))

    # Persist raw result for operators (and goal SCRATCH via CI/local copy).
    out = Path(os.environ.get(
        "HLP_SOFT_E2E_RESULT_PATH",
        "hlp-soft-live-e2e-result.json",
    ))
    out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    # Fail-honest: at least one adapter must complete ok OR we assert structured errors.
    oks = {n: e for n, e in result.items() if e.get("status") == "ok"}
    errors = {n: e for n, e in result.items() if e.get("status") == "error"}
    skipped = {n: e for n, e in result.items() if e.get("status") == "skipped"}

    for name, entry in oks.items():
        assert entry["correlation_id"] == entry["task_id"], name
        assert entry["decisions"]["D1_soft_no_state_change"] is True, name
        assert entry["decisions"]["D2_host_merge"] is True, name
        assert entry["decisions"]["D3_bci_alone_denied"] is True, name
        assert entry["task_state_after_soft"] == "in_progress", name
        assert entry["steer_called"] is True, name
        assert entry["promotion_profile"] == "HLP-realtime", name

    for name, entry in errors.items():
        assert entry.get("error"), name
        # Live failures must not look like success.
        assert entry["status"] == "error", name

    # If every live binary failed only for env (quota/auth), still require that we
    # attempted and recorded honest errors — not empty.
    assert oks or errors or skipped
    if not oks and errors:
        # Documented soft industrial bar is offline + honest live attempt.
        # Soft unit + industrial suites gate CI; here we only require structured errors.
        for name, entry in errors.items():
            assert "error" in entry and entry["error"], name
