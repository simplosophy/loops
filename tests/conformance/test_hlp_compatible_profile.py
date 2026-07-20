from __future__ import annotations

import asyncio

import pytest

from loops.hlp import (
    ArtifactPayload,
    CheckpointOption,
    Constraints,
    FakeAgentAdapter,
    HumanLoopOperations,
    PermissionGrant,
    ProposedAction,
    ProtocolError,
    ReviewComment,
)


def run(coro):
    return asyncio.run(coro)


REQUIRED_OBJECTS = {
    "Task",
    "Checkpoint",
    "Ownership",
    "Review",
    "Artifact",
    "Ledger",
    "AuditEvent",
}

REQUIRED_VALUE_OBJECTS_02 = {
    "SteeringAmendment",
    "PermissionGrant",
    "ProposedAction",
}

REQUIRED_OPERATIONS_02 = {
    "task_create",
    "task_assign",
    "task_start",
    "task_cancel",
    "task_interrupt",
    "task_amend",
    "task_get",
    "task_list",
    "checkpoint_raise",
    "checkpoint_resolve",
    "checkpoint_expire",
    "ownership_transfer",
    "ownership_delegate",
    "review_submit",
    "review_comment",
    "artifact_commit",
    "artifact_get",
    "artifact_reference",
    "ledger_read",
    "ledger_write",
    "ledger_history",
    "audit_query",
    "audit_replay",
}


def test_hlp_compatible_profile_exports_required_objects_and_operations():
    import loops.hlp as hlp

    for name in REQUIRED_OBJECTS | REQUIRED_VALUE_OBJECTS_02:
        assert name in hlp.__all__, name
        assert hasattr(hlp, name), name

    for operation in REQUIRED_OPERATIONS_02:
        assert hasattr(HumanLoopOperations, operation), operation


def test_hlp_compatible_profile_golden_23_operation_flow():
    adapter = FakeAgentAdapter()
    ops = HumanLoopOperations(adapter=adapter)

    grant = PermissionGrant(
        scope="fs:/repo:write",
        decision="allow",
        until="task",
        granted_by="user_alice",
    )
    constraints = Constraints(
        autonomy="plan_then_implement",
        grants=(grant,),
    )

    task = run(
        ops.task_create(
            principal="user_alice",
            goal="Ship accountable HLP work",
            type="conformance",
            acceptance_criteria=("continuous control works",),
            constraints=constraints,
        )
    )
    assert task.state == "created"
    assert task.spec.constraints == constraints
    assert run(ops.task_get(task.id)).id == task.id
    assert [listed.id for listed in run(ops.task_list())] == [task.id]

    run(ops.task_assign(task.id, "agent_builder", capability="implementation"))
    run(ops.task_start(task.id))
    amended = run(
        ops.task_amend(
            task.id,
            by="user_alice",
            text="Prefer the smallest protocol-level fix.",
            intent="constrain",
        )
    )
    assert amended.steering_log[-1].text == "Prefer the smallest protocol-level fix."
    assert adapter.calls_of("steer")

    interrupt = run(
        ops.task_interrupt(
            task.id,
            by="user_alice",
            prompt="Pause for human inspection.",
        )
    )
    run(
        ops.checkpoint_resolve(
            interrupt.id,
            by="user_alice",
            action="approve",
            state_patch={"inspection": "passed"},
        )
    )

    checkpoint = run(
        ops.checkpoint_raise(
            task_id=task.id,
            kind="choice",
            prompt="Select rollout",
            options=(
                CheckpointOption(id="safe", label="Safe rollout", risk="low"),
                CheckpointOption(id="fast", label="Fast rollout", risk="high"),
            ),
            proposed_actions=(
                ProposedAction(
                    id="write-tests",
                    kind="file_write",
                    summary="Write conformance tests",
                    risk="low",
                ),
                ProposedAction(
                    id="skip-review",
                    kind="plan_step",
                    summary="Skip human review",
                    risk="high",
                ),
            ),
            raised_by="agent_builder",
        )
    )
    run(
        ops.checkpoint_resolve(
            checkpoint.id,
            by="user_alice",
            action="choose",
            choice="safe",
            approved_actions=("write-tests",),
            denied_actions=("skip-review",),
            edited_artifact_ref={"id": "art_manual", "version": "v1"},
        )
    )

    plan = run(
        ops.artifact_commit(
            task_id=task.id,
            type="plan",
            payload=ArtifactPayload(kind="inline", uri="mem://plan", checksum="sha256:plan"),
            produced_by="agent_builder",
        )
    )
    plan_review = run(
        ops.review_submit(
            task_id=task.id,
            artifact_id=plan.id,
            reviewer="user_alice",
            verdict="approved",
            kind="plan",
        )
    )
    assert plan_review.kind == "plan"
    assert run(ops.task_get(task.id)).state == "in_progress"

    deliverable_v1 = run(
        ops.artifact_commit(
            task_id=task.id,
            type="report",
            payload=ArtifactPayload(kind="inline", uri="mem://v1", checksum="sha256:v1"),
            produced_by="agent_builder",
        )
    )
    run(
        ops.review_submit(
            task_id=task.id,
            artifact_id=deliverable_v1.id,
            reviewer="user_alice",
            verdict="changes_requested",
            requested_changes=("Add audit evidence",),
        )
    )
    deliverable_v2 = run(
        ops.artifact_commit(
            task_id=task.id,
            type="report",
            payload=ArtifactPayload(kind="inline", uri="mem://v2", checksum="sha256:v2"),
            produced_by="agent_builder",
            parent_version=deliverable_v1.version,
        )
    )
    comment = run(
        ops.review_submit(
            task_id=task.id,
            artifact_id=deliverable_v2.id,
            reviewer="user_alice",
            verdict="approved",
        )
    )
    run(
        ops.review_comment(
            comment.id,
            ReviewComment(anchor="summary", severity="minor", body="Accepted."),
            by="user_alice",
        )
    )

    assert run(ops.artifact_get(deliverable_v2.id, deliverable_v2.version)).id == deliverable_v2.id
    run(ops.artifact_reference(deliverable_v2.id, by_task=task.id, as_="input"))

    entry = run(ops.ledger_write("project:hlp", "release.status", "accepted", by=task.id))
    assert run(ops.ledger_read("project:hlp", "release.status")) == "accepted"
    assert run(ops.ledger_history("project:hlp", "release.status")) == [entry]

    audit_actions = [event.action for event in run(ops.audit_query(task_id=task.id))]
    replay_actions = [event.action for event in run(ops.audit_replay(task.id))]
    assert audit_actions == replay_actions
    assert "task.amended" in audit_actions
    assert "task.interrupted" in audit_actions
    assert "task.checkpoint.resolved" in audit_actions
    assert run(ops.task_get(task.id)).state == "completed"

    delegated = run(ops.task_create(principal="user_alice", goal="Delegate safely"))
    run(ops.task_assign(delegated.id, "agent_parent"))
    run(ops.task_start(delegated.id))
    run(ops.ownership_delegate(delegated.id, "agent_child", actor="agent_parent"))
    run(ops.ownership_transfer(delegated.id, "agent_reviewer", "handoff", actor="agent_child"))
    assert run(ops.task_get(delegated.id)).ownership.assignee == "agent_reviewer"

    expiring = run(ops.task_create(principal="user_alice", goal="Expire checkpoint"))
    run(ops.task_assign(expiring.id, "agent_expirer"))
    run(ops.task_start(expiring.id))
    expiring_checkpoint = run(
        ops.checkpoint_raise(
            task_id=expiring.id,
            kind="approval",
            prompt="This will expire",
            raised_by="agent_expirer",
        )
    )
    assert run(ops.checkpoint_expire(expiring_checkpoint.id)).state == "expired"

    cancel_task = run(ops.task_create(principal="user_alice", goal="Cancel task"))
    run(ops.task_assign(cancel_task.id, "agent_cancel"))
    cancelled = run(ops.task_cancel(cancel_task.id, by="user_alice"))
    assert cancelled.state == "completed"
    assert cancelled.ownership.assignee == cancelled.ownership.principal


def test_hlp_compatible_profile_rejects_non_conforming_operations():
    ops = HumanLoopOperations()
    task = run(ops._seed_to_in_progress())

    with pytest.raises(ProtocolError) as agent_interrupt:
        run(
            ops.checkpoint_raise(
                task_id=task.id,
                kind="interrupt",
                prompt="agent cannot raise this",
                raised_by="agent_builder",
            )
        )
    assert agent_interrupt.value.code == "INVALID_SPEC"

    checkpoint = run(
        ops.checkpoint_raise(
            task_id=task.id,
            kind="approval",
            prompt="Approve one action",
            raised_by="agent_builder",
            proposed_actions=(
                ProposedAction(
                    id="safe",
                    kind="tool_call",
                    summary="Safe tool",
                    risk="low",
                ),
            ),
        )
    )
    with pytest.raises(ProtocolError) as bad_action:
        run(
            ops.checkpoint_resolve(
                checkpoint.id,
                by="alice",
                action="approve",
                approved_actions=("unknown",),
            )
        )
    assert bad_action.value.code == "INVALID_SPEC"

    run(ops.checkpoint_expire(checkpoint.id))
    with pytest.raises(ProtocolError) as expired:
        run(ops.checkpoint_resolve(checkpoint.id, by="alice", action="approve"))
    assert expired.value.code == "CHECKPOINT_EXPIRED"

    artifact_task = run(ops._seed_to_in_progress())
    artifact = run(
        ops.artifact_commit(
            task_id=artifact_task.id,
            type="report",
            payload=ArtifactPayload(kind="inline", uri="mem://x", checksum="sha256:x"),
            produced_by="agent",
        )
    )
    with pytest.raises(ProtocolError) as missing_version:
        run(ops.artifact_get(artifact.id, "v404"))
    assert missing_version.value.code == "NOT_FOUND"

    with pytest.raises(ProtocolError):
        artifact._sealed = False
