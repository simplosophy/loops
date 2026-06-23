from __future__ import annotations

import asyncio
import json
from typing import Any

from loops.hlp import (
    ArtifactPayload,
    CheckpointOption,
    FakeAgentAdapter,
    HLPClient,
)


async def run_demo() -> dict[str, Any]:
    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)

    task = await client.create_task(
        principal="user_alice",
        goal="Review PR #1234 for security issues",
        type="code-review",
        acceptance_criteria=("All reviewer comments resolved",),
    )
    run_handle = await client.delegate(task.id, "agent_reviewer")
    await client.start(task.id)
    checkpoint = await client.raise_checkpoint(
        task_id=task.id,
        kind="choice",
        prompt="Delete obsolete indexes?",
        options=(
            CheckpointOption(id="safe", label="Keep risky index", risk="low"),
            CheckpointOption(id="fast", label="Delete all obsolete indexes", risk="high"),
        ),
        raised_by="agent_reviewer",
    )
    checkpoint = await client.resolve_checkpoint(
        checkpoint.id,
        by="user_alice",
        action="choose",
        choice="safe",
        comment="Choose the lower-risk path.",
    )
    artifact = await client.commit_artifact(
        task_id=task.id,
        type="report",
        payload=ArtifactPayload(
            kind="inline",
            uri="mem://hlp-demo-report-v1",
            checksum="sha256:hlp-demo-report-v1",
        ),
        produced_by="agent_reviewer",
    )
    review = await client.submit_review(
        task_id=task.id,
        artifact_id=artifact.id,
        reviewer="user_alice",
        verdict="approved",
    )
    ledger_entry = await client.write_ledger(
        "project:hlp-demo",
        "pr.1234.status",
        "approved",
        by=task.id,
    )
    history = await client.replay_audit(task.id)

    return {
        "task_id": task.id,
        "run_id": run_handle.run_id,
        "checkpoint_id": checkpoint.id,
        "checkpoint_decision": checkpoint.resolution.choice if checkpoint.resolution else None,
        "artifact_id": artifact.id,
        "artifact_version": artifact.version,
        "review_id": review.id,
        "review_verdict": review.verdict,
        "ledger_status": ledger_entry.value,
        "audit_actions": [event.action for event in history],
    }


def main() -> None:
    print(json.dumps(asyncio.run(run_demo()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
