"""HTTP transport binding tests: real sockets, no new dependencies.

Covers the full lifecycle round-trip, CAS/idempotency over the wire, the
§6.1 error-code to HTTP-status mapping, the X-HLP-Principal requirement,
and the audit-event SSE stream.
"""

from __future__ import annotations

import urllib.error
import urllib.request

import pytest

from loops.hlp import FakeAgentAdapter
from loops.hlp.operations import HumanLoopOperations
from loops.hlp.transport import HLPHttpServer, HttpHLPWireClient, TransportError


@pytest.fixture
def transport():
    operations = HumanLoopOperations(adapter=FakeAgentAdapter())
    server = HLPHttpServer(operations).start()
    client = HttpHLPWireClient(server.address, principal="user_alice", timeout=10.0)
    yield server, client
    server.stop()


def _lifecycle(transport):
    server, client = transport
    task = client.create_task(
        principal="user_alice",
        goal="transport lifecycle",
        acceptance_criteria=("done",),
    )
    client.assign(task["id"], "agent_dev", capability="code")
    return server, client, task


def test_health_and_version(transport):
    _server, client = transport
    assert client.health()["status"] == "ok"
    version = client.version()
    assert version["spec_version"] == "0.2.0-draft"
    assert version["schema_version"] == "0.2"
    assert version["profile"] == "HLP-industrial"


def test_full_lifecycle_round_trip(transport):
    server, client, task = _lifecycle(transport)
    assert task["state"] == "created"
    assert task["revision"] == 0

    started = client.start(task["id"])
    assert started["state"] == "in_progress"

    amended = client.amend(task["id"], text="focus on auth", intent="constrain")
    assert amended["state"] == "in_progress"
    assert amended["steering_log"][0]["text"] == "focus on auth"

    interrupted = client.interrupt(task["id"], prompt="hold on")
    assert interrupted["state"] == "pending"
    assert interrupted["kind"] == "interrupt"

    resolved = client.resolve_checkpoint(interrupted["id"], action="approve")
    assert resolved["state"] == "resolved"

    artifact = client.commit_artifact(
        task_id=task["id"],
        type="report",
        payload={"kind": "inline", "uri": "mem://v1", "checksum": "sha256:v1", "size": 2},
        produced_by="agent_dev",
    )
    assert artifact["version"] == "v1"

    review = client.submit_review(
        task_id=task["id"],
        artifact_id=artifact["id"],
        verdict="approved",
    )
    assert review["verdict"] == "approved"

    entry = client.write_ledger("project:transport", "lifecycle.status", "approved", by=task["id"])
    assert entry["value"] == "approved"

    final = client.call("task.get", {"task_id": task["id"]})
    assert final["state"] == "completed"

    audit = client.replay_audit(task["id"])
    actions = [event["action"] for event in audit]
    assert actions[:3] == ["task.created", "task.assigned", "task.started"]
    assert "task.completed" in actions

    # The SSE stream carries the same audit events in seq order.
    streamed = list(client.events(after=0, max_seconds=1.0))
    assert [event["action"] for event in streamed] == actions
    assert [event["seq"] for event in streamed] == sorted(event["seq"] for event in streamed)


def test_cas_conflict_maps_to_409(transport):
    _server, client, task = _lifecycle(transport)
    client.start(task["id"])
    with pytest.raises(TransportError) as err:
        client.call(
            "task.amend",
            {"task_id": task["id"], "text": "stale"},
            expected_task_revision=99,
        )
    assert err.value.status == 409
    assert err.value.code == "CONFLICT"


def test_idempotency_key_replay_over_http(transport):
    server, client, task = _lifecycle(transport)
    client.start(task["id"])

    first = client.call(
        "task.amend",
        {"task_id": task["id"], "text": "once"},
        idempotency_key="k-http-1",
    )
    second = client.call(
        "task.amend",
        {"task_id": task["id"], "text": "once"},
        idempotency_key="k-http-1",
    )
    assert first["revision"] == second["revision"]
    assert len(second["steering_log"]) == 1
    audit = client.replay_audit(task["id"])
    assert [event["action"] for event in audit].count("task.amended") == 1

    with pytest.raises(TransportError) as err:
        client.call(
            "task.amend",
            {"task_id": task["id"], "text": "different fingerprint"},
            idempotency_key="k-http-1",
        )
    assert err.value.status == 409


def test_mutating_ops_require_principal_header(transport):
    server, _client = transport
    anonymous = HttpHLPWireClient(server.address, timeout=10.0)
    with pytest.raises(TransportError) as err:
        anonymous.call("task.create", {"principal": "user_mallory", "goal": "no header"})
    assert err.value.status == 401
    assert err.value.code == "UNAUTHORIZED"

    # Read ops work without the header.
    assert anonymous.call("task.list") == []


def test_error_status_mapping(transport):
    _server, client, task = _lifecycle(transport)

    with pytest.raises(TransportError) as not_found:
        client.call("task.get", {"task_id": "task_missing"})
    assert not_found.value.status == 404

    client.start(task["id"])
    with pytest.raises(TransportError) as precondition:
        client.start(task["id"])  # already in_progress -> illegal transition
    assert precondition.value.status == 412
    assert precondition.value.code == "PRECONDITION_FAILED"

    with pytest.raises(TransportError) as invalid:
        client.call("task.create", {"principal": "user_alice", "goal": ""})
    assert invalid.value.status == 400
    assert invalid.value.code == "INVALID_SPEC"


def test_checkpoint_expired_maps_to_410(transport):
    _server, client, task = _lifecycle(transport)
    client.start(task["id"])
    ckpt = client.raise_checkpoint(
        task_id=task["id"],
        kind="approval",
        prompt="ok?",
        raised_by="agent_dev",
    )
    client.call("checkpoint.expire", {"ckpt_id": ckpt["id"]})
    with pytest.raises(TransportError) as err:
        client.resolve_checkpoint(ckpt["id"], action="approve")
    assert err.value.status == 410
    assert err.value.code == "CHECKPOINT_EXPIRED"


def test_unknown_operation_and_route(transport):
    server, _client = transport
    with pytest.raises(TransportError) as err:
        server_client = HttpHLPWireClient(server.address, principal="user_alice", timeout=10.0)
        server_client.call("task.explode", {})
    assert err.value.status == 404

    request = urllib.request.Request(f"{server.address}/v1/nope", method="GET")
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(request, timeout=10.0)
    assert err.value.code == 404


def test_structured_params_builders(transport):
    _server, client, task = _lifecycle(transport)
    client.start(task["id"])
    ckpt = client.raise_checkpoint(
        task_id=task["id"],
        kind="choice",
        prompt="pick",
        raised_by="agent_dev",
        options=(
            {"id": "safe", "label": "low risk", "risk": "low"},
            {"id": "fast", "label": "medium risk", "risk": "medium"},
        ),
    )
    assert [option["id"] for option in ckpt["options"]] == ["safe", "fast"]
    resolved = client.resolve_checkpoint(ckpt["id"], action="choose", choice="safe")
    assert resolved["resolution"]["choice"] == "safe"

    inbox = client.human_inbox()
    assert isinstance(inbox, list)


def test_sse_after_cursor_skips_replay(transport):
    server, client, task = _lifecycle(transport)
    first = list(client.events(after=0, max_seconds=1.0))
    assert first
    cursor = first[-1]["seq"]

    client.start(task["id"])
    later = list(client.events(after=cursor, max_seconds=1.0))
    assert later
    assert all(event["seq"] > cursor for event in later)
    assert [event["action"] for event in later] == ["task.started"]
