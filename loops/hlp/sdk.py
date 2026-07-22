from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .adapters import AgentAdapter, AgentRunHandle, FakeAgentAdapter
from .events import EventBus, HLPEvent, InMemoryEventBus
from .objects import (
    AdapterOutboxRecord,
    Artifact,
    ArtifactPayload,
    Checkpoint,
    CheckpointOption,
    Constraints,
    Evidence,
    HumanInboxItem,
    InputRef,
    LedgerEntry,
    ProposedAction,
    Review,
    ReviewComment,
    ReviewPolicy,
    RunProgressSnapshot,
    Task,
)
from .operations import HumanLoopOperations
from .store import HumanLoopStore
from .types import (
    CheckpointKind,
    CheckpointResolutionAction,
    ProtocolError,
    ReviewKind,
    ReviewVerdict,
    SteeringIntent,
)


@dataclass
class HLPClient:
    """Stable SDK facade for Human Loop Protocol applications."""

    store: HumanLoopStore = field(default_factory=HumanLoopStore)
    adapter: AgentAdapter = field(default_factory=FakeAgentAdapter)
    event_bus: EventBus = field(default_factory=InMemoryEventBus)
    operations: HumanLoopOperations = field(init=False)
    _event_seq: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        self.operations = HumanLoopOperations(store=self.store, adapter=self.adapter)

    async def create_task(
        self,
        *,
        principal: str,
        goal: str,
        type: str = "",
        acceptance_criteria: tuple[str, ...] = (),
        inputs: tuple[InputRef, ...] = (),
        constraints: Constraints | None = None,
        review_policy: ReviewPolicy | None = None,
    ) -> Task:
        task = await self.operations.task_create(
            principal=principal,
            goal=goal,
            type=type,
            acceptance_criteria=acceptance_criteria,
            inputs=inputs,
            constraints=constraints,
            review_policy=review_policy,
        )
        await self._after_mutation(
            "task.created",
            task_id=task.id,
            subject=("task", task.id),
            payload={"principal": principal, "goal": goal},
        )
        return self.store.get_task(task.id)

    async def delegate(
        self,
        task_id: str,
        agent_id: str,
        *,
        capability: str = "",
        input: dict[str, Any] | None = None,
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> AgentRunHandle:
        await self.operations.task_assign(
            task_id,
            agent_id,
            capability=capability,
            input=input,
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        if self.operations.last_operation_replayed:
            run_id: str | None = self._adapter_result_run_id()
        else:
            run_id = self.store.run_of_task(task_id)
        if run_id is None:
            raise RuntimeError(f"adapter did not bind a run for task {task_id}")
        handle = AgentRunHandle(
            run_id=run_id,
            task_id=task_id,
            agent_id=agent_id,
            correlation_id=task_id,
            capability=capability,
        )
        await self._after_mutation_unless_replay(
            "task.delegated",
            task_id=task_id,
            subject=("run", run_id),
            payload={"agent_id": agent_id, "capability": capability},
        )
        return handle

    async def start(
        self,
        task_id: str,
        *,
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Task:
        task = await self.operations.task_start(
            task_id,
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        replayed = await self._after_mutation_unless_replay(
            "task.started",
            task_id=task.id,
            subject=("task", task.id),
            payload={"assignee": task.ownership.assignee},
        )
        return task if replayed else self.store.get_task(task.id)

    async def amend(
        self,
        task_id: str,
        *,
        by: str,
        text: str,
        intent: SteeringIntent = "clarify",
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
        promotion_provenance: dict | None = None,
    ) -> Task:
        task = await self.operations.task_amend(
            task_id,
            by=by,
            text=text,
            intent=intent,
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
            promotion_provenance=promotion_provenance,
        )
        payload: dict = {"by": by, "intent": intent}
        if promotion_provenance is not None:
            payload["promotion"] = promotion_provenance
        replayed = await self._after_mutation_unless_replay(
            "task.amended",
            task_id=task.id,
            subject=("task", task.id),
            payload=payload,
        )
        return task if replayed else self.store.get_task(task.id)

    async def interrupt(
        self,
        task_id: str,
        *,
        by: str,
        prompt: str,
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Checkpoint:
        checkpoint = await self.operations.task_interrupt(
            task_id,
            by=by,
            prompt=prompt,
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        replayed = await self._after_mutation_unless_replay(
            "task.interrupted",
            task_id=task_id,
            subject=("checkpoint", checkpoint.id),
            payload={"by": by},
        )
        return checkpoint if replayed else self.store.get_checkpoint(checkpoint.id)

    async def get_task(self, task_id: str) -> Task:
        return await self.operations.task_get(task_id)

    async def raise_checkpoint(
        self,
        *,
        task_id: str,
        kind: CheckpointKind,
        prompt: str,
        options: tuple[CheckpointOption, ...] = (),
        proposed_actions: tuple[ProposedAction, ...] = (),
        context: tuple[Evidence, ...] = (),
        raised_by: str,
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Checkpoint:
        checkpoint = await self.operations.checkpoint_raise(
            task_id=task_id,
            kind=kind,
            prompt=prompt,
            options=options,
            proposed_actions=proposed_actions,
            context=context,
            raised_by=raised_by,
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        replayed = await self._after_mutation_unless_replay(
            "checkpoint.raised",
            task_id=task_id,
            subject=("checkpoint", checkpoint.id),
            payload={"kind": kind, "raised_by": raised_by},
        )
        return checkpoint if replayed else self.store.get_checkpoint(checkpoint.id)

    async def resolve_checkpoint(
        self,
        checkpoint_id: str,
        *,
        by: str,
        action: CheckpointResolutionAction,
        choice: str | None = None,
        input: str | None = None,
        reassign_to: str | None = None,
        approved_actions: tuple[str, ...] = (),
        denied_actions: tuple[str, ...] = (),
        state_patch: dict[str, Any] | None = None,
        edited_artifact_ref: dict[str, str] | None = None,
        comment: str | None = None,
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Checkpoint:
        checkpoint = await self.operations.checkpoint_resolve(
            checkpoint_id,
            by=by,
            action=action,
            choice=choice,
            input=input,
            reassign_to=reassign_to,
            approved_actions=approved_actions,
            denied_actions=denied_actions,
            state_patch=state_patch,
            edited_artifact_ref=edited_artifact_ref,
            comment=comment,
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        replayed = await self._after_mutation_unless_replay(
            "checkpoint.resolved",
            task_id=checkpoint.task_id,
            subject=("checkpoint", checkpoint.id),
            payload={"by": by, "action": action, "choice": choice},
        )
        return checkpoint if replayed else self.store.get_checkpoint(checkpoint.id)

    async def commit_artifact(
        self,
        *,
        task_id: str,
        type: str,
        payload: ArtifactPayload,
        produced_by: str,
        parent_version: str | None = None,
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Artifact:
        artifact = await self.operations.artifact_commit(
            task_id=task_id,
            type=type,
            payload=payload,
            produced_by=produced_by,
            parent_version=parent_version,
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        replayed = await self._after_mutation_unless_replay(
            "artifact.committed",
            task_id=task_id,
            subject=("artifact", artifact.id),
            payload={"version": artifact.version, "produced_by": produced_by},
        )
        return artifact if replayed else self.store.get_artifact(artifact.id, artifact.version)

    async def submit_review(
        self,
        *,
        task_id: str,
        artifact_id: str,
        reviewer: str,
        verdict: ReviewVerdict,
        kind: ReviewKind = "deliverable",
        comments: tuple[ReviewComment, ...] = (),
        requested_changes: tuple[str, ...] = (),
        expected_task_revision: int | None = None,
        idempotency_key: str | None = None,
    ) -> Review:
        review = await self.operations.review_submit(
            task_id=task_id,
            artifact_id=artifact_id,
            reviewer=reviewer,
            verdict=verdict,
            kind=kind,
            comments=comments,
            requested_changes=requested_changes,
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        replayed = await self._after_mutation_unless_replay(
            "review.submitted",
            task_id=task_id,
            subject=("review", review.id),
            payload={"kind": kind, "verdict": verdict, "reviewer": reviewer},
        )
        return review if replayed else self.store.get_review(review.id)

    async def write_ledger(
        self,
        scope: str,
        key: str,
        value: Any,
        *,
        by: str,
    ) -> LedgerEntry:
        entry = await self.operations.ledger_write(scope, key, value, by=by)
        await self._after_mutation(
            "ledger.written",
            task_id=by,
            subject=("ledger", scope),
            payload={"key": key, "value": value},
        )
        return entry

    async def read_ledger(self, scope: str, key: str) -> Any | None:
        return await self.operations.ledger_read(scope, key)

    async def run_progress(self, run_id: str) -> RunProgressSnapshot | None:
        """Latest ephemeral progress projection for a run (appendix C §C.2),
        or None when the adapter has no progress source."""
        progress = getattr(self.adapter, "run_progress", None)
        if progress is None:
            return None
        return progress(run_id)

    async def pending_adapter_outbox(self) -> tuple[AdapterOutboxRecord, ...]:
        """Adapter outbox records still pending; retry them via the original
        idempotency-keyed operations (see HumanLoopOperations)."""
        return await self.operations.pending_adapter_outbox()

    async def expire_due_checkpoints(self, now: datetime | None = None) -> tuple[Checkpoint, ...]:
        """Expire pending checkpoints past expires_at (spec §7.2 sweep)."""
        return await self.operations.expire_due_checkpoints(now)

    async def project_harness_events(self, run_id: str) -> list[Any]:
        """Project existing harness events into HLP human-loop objects."""
        observe = getattr(self.adapter, "observe", None)
        if observe is None:
            raise RuntimeError("adapter does not expose harness events")

        peek_events = getattr(self.adapter, "peek_events", None)
        ack_events = getattr(self.adapter, "ack_events", None)
        reliable_delivery = callable(peek_events) and callable(ack_events)
        if callable(peek_events) and callable(ack_events):
            events = await peek_events(run_id)
        else:
            events = await observe(run_id)

        projected: list[Any] = []
        for delivery in events:
            cursor = delivery.cursor if reliable_delivery else ""
            event = delivery.event if reliable_delivery else delivery
            self._validate_harness_event_correlation(run_id, event)
            if reliable_delivery and not cursor:
                raise ProtocolError(
                    "INVALID_SPEC",
                    "peeked harness event must include cursor",
                )
            if event.kind in ("needs_approval", "needs_choice", "needs_input"):
                checkpoint_kind = {
                    "needs_approval": "approval",
                    "needs_choice": "choice",
                    "needs_input": "input",
                }[event.kind]
                projected.append(
                    await self.raise_checkpoint(
                        task_id=event.task_id,
                        kind=checkpoint_kind,  # type: ignore[arg-type]
                        prompt=event.prompt,
                        options=event.options,
                        context=event.context,
                        raised_by=event.agent_id,
                    )
                )
            elif event.kind == "artifact":
                projected.append(
                    await self.commit_artifact(
                        task_id=event.task_id,
                        type=event.artifact_type or "artifact",
                        payload=ArtifactPayload(
                            kind="ref",
                            uri=event.artifact_uri,
                            checksum=event.artifact_checksum,
                            size=event.artifact_size,
                        ),
                        produced_by=event.agent_id,
                    )
                )
            if reliable_delivery and callable(ack_events):
                await ack_events(run_id, through=cursor)
        return projected

    async def human_inbox(self, principal: str) -> list[HumanInboxItem]:
        """Return human-facing actions independent of the final UI/channel."""
        items: list[HumanInboxItem] = []
        for checkpoint in self.store.checkpoints.values():
            if checkpoint.state != "pending":
                continue
            task = self.store.get_task(checkpoint.task_id)
            if task.ownership.principal != principal:
                continue
            items.append(
                HumanInboxItem(
                    kind="checkpoint",
                    action="resolve_checkpoint",
                    task_id=task.id,
                    subject_id=checkpoint.id,
                    title=checkpoint.prompt,
                    principal=principal,
                    created_at=checkpoint.raised_at,
                )
            )

        for task in self.store.list_tasks():
            if task.ownership.principal != principal:
                continue
            if task.state not in ("review_ready", "under_review"):
                continue
            for artifact_id in task.artifacts:
                if self.store.reviews_of_artifact(artifact_id):
                    continue
                artifact = self.store.get_artifact(artifact_id)
                items.append(
                    HumanInboxItem(
                        kind="review",
                        action="submit_review",
                        task_id=task.id,
                        subject_id=artifact.id,
                        title=f"Review {artifact.type} {artifact.version}",
                        principal=principal,
                        created_at=(
                            artifact.provenance.produced_at
                            if artifact.provenance is not None
                            else task.created_at
                        ),
                    )
                )

        return sorted(items, key=lambda item: item.created_at)

    async def replay_audit(self, task_id: str) -> list:
        events = await self.operations.audit_replay(task_id)
        await self._publish_event(
            "audit.replayed",
            task_id=task_id,
            subject=("audit", task_id),
            payload={"count": len(events)},
        )
        return events

    def _validate_harness_event_correlation(self, run_id: str, event: Any) -> None:
        if event.run_id and event.run_id != run_id:
            raise ProtocolError(
                "CONFLICT",
                f"harness event run correlation mismatch: expected {run_id}, got {event.run_id}",
            )
        expected_task = self.store.task_of_run(run_id)
        if expected_task is not None and event.task_id != expected_task:
            raise ProtocolError(
                "CONFLICT",
                "harness event task correlation mismatch: "
                f"expected {expected_task}, got {event.task_id}",
            )

    async def _after_mutation(
        self,
        action: str,
        *,
        task_id: str,
        subject: tuple[str, str],
        payload: dict[str, Any] | None = None,
    ) -> None:
        flush = getattr(self.store, "flush", None)
        if flush is not None:
            flush()
        await self._publish_event(
            action,
            task_id=task_id,
            subject=subject,
            payload=payload,
        )

    async def _after_mutation_unless_replay(
        self,
        action: str,
        *,
        task_id: str,
        subject: tuple[str, str],
        payload: dict[str, Any] | None = None,
    ) -> bool:
        if self.operations.last_operation_replayed:
            self.operations.last_operation_replayed = False
            return True
        await self._after_mutation(
            action,
            task_id=task_id,
            subject=subject,
            payload=payload,
        )
        return False

    def _adapter_result_run_id(self) -> str:
        operation_id = self.operations.last_operation_id
        if operation_id is None:
            raise RuntimeError("replayed adapter operation id was not recorded")
        record = self.store.get_adapter_outbox_record(operation_id)
        if not isinstance(record.result, str):
            raise RuntimeError("replayed adapter operation did not record a run id result")
        return record.result

    async def _publish_event(
        self,
        action: str,
        *,
        task_id: str,
        subject: tuple[str, str],
        payload: dict[str, Any] | None = None,
    ) -> HLPEvent:
        self._event_seq += 1
        event = HLPEvent(
            seq=self._event_seq,
            action=action,
            task_id=task_id,
            subject=subject,
            payload=payload or {},
        )
        await self.event_bus.publish(event)
        return event
