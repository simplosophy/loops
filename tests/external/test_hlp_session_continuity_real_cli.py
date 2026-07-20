from __future__ import annotations

import asyncio
import os

import pytest

from examples.hlp_session_continuity_e2e import run_demo


def run(coro):
    return asyncio.run(coro)


@pytest.mark.skipif(
    os.environ.get("HLP_RUN_EXTERNAL_CLI_E2E") != "1",
    reason="set HLP_RUN_EXTERNAL_CLI_E2E=1 to run real local CLI session-continuity probes",
)
def test_real_local_cli_session_continuity():
    result = run(run_demo())

    failures = {name: entry for name, entry in result.items() if entry["status"] != "ok"}
    assert failures == {}

    for name, entry in result.items():
        assert entry["session_id"], name
        assert entry["codeword_found"] is True, name
        assert entry["resumed_ops"] == entry["followup_ops"] > 0, name
