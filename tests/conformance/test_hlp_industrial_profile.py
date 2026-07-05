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
    HLPClient,
    HumanLoopOperations,
    PermissionGrant,
    ProtocolError,
    ProposedAction,
    ArtifactRef,
    AdapterOperationContext,
    AdapterOutboxRecord,
    OwnershipTransfer,
    ProcessAgentAdapter,
    ProcessResult,
    SQLiteHumanLoopStore,
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


def test_audit_events_carry_reducer_ready_payloads():
    ops = HumanLoopOperations()
    task = run(ops.task_create(principal="alice", goal="Reducer audit"))
    run(ops.task_assign(task.id, "agent_worker"))
    run(ops.task_start(task.id))
    run(ops.task_amend(task.id, by="alice", text="Reducer-visible steering."))

    assigned = next(event for event in ops.store.audit_log.all() if event.action == "task.assigned")
    amended = next(event for event in ops.store.audit_log.all() if event.action == "task.amended")

    assert assigned.reducer["subject"] == {"kind": "task", "id": task.id}
    assert assigned.reducer["task"]["state"] == "assigned"
    assert assigned.reducer["task"]["ownership"]["assignee"] == "agent_worker"
    assert assigned.reducer["change"] == {"assignee": "agent_worker"}

    assert amended.reducer["task"]["state"] == "in_progress"
    assert amended.reducer["task"]["steering_count"] == 1
    assert amended.reducer["change"]["text"] == "Reducer-visible steering."
    validate_wire_object("AuditEvent", to_wire(amended))


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
        "AdapterOperationContext",
        "AdapterOutboxRecord",
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

    adapter_context = AdapterOperationContext(
        operation_id="op_schema",
        task_id="task_schema",
        correlation_id="task_schema",
        operation="task.amend",
        idempotency_key=None,
        request_fingerprint="fingerprint",
        task_revision=4,
    )
    validate_wire_object("AdapterOperationContext", to_wire(adapter_context))
    validate_wire_object("AdapterOutboxRecord", to_wire(AdapterOutboxRecord(
        operation_id="op_schema",
        task_id="task_schema",
        operation="task.amend",
        request_fingerprint="fingerprint",
        context=adapter_context,
        request={"adapter_action": "steer"},
    )))

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


def test_adapter_context_is_passed_to_steer_block_and_resume():
    adapter = FakeAgentAdapter()
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops._seed_to_in_progress())
    revision = run(ops.task_get(task.id)).revision

    run(ops.task_amend(
        task.id,
        by="alice",
        text="Use the stable outbox context.",
        expected_task_revision=revision,
        idempotency_key="ctx-amend",
    ))
    checkpoint = run(ops.task_interrupt(
        task.id,
        by="alice",
        prompt="Pause with outbox context.",
        expected_task_revision=revision + 1,
        idempotency_key="ctx-interrupt",
    ))
    blocked_revision = run(ops.task_get(task.id)).revision
    run(ops.checkpoint_resolve(
        checkpoint.id,
        by="alice",
        action="approve",
        expected_task_revision=blocked_revision,
        idempotency_key="ctx-resolve",
    ))

    steer_context = adapter.calls_of("steer")[0][1]["operation_context"]
    block_context = adapter.calls_of("block")[0][1]["operation_context"]
    resume_context = adapter.calls_of("resume")[0][1]["operation_context"]

    assert steer_context["operation"] == "task.amend"
    assert block_context["operation"] == "task.interrupt"
    assert resume_context["operation"] == "checkpoint.resolve"
    assert steer_context["operation_id"].startswith("op_")
    assert block_context["idempotency_key"] == "ctx-interrupt"
    assert resume_context["task_id"] == task.id
    records = ops.store.adapter_outbox_records()
    assert {record.operation for record in records} == {
        "task.assign",
        "task.amend",
        "task.interrupt",
        "checkpoint.resolve",
    }
    assert all(record.state == "succeeded" for record in records)


def test_adapter_context_is_passed_to_delegate_handoff_and_cancel():
    adapter = FakeAgentAdapter()
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops.task_create(principal="alice", goal="Cover all adapter calls"))

    run(ops.task_assign(task.id, "agent_initial"))
    run(ops.task_start(task.id))
    run(ops.ownership_transfer(
        task.id,
        "agent_writer",
        "handoff",
        actor="agent_initial",
    ))
    run(ops.task_cancel(task.id, by="alice"))

    delegate_context = adapter.calls_of("delegate")[0][1]["operation_context"]
    handoff_context = adapter.calls_of("handoff")[0][1]["operation_context"]
    cancel_context = adapter.calls_of("cancel")[0][1]["operation_context"]

    assert delegate_context["operation"] == "task.assign"
    assert handoff_context["operation"] == "ownership.transfer"
    assert cancel_context["operation"] == "task.cancel"
    assert delegate_context["task_id"] == task.id
    assert handoff_context["correlation_id"] == task.id
    assert cancel_context["operation_id"].startswith("op_")

    records = ops.store.adapter_outbox_records()
    assert len(records) == 3
    assert all(record.state == "succeeded" for record in records)


def test_outbox_is_persisted_before_adapter_side_effect():
    class InspectingAdapter(FakeAgentAdapter):
        def __init__(self, ops):
            super().__init__()
            self.ops = ops
            self.state_seen_before_side_effect = None

        async def steer(self, run_id, amendment, *, context=None):
            self.state_seen_before_side_effect = (
                self.ops.store.get_adapter_outbox_record(context.operation_id).state
            )
            await super().steer(run_id, amendment, context=context)

    ops = HumanLoopOperations()
    adapter = InspectingAdapter(ops)
    ops.adapter = adapter
    task = run(ops._seed_to_in_progress())
    revision = run(ops.task_get(task.id)).revision

    run(ops.task_amend(
        task.id,
        by="alice",
        text="Outbox first.",
        expected_task_revision=revision,
        idempotency_key="outbox-first",
    ))

    assert adapter.state_seen_before_side_effect == "pending"


def test_retry_reuses_checkpoint_id_from_pending_adapter_outbox():
    class FailAfterSideEffectAdapter(FakeAgentAdapter):
        def __init__(self):
            super().__init__()
            self.block_checkpoint_ids = []

        async def block(self, run_id, checkpoint_id, reason, *, context=None):
            self.block_checkpoint_ids.append(checkpoint_id)
            if len(self.block_checkpoint_ids) == 1:
                raise RuntimeError("simulated crash after adapter side effect")
            await super().block(run_id, checkpoint_id, reason, context=context)

    adapter = FailAfterSideEffectAdapter()
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops._seed_to_in_progress())
    revision = run(ops.task_get(task.id)).revision

    with pytest.raises(RuntimeError):
        run(ops.task_interrupt(
            task.id,
            by="alice",
            prompt="Reuse checkpoint id.",
            expected_task_revision=revision,
            idempotency_key="pending-outbox-retry",
        ))

    checkpoint = run(ops.task_interrupt(
        task.id,
        by="alice",
        prompt="Reuse checkpoint id.",
        expected_task_revision=revision,
        idempotency_key="pending-outbox-retry",
    ))

    assert adapter.block_checkpoint_ids == [
        adapter.block_checkpoint_ids[0],
        adapter.block_checkpoint_ids[0],
    ]
    assert checkpoint.id == adapter.block_checkpoint_ids[0]
    assert ops.store.adapter_outbox_records()[0].state == "succeeded"


def test_retry_reuses_amendment_payload_from_pending_adapter_outbox():
    class FailAfterSideEffectAdapter(FakeAgentAdapter):
        def __init__(self):
            super().__init__()
            self.steer_amendments = []

        async def steer(self, run_id, amendment, *, context=None):
            self.steer_amendments.append(amendment)
            if len(self.steer_amendments) == 1:
                raise RuntimeError("simulated crash after adapter side effect")
            await super().steer(run_id, amendment, context=context)

    adapter = FailAfterSideEffectAdapter()
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops._seed_to_in_progress())
    revision = run(ops.task_get(task.id)).revision

    with pytest.raises(RuntimeError):
        run(ops.task_amend(
            task.id,
            by="alice",
            text="Reuse amendment payload.",
            expected_task_revision=revision,
            idempotency_key="pending-amend-retry",
        ))

    amended = run(ops.task_amend(
        task.id,
        by="alice",
        text="Reuse amendment payload.",
        expected_task_revision=revision,
        idempotency_key="pending-amend-retry",
    ))

    assert adapter.steer_amendments[1] == adapter.steer_amendments[0]
    assert amended.steering_log[0].at.isoformat() == adapter.steer_amendments[0]["at"]
    assert ops.store.adapter_outbox_records()[0].state == "succeeded"


def test_sqlite_restart_retries_pending_adapter_outbox_with_context(tmp_path):
    class FailAfterSideEffectAdapter(FakeAgentAdapter):
        async def block(self, run_id, checkpoint_id, reason, *, context=None):
            self._require_run(run_id, "block", context=context)
            raise RuntimeError("simulated crash after adapter side effect")

    db_path = tmp_path / "hlp-outbox.db"
    first = HLPClient(
        store=SQLiteHumanLoopStore(db_path),
        adapter=FailAfterSideEffectAdapter(),
    )
    task = run(first.create_task(principal="user_alice", goal="Recover outbox"))
    run(first.delegate(task.id, "agent_worker"))
    run(first.start(task.id))
    revision = run(first.get_task(task.id)).revision

    with pytest.raises(RuntimeError):
        run(first.interrupt(
            task.id,
            by="user_alice",
            prompt="Persist pending outbox.",
            expected_task_revision=revision,
            idempotency_key="sqlite-pending-outbox",
        ))

    restarted_store = SQLiteHumanLoopStore(db_path)
    pending = next(
        record for record in restarted_store.adapter_outbox_records()
        if record.operation == "task.interrupt"
    )
    assert pending.state == "pending"

    second_adapter = FakeAgentAdapter()
    second = HLPClient(
        store=restarted_store,
        adapter=second_adapter,
    )
    checkpoint = run(second.interrupt(
        task.id,
        by="user_alice",
        prompt="Persist pending outbox.",
        expected_task_revision=revision,
        idempotency_key="sqlite-pending-outbox",
    ))

    block_call = second_adapter.calls_of("block")[0][1]
    assert checkpoint.id == pending.request["checkpoint_id"]
    assert block_call["checkpoint_id"] == pending.request["checkpoint_id"]
    assert block_call["operation_context"]["operation_id"] == pending.operation_id
    restored_interrupt = next(
        record for record in restarted_store.adapter_outbox_records()
        if record.operation == "task.interrupt"
    )
    assert restored_interrupt.state == "succeeded"


def test_sqlite_restart_retries_pending_delegate_outbox_with_context(tmp_path):
    class FailAfterSideEffectAdapter(FakeAgentAdapter):
        async def delegate(self, *args, **kwargs):
            await super().delegate(*args, **kwargs)
            raise RuntimeError("simulated crash after delegate side effect")

    db_path = tmp_path / "hlp-delegate-outbox.db"
    first = HLPClient(
        store=SQLiteHumanLoopStore(db_path),
        adapter=FailAfterSideEffectAdapter(),
    )
    task = run(first.create_task(principal="user_alice", goal="Recover delegate outbox"))

    with pytest.raises(RuntimeError):
        run(first.delegate(task.id, "agent_worker"))

    restarted_store = SQLiteHumanLoopStore(db_path)
    pending = restarted_store.adapter_outbox_records()[0]
    assert pending.operation == "task.assign"
    assert pending.state == "pending"

    second_adapter = FakeAgentAdapter()
    second = HLPClient(
        store=restarted_store,
        adapter=second_adapter,
    )
    handle = run(second.delegate(task.id, "agent_worker"))

    delegate_call = second_adapter.calls_of("delegate")[0][1]
    assert handle.task_id == task.id
    assert delegate_call["operation_context"]["operation_id"] == pending.operation_id
    assert run(second.get_task(task.id)).state == "assigned"
    assert restarted_store.adapter_outbox_records()[0].state == "succeeded"


def test_delegate_context_preserves_legacy_keyword_adapter_compatibility():
    class KeywordOnlyDelegateAdapter(FakeAgentAdapter):
        async def delegate(self, *, task_id, agent_id, capability, input):
            return await super().delegate(
                task_id=task_id,
                agent_id=agent_id,
                capability=capability,
                input=input,
            )

    adapter = KeywordOnlyDelegateAdapter()
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops.task_create(principal="alice", goal="Keyword-only delegate"))

    run(ops.task_assign(task.id, "agent_keyword"))

    assert adapter.calls_of("delegate")[0][1]["task_id"] == task.id
    assert ops.store.adapter_outbox_records()[0].state == "succeeded"


def test_operation_context_is_passed_to_var_keyword_adapter():
    class VarKeywordDelegateAdapter(FakeAgentAdapter):
        def __init__(self):
            super().__init__()
            self.kwargs_seen = None

        async def delegate(self, task_id, agent_id, capability, input, **kwargs):
            self.kwargs_seen = kwargs
            return await super().delegate(
                task_id=task_id,
                agent_id=agent_id,
                capability=capability,
                input=input,
            )

    adapter = VarKeywordDelegateAdapter()
    ops = HumanLoopOperations(adapter=adapter)
    task = run(ops.task_create(principal="alice", goal="Var keyword delegate"))

    run(ops.task_assign(task.id, "agent_kwargs"))

    assert adapter.kwargs_seen["operation_context"].operation == "task.assign"


def test_process_adapter_serializes_hlp_operation_context():
    captured = {}

    async def runner(command, request, timeout):
        captured["request"] = request
        if request["operation"] == "delegate":
            return ProcessResult(
                exit_code=0,
                stdout='{"run_id":"run_process","correlation_id":"task_outbox"}',
                stderr="",
            )
        return ProcessResult(exit_code=0, stdout="{}", stderr="")

    adapter = ProcessAgentAdapter(
        command=("agent", "run", "--json"),
        name="industrial-process",
        runner=runner,
    )
    run_id = run(adapter.delegate(
        task_id="task_outbox",
        agent_id="agent_proc",
        capability="industrial",
        input={"goal": "ctx"},
    ))
    context = AdapterOperationContext(
        operation_id="op_test",
        task_id="task_outbox",
        correlation_id="task_outbox",
        operation="task.amend",
        idempotency_key="idem",
        request_fingerprint="fingerprint",
        task_revision=3,
    )

    run(adapter.steer(run_id, {"text": "ctx"}, context=context))

    assert captured["request"]["operation_context"] == {
        "operation_id": "op_test",
        "task_id": "task_outbox",
        "correlation_id": "task_outbox",
        "operation": "task.amend",
        "idempotency_key": "idem",
        "request_fingerprint": "fingerprint",
        "task_revision": 3,
        "schema_version": HLP_SCHEMA_VERSION,
        "profile": HLP_PROFILE,
    }


def test_process_adapter_serializes_delegate_handoff_and_cancel_contexts():
    captured = []

    async def runner(command, request, timeout):
        captured.append(request)
        if request["operation"] == "delegate":
            return ProcessResult(
                exit_code=0,
                stdout='{"run_id":"run_process","correlation_id":"task_process"}',
                stderr="",
            )
        if request["operation"] == "handoff":
            return ProcessResult(
                exit_code=0,
                stdout='{"run_id":"run_handoff","correlation_id":"task_process"}',
                stderr="",
            )
        return ProcessResult(exit_code=0, stdout="{}", stderr="")

    adapter = ProcessAgentAdapter(
        command=("agent", "run", "--json"),
        name="industrial-process",
        runner=runner,
    )
    delegate_context = AdapterOperationContext(
        operation_id="op_delegate",
        task_id="task_process",
        correlation_id="task_process",
        operation="task.assign",
        idempotency_key=None,
        request_fingerprint="fp_delegate",
        task_revision=0,
    )
    handoff_context = AdapterOperationContext(
        operation_id="op_handoff",
        task_id="task_process",
        correlation_id="task_process",
        operation="ownership.transfer",
        idempotency_key=None,
        request_fingerprint="fp_handoff",
        task_revision=2,
    )
    cancel_context = AdapterOperationContext(
        operation_id="op_cancel",
        task_id="task_process",
        correlation_id="task_process",
        operation="task.cancel",
        idempotency_key=None,
        request_fingerprint="fp_cancel",
        task_revision=3,
    )

    run_id = run(adapter.delegate(
        task_id="task_process",
        agent_id="agent_proc",
        capability="industrial",
        input={"goal": "ctx"},
        operation_context=delegate_context,
    ))
    handoff_run_id = run(adapter.handoff(
        run_id,
        "agent_next",
        {"task_id": "task_process"},
        operation_context=handoff_context,
    ))
    run(adapter.cancel(handoff_run_id, "cancelled by alice", operation_context=cancel_context))

    assert [
        request["operation_context"]["operation_id"]
        for request in captured
    ] == ["op_delegate", "op_handoff", "op_cancel"]
