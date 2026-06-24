from __future__ import annotations

import asyncio
import json
from typing import Any

from loops.hlp import (
    FakeHarnessAdapter,
    HarnessCapabilities,
    HarnessEvent,
    HLPClient,
)


async def run_demo() -> dict[str, Any]:
    adapter = FakeHarnessAdapter(capabilities=HarnessCapabilities(
        name="fake-code-review-harness",
        conformance=("checkpoint-capable", "artifact-aware"),
        description="Projects harness human interactions into HLP.",
    ))
    client = HLPClient(adapter=adapter)

    task = await client.create_task(
        principal="user_alice",
        goal="Wrap an existing code-review harness",
        type="harness-wrap",
        acceptance_criteria=("Human approval and review are tracked by HLP",),
    )
    run = await client.delegate(
        task.id,
        "agent_review_harness",
        capability="harness-wrap",
    )
    await client.start(task.id)

    adapter.queue_event(run.run_id, HarnessEvent(
        kind="needs_approval",
        task_id=task.id,
        run_id=run.run_id,
        agent_id=run.agent_id,
        prompt="Apply the generated patch?",
    ))
    checkpoint = (await client.project_harness_events(run.run_id))[0]
    inbox_after_checkpoint = await client.human_inbox("user_alice")

    checkpoint = await client.resolve_checkpoint(
        checkpoint.id,
        by="user_alice",
        action="approve",
    )

    adapter.queue_event(run.run_id, HarnessEvent(
        kind="artifact",
        task_id=task.id,
        run_id=run.run_id,
        agent_id=run.agent_id,
        artifact_type="patch",
        artifact_uri="mem://patch-v1",
        artifact_checksum="sha256:patch-v1",
    ))
    artifact = (await client.project_harness_events(run.run_id))[0]
    inbox_after_artifact = await client.human_inbox("user_alice")

    review = await client.submit_review(
        task_id=task.id,
        artifact_id=artifact.id,
        reviewer="user_alice",
        verdict="approved",
    )
    final_task = await client.get_task(task.id)

    return {
        "task_id": task.id,
        "run_id": run.run_id,
        "harness_conformance": list(adapter.harness_capabilities().conformance),
        "checkpoint_id": checkpoint.id,
        "checkpoint_prompt": checkpoint.prompt,
        "checkpoint_decision": checkpoint.resolution.action if checkpoint.resolution else None,
        "artifact_id": artifact.id,
        "artifact_version": artifact.version,
        "review_id": review.id,
        "review_verdict": review.verdict,
        "final_task_state": final_task.state,
        "inbox_after_checkpoint": [item.action for item in inbox_after_checkpoint],
        "inbox_after_artifact": [item.action for item in inbox_after_artifact],
    }


def main() -> None:
    print(json.dumps(asyncio.run(run_demo()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
