from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from loops.hlp import ArtifactPayload, FakeAgentAdapter, HLPClient
from loops.tui.controller import TUIController
from loops.tui.session import SessionStore


async def run_demo() -> dict[str, Any]:
    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)

    with tempfile.TemporaryDirectory(prefix="hlp-tui-demo-") as tmpdir:
        sessions = SessionStore(Path(tmpdir) / "sessions.json")
        session = sessions.create(cwd="/demo", adapter="fake", principal="user_local")
        controller = TUIController(client=client, sessions=sessions)

        await controller.handle(session.id, "Review a generated patch")
        active = sessions.resume(session.id)
        checkpoint = await client.raise_checkpoint(
            task_id=active.active_task_id,
            kind="approval",
            prompt="Apply patch?",
            raised_by="agent_tui",
        )
        await controller.handle(session.id, "/approve")
        resolved_checkpoint = client.store.get_checkpoint(checkpoint.id)
        artifact = await client.commit_artifact(
            task_id=active.active_task_id,
            type="patch",
            payload=ArtifactPayload(
                kind="inline",
                uri="mem://hlp-tui-demo.patch",
                checksum="sha256:hlp-tui-demo",
            ),
            produced_by="agent_tui",
        )
        review_result = await controller.handle(session.id, "/review approved")
        final_task = await client.get_task(active.active_task_id)
        audit = await client.replay_audit(active.active_task_id)

    return {
        "session_id": session.id,
        "task_id": active.active_task_id,
        "run_id": active.active_run_id,
        "checkpoint_id": checkpoint.id,
        "checkpoint_decision": (
            resolved_checkpoint.resolution.action
            if resolved_checkpoint.resolution is not None
            else ""
        ),
        "artifact_id": artifact.id,
        "review_verdict": "approved" if "verdict=approved" in review_result.output else "",
        "final_task_state": final_task.state,
        "adapter_operations": [name for name, _payload in adapter.calls],
        "audit_actions": [event.action for event in audit],
    }


def main() -> None:
    print(json.dumps(asyncio.run(run_demo()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
