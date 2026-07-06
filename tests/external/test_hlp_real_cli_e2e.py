from __future__ import annotations

import asyncio
import os

import pytest

from examples.hlp_local_cli_e2e import run_demo


def run(coro):
    return asyncio.run(coro)


@pytest.mark.skipif(
    os.environ.get("HLP_RUN_EXTERNAL_CLI_E2E") != "1",
    reason="set HLP_RUN_EXTERNAL_CLI_E2E=1 to run real local CLI adapters",
)
def test_real_local_cli_adapters_run_hlp_e2e():
    result = run(run_demo(adapters=("codex", "kimi", "claude"), strict=True))

    failures = {
        name: entry
        for name, entry in result.items()
        if entry["status"] != "ok"
    }
    assert failures == {}

    for name, entry in result.items():
        assert entry["task_id"].startswith("task_"), name
        assert entry["run_id"], name
        assert entry["correlation_id"] == entry["task_id"], name
        assert entry["returned_correlation_id"] == entry["task_id"], name
        assert entry["adapter_operations"] == [
            "delegate",
            "steer",
            "block",
            "resume",
            "delegate",
            "handoff",
            "cancel",
        ]
        assert entry["final_task_state"] == "completed", name
        assert entry["review_verdict"] == "approved", name
        assert entry["ledger_status"] == "approved", name
