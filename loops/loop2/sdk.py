from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .adapters import AgentAdapter, AgentRunHandle, FakeAgentAdapter
from .events import InMemoryEventBus
from .objects import (
    Artifact,
    ArtifactPayload,
    Checkpoint,
    CheckpointOption,
    Evidence,
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
    event_bus: InMemoryEventBus = field(default_factory=InMemoryEventBus)
    operations: HumanLoopOperations = field(init=False)

    def __post_init__(self) -> None:
        self.operations = HumanLoopOperations(store=self.store, aap=self.adapter)

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
        return task

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
        return task

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
        return checkpoint

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
        return checkpoint

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
        return artifact

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
        return review

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

    async def replay_audit(self, task_id: str) -> list:
        events = await self.operations.audit_replay(task_id)
        await self.event_bus.emit(
            action="audit.replayed",
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
        await self.event_bus.emit(
            action=action,
            task_id=task_id,
            subject=subject,
            payload=payload,
        )
