from __future__ import annotations

from ..objects import ArtifactPayload, Task
from .artifact import ArtifactOps
from .audit import AuditOps
from .checkpoint import CheckpointOps
from .ledger import LedgerOps
from .ownership import OwnershipOps
from .review import ReviewOps
from .task import TaskOps


class DemoOps(
    TaskOps,
    CheckpointOps,
    OwnershipOps,
    ReviewOps,
    ArtifactOps,
    LedgerOps,
    AuditOps,
):
    # ────────────────── Test/demo helpers (non-spec operations) ──────────────────

    async def _seed_to_in_progress(self) -> Task:
        """Quickly build an in_progress task, for tests."""
        task = await self.task_create(principal="alice", goal="test goal")
        await self.task_assign(task.id, "agent_test")
        await self.task_start(task.id)
        return task

    async def _seed_to_review_ready(self) -> Task:
        """Quickly build a review_ready task (artifact v1 delivered)."""
        task = await self._seed_to_in_progress()
        await self.artifact_commit(
            task_id=task.id,
            type="report",
            payload=ArtifactPayload(kind="inline", uri="mem://v1", checksum="sha256:1"),
            produced_by="agent",
        )
        return task

    async def _seed_full_lifecycle(self) -> Task:
        """Build a task that has gone through the full closed loop (for audit/version tests)."""
        task = await self._seed_to_review_ready()
        await self.review_submit(
            task_id=task.id,
            artifact_id=task.artifacts[0],
            reviewer="bob",
            verdict="changes_requested",
            requested_changes=("fix it",),
        )
        await self.artifact_commit(
            task_id=task.id,
            type="report",
            payload=ArtifactPayload(kind="inline", uri="mem://v2", checksum="sha256:2"),
            produced_by="agent",
        )
        await self.review_submit(
            task_id=task.id,
            artifact_id=task.artifacts[1],
            reviewer="bob",
            verdict="approved",
        )
        return task
