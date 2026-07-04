from __future__ import annotations

import asyncio

import pytest

from loops.hlp import (
    ArtifactPayload,
    FakeAgentAdapter,
    HumanLoopOperations,
    ProtocolError,
)


def run(coro):
    return asyncio.run(coro)


def test_task_revision_increments_once_per_successful_task_mutation():
    ops = HumanLoopOperations()

    task = run(ops.task_create(principal="user_alice", goal="CAS"))
    assert task.revision == 0

    assigned = run(ops.task_assign(task.id, "agent_worker"))
    assert assigned.revision == 1

    started = run(ops.task_start(task.id))
    assert started.revision == 2

    amended = run(ops.task_amend(
        task.id,
        by="user_alice",
        text="Keep the scope narrow.",
    ))
    assert amended.revision == 3


def test_task_amend_replay_with_same_idempotency_key_does_not_steer_or_audit_twice():
    adapter = FakeAgentAdapter()
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops._seed_to_in_progress())
    revision = run(ops.task_get(task.id)).revision

    first = run(ops.task_amend(
        task.id,
        by="alice",
        text="Review auth boundaries only.",
        expected_task_revision=revision,
        idempotency_key="amend-auth-boundaries",
    ))
    replay = run(ops.task_amend(
        task.id,
        by="alice",
        text="Review auth boundaries only.",
        expected_task_revision=revision,
        idempotency_key="amend-auth-boundaries",
    ))

    assert replay == first
    assert len(first.steering_log) == 1
    assert len(adapter.calls_of("steer")) == 1
    assert [event.action for event in ops.store.audit_log.all()].count("task.amended") == 1


def test_same_idempotency_key_with_different_payload_conflicts_without_mutation():
    adapter = FakeAgentAdapter()
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops._seed_to_in_progress())
    revision = run(ops.task_get(task.id)).revision

    run(ops.task_amend(
        task.id,
        by="alice",
        text="Review auth boundaries only.",
        expected_task_revision=revision,
        idempotency_key="same-key",
    ))

    with pytest.raises(ProtocolError) as exc:
        run(ops.task_amend(
            task.id,
            by="alice",
            text="Review billing boundaries instead.",
            expected_task_revision=revision,
            idempotency_key="same-key",
        ))

    assert exc.value.code == "CONFLICT"
    assert len(adapter.calls_of("steer")) == 1
    assert [event.action for event in ops.store.audit_log.all()].count("task.amended") == 1


def test_stale_expected_task_revision_conflicts_before_adapter_call():
    adapter = FakeAgentAdapter()
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops._seed_to_in_progress())

    with pytest.raises(ProtocolError) as exc:
        run(ops.task_amend(
            task.id,
            by="alice",
            text="This should not reach the adapter.",
            expected_task_revision=1,
            idempotency_key="stale-revision",
        ))

    assert exc.value.code == "CONFLICT"
    assert adapter.calls_of("steer") == []


def test_interrupt_replay_returns_same_checkpoint_and_blocks_once():
    adapter = FakeAgentAdapter()
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops._seed_to_in_progress())
    revision = run(ops.task_get(task.id)).revision

    first = run(ops.task_interrupt(
        task.id,
        by="alice",
        prompt="Pause for inspection.",
        expected_task_revision=revision,
        idempotency_key="interrupt-inspection",
    ))
    replay = run(ops.task_interrupt(
        task.id,
        by="alice",
        prompt="Pause for inspection.",
        expected_task_revision=revision,
        idempotency_key="interrupt-inspection",
    ))

    assert replay == first
    assert len(adapter.calls_of("block")) == 1
    assert len(run(ops.task_get(task.id)).checkpoints) == 1


def test_checkpoint_resolve_replay_returns_same_resolution_and_resumes_once():
    adapter = FakeAgentAdapter()
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops._seed_to_in_progress())
    checkpoint = run(ops.checkpoint_raise(
        task_id=task.id,
        kind="approval",
        prompt="Proceed?",
        raised_by="agent_worker",
    ))
    revision = run(ops.task_get(task.id)).revision

    first = run(ops.checkpoint_resolve(
        checkpoint.id,
        by="alice",
        action="approve",
        expected_task_revision=revision,
        idempotency_key="resolve-approval",
    ))
    replay = run(ops.checkpoint_resolve(
        checkpoint.id,
        by="alice",
        action="approve",
        expected_task_revision=revision,
        idempotency_key="resolve-approval",
    ))

    assert replay == first
    assert len(adapter.calls_of("resume")) == 1


def test_artifact_commit_replay_returns_same_artifact_and_does_not_create_v2():
    ops = HumanLoopOperations()
    task = run(ops._seed_to_in_progress())
    revision = run(ops.task_get(task.id)).revision
    payload = ArtifactPayload(
        kind="inline",
        uri="mem://artifact-v1",
        checksum="sha256:artifact-v1",
    )

    first = run(ops.artifact_commit(
        task_id=task.id,
        type="report",
        payload=payload,
        produced_by="agent_worker",
        expected_task_revision=revision,
        idempotency_key="commit-report",
    ))
    replay = run(ops.artifact_commit(
        task_id=task.id,
        type="report",
        payload=payload,
        produced_by="agent_worker",
        expected_task_revision=revision,
        idempotency_key="commit-report",
    ))

    assert replay == first
    assert replay.version == "v1"
    assert run(ops.task_get(task.id)).artifacts == [first.id]
