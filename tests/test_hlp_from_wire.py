"""from_wire round-trip tests: typed reconstruction from wire dicts.

Covers to_wire → from_wire equality for every first-class object and the key
value objects, the from_/as_ alias inversion, tolerance for unknown keys,
INVALID_SPEC on missing required fields, NOT_FOUND on unknown names, and the
HttpHLPWireClient.call(..., as_="Task") transport integration.

Test style follows the repo convention: sync def test_* + asyncio.run() to
drive async operations, no pytest-asyncio.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from loops.hlp import (
    AdapterOperationContext,
    AdapterOutboxRecord,
    Artifact,
    ArtifactPayload,
    ArtifactProvenance,
    ArtifactRef,
    AuditLog,
    Checkpoint,
    CheckpointOption,
    CheckpointResolution,
    Constraints,
    ControlSignal,
    Evidence,
    ExternalRef,
    FakeAgentAdapter,
    HumanInboxItem,
    IdempotencyRecord,
    InputRef,
    InteractionRef,
    Ledger,
    Ownership,
    OwnershipTransfer,
    PermissionGrant,
    ProposedAction,
    ProtocolError,
    Review,
    ReviewComment,
    SteeringAmendment,
    Task,
    TaskSpec,
    from_wire,
    to_wire,
)
from loops.hlp.operations import HumanLoopOperations
from loops.hlp.transport import HLPHttpServer, HttpHLPWireClient

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def run(coro):
    """Sync driver for async operations."""
    return asyncio.run(coro)


def _round_trip(name, value):
    return from_wire(name, to_wire(value))


def _seed_rich_task(ops: HumanLoopOperations) -> Task:
    """A task with spec details, an ownership chain, and a steering log."""
    task = run(
        ops.task_create(
            principal="user_alice",
            goal="rich round trip",
            type="code-change",
            acceptance_criteria=("tests green", "review approved"),
            inputs=(
                InputRef(kind="artifact", id="art_seed", version="v1"),
                InputRef(kind="resource", uri="https://example.com/spec"),
            ),
            constraints=Constraints(
                max_duration="1h",
                external_refs=(
                    ExternalRef(kind="ticket", namespace="jira", id="HLP-1", label="tracker"),
                ),
                autonomy="plan_then_implement",
                grants=(
                    PermissionGrant(
                        scope="fs:read:/tmp",
                        decision="allow",
                        granted_by="user_alice",
                    ),
                ),
            ),
        )
    )
    run(ops.task_assign(task.id, "agent_dev", capability="code"))
    run(ops.task_start(task.id))
    run(ops.task_amend(task.id, by="user_alice", text="focus on auth", intent="constrain"))
    return run(ops.task_get(task.id))


# ── first-class objects ──


def test_task_round_trip_full_lifecycle():
    ops = HumanLoopOperations()
    seeded = run(ops._seed_full_lifecycle())
    snapshot = run(ops.task_get(seeded.id))
    assert _round_trip("Task", snapshot) == snapshot


def test_task_round_trip_with_steering_and_constraints():
    ops = HumanLoopOperations(adapter=FakeAgentAdapter())
    snapshot = _seed_rich_task(ops)
    restored = _round_trip("Task", snapshot)
    assert restored == snapshot
    assert restored.steering_log[0].text == "focus on auth"
    assert restored.ownership.chain[0].from_ == "user_alice"


def test_checkpoint_round_trip():
    checkpoint = Checkpoint(
        task_id="task_1",
        kind="choice",
        prompt="pick one",
        options=(
            CheckpointOption(id="safe", label="low risk", risk="low"),
            CheckpointOption(id="fast", label="medium risk", risk="medium"),
        ),
        proposed_actions=(
            ProposedAction(
                id="pa_1",
                kind="fs:write",
                summary="write report",
                permission_scope="fs:write:/tmp/report",
                detail={"path": "/tmp/report"},
                risk="high",
            ),
        ),
        context=(
            Evidence(kind="artifact", id="art_1"),
            Evidence(kind="text", content="log excerpt"),
        ),
        state="resolved",
        raised_by="agent",
        expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        resolution=CheckpointResolution(
            by="user_alice",
            action="choose",
            choice="safe",
            approved_actions=("pa_1",),
            state_patch={"k": 1},
            edited_artifact_ref={"id": "art_1", "version": "v2"},
            comment="looks good",
        ),
    )
    assert _round_trip("Checkpoint", checkpoint) == checkpoint


def test_ownership_alias_fields_round_trip():
    transfer = OwnershipTransfer(from_="user_alice", to="agent_dev", via="assign")
    wire = to_wire(transfer)
    assert "from" in wire and "from_" not in wire
    assert from_wire("OwnershipTransfer", wire) == transfer

    ownership = Ownership(
        principal="user_alice",
        assignee="agent_dev",
        delegable=False,
        chain=(transfer,),
    )
    assert _round_trip("Ownership", ownership) == ownership


def test_review_round_trip():
    review = Review(
        id="rev_1",
        task_id="task_1",
        artifact_id="art_1",
        reviewer="user_bob",
        kind="deliverable",
        verdict="changes_requested",
        comments=(
            ReviewComment(anchor="l10", severity="major", body="rename this"),
            ReviewComment(anchor="l20"),
        ),
        requested_changes=("fix naming",),
    )
    assert _round_trip("Review", review) == review

    # to_wire skips `_`-private fields: a sealed review comes back unsealed.
    sealed = review.seal()
    wire = to_wire(sealed)
    assert "_sealed" not in wire
    restored = from_wire("Review", wire)
    assert restored._sealed is False
    assert restored == replace(sealed, _sealed=False)


def test_artifact_round_trip():
    artifact = Artifact(
        id="art_1",
        type="report",
        provenance=ArtifactProvenance(produced_by="task_1"),
        version="v2",
        parent_version="v1",
        payload=ArtifactPayload(kind="inline", uri="mem://v2", checksum="sha256:2", size=4),
        references=(
            ArtifactRef(task_id="task_1", as_="output"),
            ArtifactRef(task_id="task_0", as_="input"),
        ),
    )
    assert _round_trip("Artifact", artifact) == artifact
    assert _round_trip("ArtifactPayload", artifact.payload) == artifact.payload
    assert _round_trip("ArtifactProvenance", artifact.provenance) == artifact.provenance

    # to_wire skips `_`-private fields: a sealed artifact comes back unsealed.
    sealed = artifact.seal()
    wire = to_wire(sealed)
    assert "_sealed" not in wire
    restored = from_wire("Artifact", wire)
    assert restored._sealed is False
    assert restored == replace(sealed, _sealed=False)


def test_artifact_ref_alias_round_trip():
    ref = ArtifactRef(task_id="task_1", as_="input")
    wire = to_wire(ref)
    assert wire["as"] == "input" and "as_" not in wire
    assert from_wire("ArtifactRef", wire) == ref


def test_ledger_round_trip():
    ledger = Ledger(scope="project:demo")
    ledger.write("lifecycle.status", "in_progress", by="task_1")
    ledger.write("lifecycle.status", "approved", by="task_1")
    ledger.write("owner", {"current": "user_alice"}, by="task_2")
    assert _round_trip("Ledger", ledger) == ledger

    entry = ledger.history("owner")[0]
    assert _round_trip("LedgerEntry", entry) == entry


def test_audit_event_round_trip():
    log = AuditLog()
    first = log.append(
        actor="user_alice",
        action="task.created",
        subject=("task", "task_1"),
        task_id="task_1",
        after={"state": "created"},
    )
    second = log.append(
        actor="agent_dev",
        action="task.assigned",
        subject=("task", "task_1"),
        task_id="task_1",
        reducer={"op": "assign"},
    )
    assert log.verify_hash_chain()
    for event in (first, second):
        assert _round_trip("AuditEvent", event) == event


# ── value objects ──


def test_value_objects_round_trip():
    context = AdapterOperationContext(
        operation_id="op_1",
        task_id="task_1",
        correlation_id="corr_1",
        operation="task.assign",
        idempotency_key="k-1",
        request_fingerprint="fp",
        task_revision=3,
    )
    cases = [
        (
            "TaskSpec",
            TaskSpec(
                goal="g",
                acceptance_criteria=("a",),
                inputs=(InputRef(kind="resource", uri="https://example.com/x"),),
                constraints=Constraints(max_duration="1h", autonomy="read_only"),
            ),
        ),
        (
            "Constraints",
            Constraints(
                max_duration="30m",
                external_refs=(ExternalRef(kind="ticket", namespace="jira", id="HLP-1"),),
                autonomy="confirm_each_action",
                grants=(PermissionGrant(scope="net:*", decision="deny"),),
            ),
        ),
        (
            "PermissionGrant",
            PermissionGrant(
                scope="fs:read:/tmp",
                decision="allow",
                granted_by="user_alice",
                granted_at=NOW,
            ),
        ),
        # until is str | datetime: the datetime form must decode back to datetime.
        ("PermissionGrant", PermissionGrant(scope="fs:write:/tmp", decision="deny", until=NOW)),
        ("SteeringAmendment", SteeringAmendment(text="focus", intent="redirect", by="u", at=NOW)),
        ("InputRef", InputRef(kind="artifact", id="art_1", version="v1")),
        ("ExternalRef", ExternalRef(kind="ticket", namespace="jira", id="HLP-1", label="t")),
        ("CheckpointOption", CheckpointOption(id="safe", label="low risk", risk="low")),
        (
            "ProposedAction",
            ProposedAction(
                id="pa_1",
                kind="fs:write",
                summary="write",
                permission_scope="fs:write:/tmp/x",
                detail={"path": "/tmp/x"},
                risk="high",
            ),
        ),
        ("Evidence", Evidence(kind="text", content="log")),
        (
            "CheckpointResolution",
            CheckpointResolution(
                by="user_alice",
                action="provide",
                input="42",
                approved_actions=("pa_1",),
                denied_actions=("pa_2",),
                state_patch={"k": 1},
                edited_artifact_ref={"id": "art_1", "version": "v2"},
                comment="c",
                at=NOW,
            ),
        ),
        (
            "HumanInboxItem",
            HumanInboxItem(
                kind="checkpoint",
                action="resolve_checkpoint",
                task_id="task_1",
                subject_id="ckpt_1",
                title="approve?",
                principal="user_alice",
                created_at=NOW,
            ),
        ),
        ("AdapterOperationContext", context),
        (
            "AdapterOutboxRecord",
            AdapterOutboxRecord(
                operation_id="op_1",
                task_id="task_1",
                operation="task.assign",
                request_fingerprint="fp",
                context=context,
                request={"adapter_action": "delegate"},
                result={"run_id": "run_1"},
                state="succeeded",
                created_at=NOW,
                updated_at=NOW,
            ),
        ),
        (
            "IdempotencyRecord",
            IdempotencyRecord(
                task_id="task_1",
                key="k-1",
                operation="task.amend",
                request_fingerprint="fp",
                revision_before=1,
                revision_after=2,
                result={"ok": True},
                audit_seq_start=3,
                audit_seq_end=4,
            ),
        ),
        ("InteractionRef", InteractionRef(channel="voice", session_id="s_1", episode_id="e_1")),
        (
            "ControlSignal",
            ControlSignal(
                strength="soft",
                intent="redirect",
                principal_binding="user_alice",
                confidence=0.7,
                source_kind="speech",
                source_ref="mic-1",
                text="hold on",
                promotion="none",
                run_id="run_1",
                interaction=InteractionRef(channel="voice", session_id="s_1"),
                effective_at=NOW,
                recorded_at=NOW,
            ),
        ),
    ]
    for name, value in cases:
        assert _round_trip(name, value) == value, name


# ── tolerance and failure modes ──


def test_unknown_extra_keys_tolerated():
    spec = TaskSpec(goal="g")
    wire = to_wire(spec)
    wire["x_future_field"] = {"nested": [1, 2]}
    assert from_wire("TaskSpec", wire) == spec


def test_datetime_z_suffix_tolerated():
    amendment = SteeringAmendment(text="x", at=NOW)
    wire = to_wire(amendment)
    assert wire["at"].endswith("+00:00")
    wire["at"] = wire["at"].replace("+00:00", "Z")
    assert from_wire("SteeringAmendment", wire) == amendment


def test_missing_required_field_raises_invalid_spec():
    ops = HumanLoopOperations()
    snapshot = _seed_rich_task(ops)
    wire = to_wire(snapshot)
    del wire["id"]  # schema-required field on Task
    with pytest.raises(ProtocolError) as err:
        from_wire("Task", wire)
    assert err.value.code == "INVALID_SPEC"

    option_wire = to_wire(CheckpointOption(id="a", label="b"))
    del option_wire["label"]  # no JSON schema for CheckpointOption; the builder fails fast
    with pytest.raises(ProtocolError) as err:
        from_wire("CheckpointOption", option_wire)
    assert err.value.code == "INVALID_SPEC"


def test_unknown_name_raises_not_found():
    with pytest.raises(ProtocolError) as err:
        from_wire("NoSuchObject", {})
    assert err.value.code == "NOT_FOUND"


# ── transport integration ──


@pytest.fixture
def transport():
    operations = HumanLoopOperations(adapter=FakeAgentAdapter())
    server = HLPHttpServer(operations).start()
    client = HttpHLPWireClient(server.address, principal="user_alice", timeout=10.0)
    yield server, client
    server.stop()


def test_transport_call_as_reconstructs_task(transport):
    server, client = transport
    created = client.create_task(
        principal="user_alice",
        goal="typed wire",
        acceptance_criteria=("done",),
    )
    client.assign(created["id"], "agent_dev", capability="code")
    client.start(created["id"])
    client.amend(created["id"], text="focus on auth", intent="constrain")

    typed = client.call("task.get", {"task_id": created["id"]}, as_="Task")
    assert isinstance(typed, Task)

    snapshot = server.run_op(server.operations.task_get(created["id"]))
    assert typed == snapshot

    # The plain wire result is exactly to_wire(snapshot).
    wire = client.call("task.get", {"task_id": created["id"]})
    assert wire == to_wire(snapshot)

    # List results pass through untouched even when as_ is set.
    tasks = client.call("task.list", {}, as_="Task")
    assert isinstance(tasks, list)
    assert tasks and isinstance(tasks[0], dict)
