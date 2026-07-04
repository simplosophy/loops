from __future__ import annotations

import asyncio

import pytest

from loops.hlp import (
    AgentAdapterError,
    ArtifactPayload,
    FakeHarnessAdapter,
    HarnessCapabilities,
    HarnessEvent,
    HLPClient,
    ProcessAgentAdapter,
    ProcessResult,
    ProtocolError,
)


def run(coro):
    return asyncio.run(coro)


def test_hlp_integrated_profile_projects_harness_events_with_correlation():
    adapter = FakeHarnessAdapter(capabilities=HarnessCapabilities(
        name="conformance-harness",
        conformance=("checkpoint-capable", "artifact-aware", "event-streaming"),
    ))
    client = HLPClient(adapter=adapter)

    task = run(client.create_task(
        principal="user_alice",
        goal="Project harness events",
    ))
    handle = run(client.delegate(task.id, "agent_harness", capability="conformance"))
    run(client.start(task.id))

    adapter.queue_event(handle.run_id, HarnessEvent(
        kind="needs_approval",
        task_id=task.id,
        run_id=handle.run_id,
        agent_id=handle.agent_id,
        prompt="Approve harness operation?",
    ))
    checkpoint = run(client.project_harness_events(handle.run_id))[0]
    assert checkpoint.kind == "approval"

    run(client.resolve_checkpoint(
        checkpoint.id,
        by="user_alice",
        action="approve",
        state_patch={"resume": "from-human-state"},
    ))

    adapter.queue_event(handle.run_id, HarnessEvent(
        kind="artifact",
        task_id=task.id,
        run_id=handle.run_id,
        agent_id=handle.agent_id,
        artifact_type="report",
        artifact_uri="mem://integrated-report",
        artifact_checksum="sha256:integrated-report",
    ))
    artifact = run(client.project_harness_events(handle.run_id))[0]
    assert artifact.payload == ArtifactPayload(
        kind="ref",
        uri="mem://integrated-report",
        checksum="sha256:integrated-report",
        size=0,
    )

    inbox = run(client.human_inbox("user_alice"))
    assert [(item.kind, item.action, item.subject_id) for item in inbox] == [
        ("review", "submit_review", artifact.id),
    ]


def test_hlp_integrated_profile_rejects_mismatched_harness_correlation():
    adapter = FakeHarnessAdapter()
    client = HLPClient(adapter=adapter)

    task = run(client.create_task(principal="user_alice", goal="Protect projection"))
    handle = run(client.delegate(task.id, "agent_harness"))
    run(client.start(task.id))

    adapter.queue_event(handle.run_id, HarnessEvent(
        kind="needs_input",
        task_id="task_other",
        run_id=handle.run_id,
        agent_id=handle.agent_id,
        prompt="Bad task id",
    ))

    with pytest.raises(ProtocolError) as exc:
        run(client.project_harness_events(handle.run_id))
    assert exc.value.code == "CONFLICT"


def test_hlp_integrated_profile_process_adapter_requires_external_run_id():
    async def runner(_command, request, _timeout):
        assert request["operation"] == "delegate"
        assert request["correlation_id"] == "task_proc"
        return ProcessResult(exit_code=0, stdout="{}", stderr="")

    adapter = ProcessAgentAdapter(
        command=("agent", "run", "--json"),
        name="conformance-process",
        runner=runner,
    )

    with pytest.raises(AgentAdapterError) as exc:
        run(adapter.delegate(
            task_id="task_proc",
            agent_id="agent_proc",
            capability="conformance",
            input={"goal": "prove run id"},
        ))
    assert exc.value.operation == "delegate"
    assert "run_id" in str(exc.value)
