from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from loops.hlp import (
    ArtifactPayload,
    HLP_JSON_SCHEMAS,
    HLP_PROFILE,
    HLP_SCHEMA_VERSION,
    HLP_SPEC_VERSION,
    FakeAgentAdapter,
    HumanLoopOperations,
    PermissionGrant,
    ProtocolError,
    ProposedAction,
    ArtifactRef,
    OwnershipTransfer,
    is_permission_scope_pre_authorized,
    negotiate_hlp_version,
    permission_scope_matches,
    schema_for,
    to_wire,
    validate_wire_object,
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


def test_permission_scope_grammar_normalizes_and_rejects_invalid_scopes():
    grant = PermissionGrant(
        scope=" fs:/repo/main:* ",
        decision="allow",
        granted_by="user_alice",
    )

    assert grant.scope == "fs:/repo/main:*"
    assert permission_scope_matches("fs:/repo/main:*", "fs:/repo/main/file.py")
    assert not permission_scope_matches("fs:/repo/main:*", "net:https://example.com")

    with pytest.raises(ProtocolError) as exc:
        PermissionGrant(scope="fs repo write", decision="allow", granted_by="user_alice")
    assert exc.value.code == "INVALID_SPEC"


def test_permission_scope_deny_precedence_and_expiry():
    now = datetime.now(timezone.utc)
    grants = (
        PermissionGrant(
            scope="fs:/repo:*",
            decision="allow",
            until="task",
            granted_by="user_alice",
        ),
        PermissionGrant(
            scope="fs:/repo/secrets:*",
            decision="deny",
            until="task",
            granted_by="user_alice",
        ),
        PermissionGrant(
            scope="net:https://api.example.com/*",
            decision="allow",
            until=now - timedelta(seconds=1),
            granted_by="user_alice",
        ),
    )

    assert is_permission_scope_pre_authorized(grants, "fs:/repo/src/app.py", at=now)
    assert not is_permission_scope_pre_authorized(grants, "fs:/repo/secrets/key.txt", at=now)
    assert not is_permission_scope_pre_authorized(
        grants,
        "net:https://api.example.com/users",
        at=now,
    )
    assert not is_permission_scope_pre_authorized(grants, "tool:mcp/git.apply", at=now)


def test_proposed_action_carries_permission_scope_for_grant_matching():
    action = ProposedAction(
        id="apply_patch",
        kind="tool",
        summary="Apply generated patch",
        permission_scope="fs:/repo:*",
    )

    assert action.permission_scope == "fs:/repo:*"


def test_audit_log_is_tamper_evident_hash_chain():
    ops = HumanLoopOperations()
    task = run(ops._seed_to_in_progress())
    run(ops.task_amend(task.id, by="alice", text="Record hash chain."))

    events = ops.store.audit_log.all()

    assert ops.store.audit_log.verify_hash_chain()
    assert events[0].prev_hash == ""
    assert all(event.hash.startswith("sha256:") for event in events)
    assert events[1].prev_hash == events[0].hash
    assert events[-1].schema_version == "0.2"
    assert events[-1].profile == "HLP-industrial"

    ops.store.audit_log._events[1] = replace(events[1], action="tampered")

    assert not ops.store.audit_log.verify_hash_chain()


def test_json_schema_registry_covers_industrial_wire_objects():
    assert set(HLP_JSON_SCHEMAS) >= {
        "Task",
        "Checkpoint",
        "Ownership",
        "Review",
        "Artifact",
        "Ledger",
        "ProtocolError",
        "AuditEvent",
        "HarnessEvent",
        "HarnessEventDelivery",
        "PermissionGrant",
        "ProposedAction",
        "VersionNegotiation",
    }

    protocol_error = ProtocolError("CONFLICT", "revision conflict").to_dict(
        operation_id="op_1",
        correlation_id="task_1",
    )
    validate_wire_object("ProtocolError", protocol_error)
    assert protocol_error["profile"] == HLP_PROFILE

    grant = PermissionGrant(scope="fs:/repo:*", decision="allow", granted_by="user_alice")
    validate_wire_object("PermissionGrant", {
        "scope": grant.scope,
        "decision": grant.decision,
        "until": grant.until,
        "granted_by": grant.granted_by,
        "granted_at": grant.granted_at.isoformat(),
        "schema_version": HLP_SCHEMA_VERSION,
        "profile": HLP_PROFILE,
    })

    schema = schema_for("ProtocolError")
    assert schema["properties"]["spec_version"]["const"] == HLP_SPEC_VERSION
    assert schema["properties"]["schema_version"]["const"] == HLP_SCHEMA_VERSION


def test_schema_for_returns_copy_and_unknown_schema_is_not_found():
    schema = schema_for("ProtocolError")
    schema["properties"]["schema_version"]["const"] = "mutated"

    assert schema_for("ProtocolError")["properties"]["schema_version"]["const"] == HLP_SCHEMA_VERSION

    with pytest.raises(ProtocolError) as exc:
        schema_for("MissingSchema")
    assert exc.value.code == "NOT_FOUND"


def test_validate_wire_object_rejects_missing_wrong_type_and_bad_const():
    with pytest.raises(ProtocolError) as missing:
        validate_wire_object("ProtocolError", {"code": "CONFLICT"})
    assert missing.value.code == "INVALID_SPEC"

    invalid_type = ProtocolError("CONFLICT").to_dict()
    invalid_type["retryable"] = "yes"
    with pytest.raises(ProtocolError) as wrong_type:
        validate_wire_object("ProtocolError", invalid_type)
    assert wrong_type.value.code == "INVALID_SPEC"

    invalid_const = ProtocolError("CONFLICT").to_dict()
    invalid_const["schema_version"] = "9.0"
    with pytest.raises(ProtocolError) as bad_const:
        validate_wire_object("ProtocolError", invalid_const)
    assert bad_const.value.code == "VERSION_UNSUPPORTED"


def test_wire_serialization_preserves_aliases_and_rfc3339_timestamps():
    transfer = OwnershipTransfer(from_="agent_old", to="agent_new", via="handoff")
    artifact_ref = ArtifactRef(task_id="task_1", as_="input")

    transfer_wire = to_wire(transfer)
    ref_wire = to_wire(artifact_ref)

    assert "from" in transfer_wire
    assert "from_" not in transfer_wire
    assert transfer_wire["at"].endswith("+00:00")
    assert "as" in ref_wire
    assert "as_" not in ref_wire
    assert ref_wire["schema_version"] == HLP_SCHEMA_VERSION
    assert ref_wire["profile"] == HLP_PROFILE


def test_version_negotiation_selects_shared_profile_and_fails_fast():
    negotiated = negotiate_hlp_version(
        spec_versions=(HLP_SPEC_VERSION, "0.1.0-draft"),
        schema_versions=(HLP_SCHEMA_VERSION,),
        profiles=("HLP-integrated", HLP_PROFILE),
    )

    assert negotiated.spec_version == HLP_SPEC_VERSION
    assert negotiated.schema_version == HLP_SCHEMA_VERSION
    assert negotiated.profile == HLP_PROFILE

    with pytest.raises(ProtocolError) as exc:
        negotiate_hlp_version(
            spec_versions=("9.0.0",),
            schema_versions=(HLP_SCHEMA_VERSION,),
            profiles=(HLP_PROFILE,),
        )

    assert exc.value.code == "VERSION_UNSUPPORTED"
    validate_wire_object("VersionNegotiation", negotiated.to_dict())
