from __future__ import annotations

import asyncio

from loops.hlp import (
    ArtifactPayload,
    ClaudeCodeCLIAdapter,
    CheckpointOption,
    CodexCLIAdapter,
    CrewAIAdapter,
    FakeAgentAdapter,
    HermesCLIAdapter,
    HermsCLIAdapter,
    HLPClient,
    InMemoryEventBus,
    LangGraphAdapter,
    OpenAIAgentsSDKAdapter,
    OpenAIPythonSDKAdapter,
    PythonCallableAgentAdapter,
    SQLiteHumanLoopStore,
)
from examples.hlp_e2e_demo import run_demo


def run(coro):
    return asyncio.run(coro)


def test_hlp_client_runs_human_loop_without_low_level_operations():
    adapter = FakeAgentAdapter()
    client = HLPClient(adapter=adapter)

    task = run(client.create_task(
        principal="user_alice",
        goal="Review PR #1234 for security issues",
        type="code-review",
        acceptance_criteria=("All reviewer comments resolved",),
    ))
    run_handle = run(client.delegate(
        task.id,
        agent_id="agent_coder",
        capability="code-review",
        input={"goal": task.spec.goal, "repository": "web"},
    ))
    run(client.start(task.id))
    checkpoint = run(client.raise_checkpoint(
        task_id=task.id,
        kind="choice",
        prompt="Delete obsolete index?",
        options=(
            CheckpointOption(id="safe", label="Keep risky index", risk="low"),
            CheckpointOption(id="fast", label="Delete all", risk="high"),
        ),
        raised_by="agent_coder",
    ))
    run(client.resolve_checkpoint(
        checkpoint.id,
        by="user_alice",
        action="choose",
        choice="safe",
        comment="Prefer the lower-risk path.",
    ))
    artifact = run(client.commit_artifact(
        task_id=task.id,
        type="report",
        payload=ArtifactPayload(
            kind="inline",
            uri="mem://report-v1",
            checksum="sha256:report-v1",
        ),
        produced_by="agent_coder",
    ))
    review = run(client.submit_review(
        task_id=task.id,
        artifact_id=artifact.id,
        reviewer="user_bob",
        verdict="approved",
    ))
    entry = run(client.write_ledger(
        scope="project:web",
        key="pr.1234.status",
        value="approved",
        by=task.id,
    ))
    history = run(client.replay_audit(task.id))

    assert run_handle.task_id == task.id
    assert run_handle.correlation_id == task.id
    assert adapter.task_of_run(run_handle.run_id) == task.id
    assert adapter.calls[0][1]["capability"] == "code-review"
    assert adapter.calls[0][1]["input"] == {
        "goal": task.spec.goal,
        "repository": "web",
    }
    assert [name for name, _payload in adapter.calls] == [
        "delegate",
        "block",
        "resume",
    ]
    assert review.verdict == "approved"
    assert entry.value == "approved"
    assert [event.action for event in history] == [
        "task.created",
        "task.assigned",
        "task.started",
        "task.checkpoint.raised",
        "task.checkpoint.resolved",
        "artifact.committed",
        "review.submitted",
        "ledger.written",
    ]


def test_fake_agent_adapter_records_contract_calls():
    adapter = FakeAgentAdapter()

    delegate = run(adapter.delegate(
        task_id="task_123",
        agent_id="agent_reviewer",
        capability="code-review",
        input={"goal": "review"},
    ))
    run(adapter.block(delegate, "ckpt_123", "Need approval"))
    run(adapter.resume(delegate, {"action": "approve"}))
    handoff = run(adapter.handoff(delegate, "agent_writer", {"reason": "rewrite"}))
    run(adapter.cancel(handoff, "demo done"))
    health = run(adapter.healthcheck())

    assert adapter.task_of_run(delegate) == "task_123"
    assert adapter.task_of_run(handoff) == "task_123"
    assert health == {
        "status": "ok",
        "adapter": "fake",
        "runs": 2,
    }
    assert [name for name, _payload in adapter.calls] == [
        "delegate",
        "block",
        "resume",
        "handoff",
        "cancel",
        "healthcheck",
    ]


def test_named_adapter_targets_are_available_without_optional_dependencies():
    async def handler(request):
        return {"handled": request["task_id"], "agent": request["agent_id"]}

    python_adapter = PythonCallableAgentAdapter("custom-python", handler)
    openai_agents = OpenAIAgentsSDKAdapter(handler)
    openai_python = OpenAIPythonSDKAdapter(handler)
    langgraph = LangGraphAdapter(handler)
    crewai = CrewAIAdapter(handler)
    codex = CodexCLIAdapter(command=("codex", "exec"))
    claude = ClaudeCodeCLIAdapter(command=("claude", "-p"))
    herms = HermsCLIAdapter(command=("herms", "run"))

    run_id = run(python_adapter.delegate(
        task_id="task_custom",
        agent_id="agent_custom",
        capability="demo",
        input={"goal": "demo"},
    ))
    assert python_adapter.results[run_id] == {
        "handled": "task_custom",
        "agent": "agent_custom",
    }

    assert run(openai_agents.healthcheck())["adapter"] == "openai-agents-sdk"
    assert run(openai_python.healthcheck())["adapter"] == "openai-python-sdk"
    assert run(langgraph.healthcheck())["adapter"] == "langgraph"
    assert run(crewai.healthcheck())["adapter"] == "crewai"
    assert run(codex.healthcheck())["command"] == ("codex", "exec")
    assert run(claude.healthcheck())["adapter"] == "claude-code-cli"
    assert HermesCLIAdapter is HermsCLIAdapter
    assert run(herms.healthcheck())["adapter"] == "herms-cli"


def test_hlp_client_emits_lifecycle_events_in_order():
    bus = InMemoryEventBus()
    client = HLPClient(adapter=FakeAgentAdapter(), event_bus=bus)

    task = run(client.create_task(principal="user_alice", goal="Ship release notes"))
    run_handle = run(client.delegate(task.id, "agent_writer"))
    run(client.start(task.id))
    checkpoint = run(client.raise_checkpoint(
        task_id=task.id,
        kind="approval",
        prompt="Publish draft?",
        raised_by="agent_writer",
    ))
    run(client.resolve_checkpoint(checkpoint.id, by="user_alice", action="approve"))
    artifact = run(client.commit_artifact(
        task_id=task.id,
        type="release-notes",
        payload=ArtifactPayload(
            kind="inline",
            uri="mem://release-notes-v1",
            checksum="sha256:release-notes-v1",
        ),
        produced_by="agent_writer",
    ))
    run(client.submit_review(
        task_id=task.id,
        artifact_id=artifact.id,
        reviewer="user_alice",
        verdict="approved",
    ))
    run(client.write_ledger("project:demo", "release.status", "approved", by=task.id))
    run(client.replay_audit(task.id))

    assert run_handle.run_id
    assert [event.action for event in bus.events] == [
        "task.created",
        "task.delegated",
        "task.started",
        "checkpoint.raised",
        "checkpoint.resolved",
        "artifact.committed",
        "review.submitted",
        "ledger.written",
        "audit.replayed",
    ]
    assert all(event.task_id == task.id for event in bus.events)


def test_sqlite_store_persists_hlp_state_across_restart(tmp_path):
    db_path = tmp_path / "hlp.db"
    first = HLPClient(
        store=SQLiteHumanLoopStore(db_path),
        adapter=FakeAgentAdapter(),
    )

    task = run(first.create_task(principal="user_alice", goal="Persist HLP state"))
    run(first.delegate(task.id, "agent_persistent"))
    run(first.start(task.id))
    checkpoint = run(first.raise_checkpoint(
        task_id=task.id,
        kind="approval",
        prompt="Continue?",
        raised_by="agent_persistent",
    ))
    run(first.resolve_checkpoint(checkpoint.id, by="user_alice", action="approve"))
    artifact = run(first.commit_artifact(
        task_id=task.id,
        type="report",
        payload=ArtifactPayload(
            kind="inline",
            uri="mem://persisted-report",
            checksum="sha256:persisted-report",
        ),
        produced_by="agent_persistent",
    ))
    review = run(first.submit_review(
        task_id=task.id,
        artifact_id=artifact.id,
        reviewer="user_alice",
        verdict="approved",
    ))
    run(first.write_ledger("project:persist", "status", "approved", by=task.id))

    second = HLPClient(
        store=SQLiteHumanLoopStore(db_path),
        adapter=FakeAgentAdapter(),
    )

    restored_task = run(second.get_task(task.id))
    restored_checkpoint = second.store.get_checkpoint(checkpoint.id)
    restored_artifact = second.store.get_artifact(artifact.id)
    restored_review = second.store.get_review(review.id)
    restored_ledger_value = run(second.read_ledger("project:persist", "status"))
    restored_history = run(second.replay_audit(task.id))

    assert restored_task.id == task.id
    assert restored_task.state == "accepted"
    assert restored_checkpoint.state == "resolved"
    assert restored_artifact.version == "v1"
    assert restored_review.verdict == "approved"
    assert restored_ledger_value == "approved"
    assert [event.action for event in restored_history][-3:] == [
        "artifact.committed",
        "review.submitted",
        "ledger.written",
    ]


def test_hlp_e2e_demo_runs_without_external_services():
    result = run(run_demo())

    assert result["task_id"].startswith("task_")
    assert result["run_id"].startswith("run_")
    assert result["checkpoint_decision"] == "safe"
    assert result["artifact_version"] == "v1"
    assert result["review_verdict"] == "approved"
    assert result["ledger_status"] == "approved"
    assert result["audit_actions"] == [
        "task.created",
        "task.assigned",
        "task.started",
        "task.checkpoint.raised",
        "task.checkpoint.resolved",
        "artifact.committed",
        "review.submitted",
        "ledger.written",
    ]
