from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .adapters import AgentAdapter, AgentRunHandle, FakeAgentAdapter, HarnessAdapter
from .events import EventBus, HLPEvent, InMemoryEventBus
from .objects import (
    Artifact,
    ArtifactPayload,
    Checkpoint,
    CheckpointOption,
    Evidence,
    HumanInboxItem,
    InputRef,
    LedgerEntry,
    Review,
    ReviewComment,
    Task,
)
from .operations import HumanLoopOperations
from .store import HumanLoopStore
from .types import CheckpointKind, CheckpointResolutionAction, ReviewVerdict


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
    ) -> Task:
        task = await self.operations.task_create(
            principal=principal,
            goal=goal,
            type=type,
            acceptance_criteria=acceptance_criteria,
            inputs=inputs,
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
    ) -> AgentRunHandle:
        await self.operations.task_assign(
            task_id,
            agent_id,
            capability=capability,
            input=input,
        )
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
        await self._after_mutation(
            "task.delegated",
            task_id=task_id,
            subject=("run", run_id),
            payload={"agent_id": agent_id, "capability": capability},
        )
        return handle

    async def start(self, task_id: str) -> Task:
        task = await self.operations.task_start(task_id)
        await self._after_mutation(
            "task.started",
            task_id=task.id,
            subject=("task", task.id),
            payload={"assignee": task.ownership.assignee},
        )
        return self.store.get_task(task.id)

    async def get_task(self, task_id: str) -> Task:
        return await self.operations.task_get(task_id)

    async def raise_checkpoint(
        self,
        *,
        task_id: str,
        kind: CheckpointKind,
        prompt: str,
        options: tuple[CheckpointOption, ...] = (),
        context: tuple[Evidence, ...] = (),
        raised_by: str,
    ) -> Checkpoint:
        checkpoint = await self.operations.checkpoint_raise(
            task_id=task_id,
            kind=kind,
            prompt=prompt,
            options=options,
            context=context,
            raised_by=raised_by,
        )
        await self._after_mutation(
            "checkpoint.raised",
            task_id=task_id,
            subject=("checkpoint", checkpoint.id),
            payload={"kind": kind, "raised_by": raised_by},
        )
        return self.store.get_checkpoint(checkpoint.id)

    async def resolve_checkpoint(
        self,
        checkpoint_id: str,
        *,
        by: str,
        action: CheckpointResolutionAction,
        choice: str | None = None,
        input: str | None = None,
        reassign_to: str | None = None,
        comment: str | None = None,
    ) -> Checkpoint:
        checkpoint = await self.operations.checkpoint_resolve(
            checkpoint_id,
            by=by,
            action=action,
            choice=choice,
            input=input,
            reassign_to=reassign_to,
            comment=comment,
        )
        await self._after_mutation(
            "checkpoint.resolved",
            task_id=checkpoint.task_id,
            subject=("checkpoint", checkpoint.id),
            payload={"by": by, "action": action, "choice": choice},
        )
        return self.store.get_checkpoint(checkpoint.id)

    async def commit_artifact(
        self,
        *,
        task_id: str,
        type: str,
        payload: ArtifactPayload,
        produced_by: str,
        parent_version: str | None = None,
    ) -> Artifact:
        artifact = await self.operations.artifact_commit(
            task_id=task_id,
            type=type,
            payload=payload,
            produced_by=produced_by,
            parent_version=parent_version,
        )
        await self._after_mutation(
            "artifact.committed",
            task_id=task_id,
            subject=("artifact", artifact.id),
            payload={"version": artifact.version, "produced_by": produced_by},
        )
        return self.store.get_artifact(artifact.id, artifact.version)

    async def submit_review(
        self,
        *,
        task_id: str,
        artifact_id: str,
        reviewer: str,
        verdict: ReviewVerdict,
        comments: tuple[ReviewComment, ...] = (),
        requested_changes: tuple[str, ...] = (),
    ) -> Review:
        review = await self.operations.review_submit(
            task_id=task_id,
            artifact_id=artifact_id,
            reviewer=reviewer,
            verdict=verdict,
            comments=comments,
            requested_changes=requested_changes,
        )
        await self._after_mutation(
            "review.submitted",
            task_id=task_id,
            subject=("review", review.id),
            payload={"verdict": verdict, "reviewer": reviewer},
        )
        return self.store.get_review(review.id)

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

    async def project_harness_events(self, run_id: str) -> list[Any]:
        """Project existing harness events into HLP human-loop objects."""
        if not isinstance(self.adapter, HarnessAdapter):
            raise RuntimeError("adapter does not expose harness events")

        projected: list[Any] = []
        for event in await self.adapter.observe(run_id):
            if event.kind in ("needs_approval", "needs_choice", "needs_input"):
                checkpoint_kind = {
                    "needs_approval": "approval",
                    "needs_choice": "choice",
                    "needs_input": "input",
                }[event.kind]
                projected.append(await self.raise_checkpoint(
                    task_id=event.task_id,
                    kind=checkpoint_kind,  # type: ignore[arg-type]
                    prompt=event.prompt,
                    options=event.options,  # type: ignore[arg-type]
                    context=event.context,  # type: ignore[arg-type]
                    raised_by=event.agent_id,
                ))
            elif event.kind == "artifact":
                projected.append(await self.commit_artifact(
                    task_id=event.task_id,
                    type=event.artifact_type or "artifact",
                    payload=ArtifactPayload(
                        kind="ref",
                        uri=event.artifact_uri,
                        checksum=event.artifact_checksum,
                        size=event.artifact_size,
                    ),
                    produced_by=event.agent_id,
                ))
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
            items.append(HumanInboxItem(
                kind="checkpoint",
                action="resolve_checkpoint",
                task_id=task.id,
                subject_id=checkpoint.id,
                title=checkpoint.prompt,
                principal=principal,
                created_at=checkpoint.raised_at,
            ))

        for task in self.store.list_tasks():
            if task.ownership.principal != principal:
                continue
            if task.state not in ("review_ready", "under_review"):
                continue
            for artifact_id in task.artifacts:
                if self.store.reviews_of_artifact(artifact_id):
                    continue
                artifact = self.store.get_artifact(artifact_id)
                items.append(HumanInboxItem(
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
                ))

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
