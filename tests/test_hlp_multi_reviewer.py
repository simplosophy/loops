"""Multi-reviewer aggregation (spec §3.6, §7.5): policy, quorum, veto, rounds."""

from __future__ import annotations

import asyncio

import pytest

from loops.hlp import (
    ArtifactPayload,
    FakeAgentAdapter,
    HumanLoopOperations,
    ProtocolError,
    ReviewPolicy,
    from_wire,
    to_wire,
)
from loops.hlp.transport import HLPHttpServer, HttpHLPWireClient


def run(coro):
    return asyncio.run(coro)


def _policy(*reviewers: str, quorum: str = "all") -> ReviewPolicy:
    return ReviewPolicy(required_reviewers=tuple(reviewers), quorum=quorum)  # type: ignore[arg-type]


def _seed(ops: HumanLoopOperations, policy: ReviewPolicy | None = None):
    task = run(
        ops.task_create(
            principal="user_alice",
            goal="multi review",
            review_policy=policy,
        )
    )
    run(ops.task_assign(task.id, "agent_dev"))
    run(ops.task_start(task.id))
    artifact = run(
        ops.artifact_commit(
            task_id=task.id,
            type="report",
            payload=ArtifactPayload(kind="inline", uri="mem://v1", checksum="sha256:v1"),
            produced_by="agent_dev",
        )
    )
    return task, artifact


def _review(ops, task_id, artifact_id, reviewer, verdict, **kwargs):
    return run(
        ops.review_submit(
            task_id=task_id,
            artifact_id=artifact_id,
            reviewer=reviewer,
            verdict=verdict,
            **kwargs,
        )
    )


def test_quorum_all_waits_for_every_approval_then_completes_once():
    ops = HumanLoopOperations(adapter=FakeAgentAdapter())
    policy = _policy("user_bob", "user_carol", quorum="all")
    task, artifact = _seed(ops, policy)

    _review(ops, task.id, artifact.id, "user_bob", "approved")
    assert run(ops.task_get(task.id)).state == "under_review"  # pending
    assert not [e for e in ops.store.audit_log.all() if e.action == "task.completed"]

    _review(ops, task.id, artifact.id, "user_carol", "approved")
    final = run(ops.task_get(task.id))
    assert final.state == "completed"
    completed = [e for e in ops.store.audit_log.all() if e.action == "task.completed"]
    assert len(completed) == 1


def test_quorum_majority_completes_on_strict_majority():
    ops = HumanLoopOperations(adapter=FakeAgentAdapter())
    policy = _policy("user_bob", "user_carol", "user_dave", quorum="majority")
    task, artifact = _seed(ops, policy)

    _review(ops, task.id, artifact.id, "user_bob", "approved")
    assert run(ops.task_get(task.id)).state == "under_review"
    _review(ops, task.id, artifact.id, "user_carol", "approved")
    assert run(ops.task_get(task.id)).state == "completed"


def test_quorum_any_completes_on_first_approval():
    ops = HumanLoopOperations(adapter=FakeAgentAdapter())
    policy = _policy("user_bob", "user_carol", quorum="any")
    task, artifact = _seed(ops, policy)

    _review(ops, task.id, artifact.id, "user_bob", "approved")
    assert run(ops.task_get(task.id)).state == "completed"


def test_veto_beats_quorum_progress():
    ops = HumanLoopOperations(adapter=FakeAgentAdapter())
    policy = _policy("user_bob", "user_carol", quorum="any")
    task, artifact = _seed(ops, policy)

    _review(ops, task.id, artifact.id, "user_carol", "rejected")
    assert run(ops.task_get(task.id)).state == "rejected"


def test_changes_requested_sends_task_back_for_rework_immediately():
    ops = HumanLoopOperations(adapter=FakeAgentAdapter())
    policy = _policy("user_bob", "user_carol", quorum="all")
    task, artifact = _seed(ops, policy)

    _review(
        ops,
        task.id,
        artifact.id,
        "user_bob",
        "changes_requested",
        requested_changes=("fix auth",),
    )
    final = run(ops.task_get(task.id))
    assert final.state == "in_progress"
    assert final.ownership.assignee == "agent_dev"


def test_reviewer_must_be_in_required_reviewers():
    ops = HumanLoopOperations(adapter=FakeAgentAdapter())
    policy = _policy("user_bob", quorum="all")
    task, artifact = _seed(ops, policy)

    with pytest.raises(ProtocolError) as err:
        _review(ops, task.id, artifact.id, "user_mallory", "approved")
    assert err.value.code == "UNAUTHORIZED"


def test_latest_verdict_per_reviewer_wins():
    ops = HumanLoopOperations(adapter=FakeAgentAdapter())
    policy = _policy("user_bob", "user_carol", quorum="all")
    task, artifact = _seed(ops, policy)

    _review(ops, task.id, artifact.id, "user_bob", "approved")  # pending at 1/2
    # Bob changes his mind with a NEW review (append-only; latest supersedes).
    _review(
        ops,
        task.id,
        artifact.id,
        "user_bob",
        "changes_requested",
        requested_changes=("more tests",),
    )
    assert run(ops.task_get(task.id)).state == "in_progress"


def test_new_artifact_version_starts_a_fresh_round():
    ops = HumanLoopOperations(adapter=FakeAgentAdapter())
    policy = _policy("user_bob", "user_carol", quorum="all")
    task, artifact = _seed(ops, policy)

    _review(ops, task.id, artifact.id, "user_bob", "approved")
    _review(
        ops,
        task.id,
        artifact.id,
        "user_carol",
        "changes_requested",
        requested_changes=("rework",),
    )
    v2 = run(
        ops.artifact_commit(
            task_id=task.id,
            type="report",
            payload=ArtifactPayload(
                kind="inline",
                uri="mem://v2",
                checksum="sha256:v2",
            ),
            produced_by="agent_dev",
            parent_version=artifact.version,
        )
    )

    # Bob's v1 approval must NOT carry into the v2 round.
    review_v2 = _review(ops, task.id, v2.id, "user_bob", "approved")
    assert review_v2.artifact_version == "v2"
    assert run(ops.task_get(task.id)).state == "under_review"

    _review(ops, task.id, v2.id, "user_carol", "approved")
    assert run(ops.task_get(task.id)).state == "completed"
    assert len([e for e in ops.store.audit_log.all() if e.action == "task.completed"]) == 1


def test_changes_requested_still_requires_requested_changes():
    ops = HumanLoopOperations(adapter=FakeAgentAdapter())
    policy = _policy("user_bob", quorum="all")
    task, artifact = _seed(ops, policy)

    with pytest.raises(ProtocolError) as err:
        _review(ops, task.id, artifact.id, "user_bob", "changes_requested")
    assert err.value.code == "INVALID_SPEC"


def test_review_policy_requires_non_empty_reviewers():
    with pytest.raises(ProtocolError) as err:
        ReviewPolicy(required_reviewers=())
    assert err.value.code == "INVALID_SPEC"


def test_no_policy_keeps_single_reviewer_semantics():
    ops = HumanLoopOperations(adapter=FakeAgentAdapter())
    task, artifact = _seed(ops, policy=None)
    _review(ops, task.id, artifact.id, "user_anyone", "approved")
    assert run(ops.task_get(task.id)).state == "completed"


def test_review_policy_and_versioned_review_wire_round_trip():
    policy = _policy("user_bob", "user_carol", quorum="majority")
    assert from_wire("ReviewPolicy", to_wire(policy)) == policy

    ops = HumanLoopOperations(adapter=FakeAgentAdapter())
    task, artifact = _seed(ops, policy)
    review = _review(ops, task.id, artifact.id, "user_bob", "approved")
    rebuilt = from_wire("Review", to_wire(review))
    assert rebuilt.artifact_version == review.artifact_version == "v1"
    assert rebuilt.reviewer == "user_bob"


def test_task_create_with_review_policy_over_http():
    operations = HumanLoopOperations(adapter=FakeAgentAdapter())
    server = HLPHttpServer(operations).start()
    try:
        client = HttpHLPWireClient(server.address, principal="user_alice", timeout=10.0)
        task = client.create_task(
            principal="user_alice",
            goal="http multi review",
            review_policy={
                "required_reviewers": ["user_bob", "user_carol"],
                "quorum": "any",
            },
        )
        assert task["spec"]["review_policy"]["quorum"] == "any"
        client.assign(task["id"], "agent_dev")
        client.start(task["id"])
        artifact = client.commit_artifact(
            task_id=task["id"],
            type="report",
            payload={"kind": "inline", "uri": "mem://v1", "checksum": "sha256:v1", "size": 0},
            produced_by="agent_dev",
        )
        client.call(
            "review.submit",
            {
                "task_id": task["id"],
                "artifact_id": artifact["id"],
                "verdict": "approved",
                "reviewer": "user_bob",
            },
            principal="user_bob",
        )
        assert client.call("task.get", {"task_id": task["id"]})["state"] == "completed"
    finally:
        server.stop()
