"""Offline soft harness E2E through the shipped soft e2e entry (injected runners)."""

from __future__ import annotations

import asyncio

from examples.hlp_soft_harness_e2e import (
    default_offline_runners,
    inventory_harnesses,
    run_soft_e2e,
)


def run(coro):
    return asyncio.run(coro)


def test_soft_harness_e2e_offline_codex_and_pi_multi_merge():
    adapters = ("codex", "pi")
    result = run(
        run_soft_e2e(
            adapters=adapters,
            runners=default_offline_runners(adapters),
            timeout=15.0,
        )
    )
    assert set(result) == {"codex", "pi"}
    for name, entry in result.items():
        assert entry["status"] == "ok", (name, entry)
        assert entry["mode"] == "offline", name
        assert entry["task_id"].startswith("task_"), name
        assert entry["correlation_id"] == entry["task_id"], name
        assert entry["decisions"]["correlation_preserved"] is True, name
        assert entry["decisions"]["D1_soft_no_state_change"] is True, name
        assert entry["decisions"]["D2_host_merge"] is True, name
        assert entry["decisions"]["D3_bci_alone_denied"] is True, name
        assert entry["task_state_after_soft"] == "in_progress", name
        assert entry["soft_signals_in"] == 3, name
        assert entry["soft_signals_promoted"] == 2, name
        assert "JSON-only" in entry["steering_text"], name
        assert "correlation_id" in entry["steering_text"], name
        assert "uh-huh" not in entry["steering_text"], name
        assert entry["promotion_profile"] == "HLP-realtime", name
        assert entry["promotion_signal_count"] == 2, name
        assert entry["steer_called"] is True, name
        assert "steer" in entry["adapter_operations"], name


def test_inventory_harnesses_reports_paths():
    inv = inventory_harnesses()
    assert set(inv) >= {"codex", "pi", "claude", "kimi"}
    for _name, info in inv.items():
        assert "available" in info
        assert "path" in info
