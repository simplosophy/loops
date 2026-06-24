from __future__ import annotations

import asyncio
import json
from typing import Any

from loops.hlp import (
    CodexHarnessAdapter,
    HLPClient,
    ProcessResult,
)


async def run_demo() -> dict[str, Any]:
    adapter = CodexHarnessAdapter(
        command=("codex", "exec", "--json"),
        runner=_codex_demo_runner,
    )
    client = HLPClient(adapter=adapter)

    task = await client.create_task(
        principal="user_alice",
        goal="Review a Codex generated patch",
        type="codex-harness",
        acceptance_criteria=("Human approval and review are tracked by HLP",),
    )
    run = await client.delegate(
        task.id,
        "agent_codex",
        capability="code-edit",
        input={"goal": task.spec.goal},
    )
    await client.start(task.id)

    checkpoint = (await client.project_harness_events(run.run_id))[0]
    inbox_after_checkpoint = await client.human_inbox("user_alice")

    checkpoint = await client.resolve_checkpoint(
        checkpoint.id,
        by="user_alice",
        action="approve",
    )

    artifact = (await client.project_harness_events(run.run_id))[0]
    inbox_after_artifact = await client.human_inbox("user_alice")

    review = await client.submit_review(
        task_id=task.id,
        artifact_id=artifact.id,
        reviewer="user_alice",
        verdict="approved",
    )
    final_task = await client.get_task(task.id)
    health = await adapter.healthcheck()

    return {
        "task_id": task.id,
        "run_id": run.run_id,
        "adapter": health["adapter"],
        "harness_conformance": list(adapter.harness_capabilities().conformance),
        "checkpoint_id": checkpoint.id,
        "checkpoint_prompt": checkpoint.prompt,
        "checkpoint_decision": checkpoint.resolution.action if checkpoint.resolution else None,
        "artifact_id": artifact.id,
        "artifact_version": artifact.version,
        "artifact_uri": artifact.payload.uri,
        "review_id": review.id,
        "review_verdict": review.verdict,
        "final_task_state": final_task.state,
        "inbox_after_checkpoint": [item.action for item in inbox_after_checkpoint],
        "inbox_after_artifact": [item.action for item in inbox_after_artifact],
    }


async def _codex_demo_runner(
    command: tuple[str, ...],
    request: dict[str, Any],
    timeout: float,
) -> ProcessResult:
    if request["operation"] == "delegate":
        return ProcessResult(
            exit_code=0,
            stdout="\n".join((
                json.dumps({"type": "session.started", "session_id": "codex_demo_session"}),
                json.dumps({
                    "type": "hlp.event",
                    "run_id": "codex_demo_run",
                    "correlation_id": request["correlation_id"],
                    "hlp": {
                        "kind": "needs_approval",
                        "agent_id": request["agent_id"],
                        "prompt": "Apply the Codex patch?",
                    },
                }),
                json.dumps({
                    "type": "turn.completed",
                    "run_id": "codex_demo_run",
                    "correlation_id": request["correlation_id"],
                    "status": "ok",
                }),
            )),
            stderr="",
        )
    if request["operation"] == "resume":
        return ProcessResult(
            exit_code=0,
            stdout="\n".join((
                json.dumps({
                    "type": "hlp.event",
                    "run_id": request["run_id"],
                    "correlation_id": request["correlation_id"],
                    "hlp": {
                        "kind": "artifact",
                        "agent_id": "agent_codex",
                        "artifact_type": "patch",
                        "artifact_uri": "mem://codex-demo.patch",
                        "artifact_checksum": "sha256:codex-demo.patch",
                        "artifact_size": 128,
                    },
                }),
                json.dumps({
                    "type": "turn.completed",
                    "run_id": request["run_id"],
                    "correlation_id": request["correlation_id"],
                    "status": "ok",
                }),
            )),
            stderr="",
        )
    return ProcessResult(exit_code=0, stdout="{}", stderr="")


def main() -> None:
    print(json.dumps(asyncio.run(run_demo()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
