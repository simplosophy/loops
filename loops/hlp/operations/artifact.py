from __future__ import annotations

from typing import Literal

from ..objects import Artifact, ArtifactPayload, ArtifactProvenance, ArtifactRef
from ..state_machine import check_transition
from ..types import ProtocolError
from ._base import HumanLoopOperationsBase, _TaskOperationReplay


class ArtifactOps(HumanLoopOperationsBase):
    # ────────────────── Artifact (spec §4.1) ──────────────────

    async def artifact_commit(
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
        """artifact.commit (spec §4.1, §3.7).

        in_progress→review_ready (first delivery) or
        under_review→in_progress is not handled here (governed by the review state machine).
        Reference: committing in the in_progress state triggers review_ready.
        """
        task = self.store._get_task_for_update(task_id)
        idempotency = self._begin_task_operation(
            task,
            "artifact.commit",
            {
                "type": type,
                "payload": payload,
                "produced_by": produced_by,
                "parent_version": parent_version,
            },
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        if isinstance(idempotency, _TaskOperationReplay):
            return idempotency.result
        # spec §4.3: artifact.commit requires in_progress or the rework state
        if task.state not in ("in_progress",):
            raise ProtocolError(
                "PRECONDITION_FAILED",
                f"cannot commit artifact in task state {task.state!r}",
            )

        # version number: number of artifacts produced by this task + 1 (spec §3.7)
        version = f"v{len(task.artifacts) + 1}"

        art = Artifact(
            type=type,
            provenance=ArtifactProvenance(produced_by=task_id),
            version=version,
            parent_version=parent_version,
            payload=payload,
        ).seal()
        self.store.put_artifact(art)
        task.artifacts.append(art.id)

        # first delivery triggers review_ready (spec §3.3)
        check_transition(task.state, "review_ready")
        task.state = "review_ready"
        if task.ownership.assignee != task.ownership.principal:
            task.ownership = task.ownership.transfer(task.ownership.principal, via="handoff")

        self._audit(
            actor=produced_by,
            action="artifact.committed",
            subject=("artifact", art.id),
            task_id=task_id,
            after={"version": version},
        )
        self._commit_task_operation(task, idempotency, art)
        return art

    async def artifact_get(self, art_id: str, version: str | None = None) -> Artifact:
        """artifact.get (spec §4.1)."""
        return self.store.get_artifact(art_id, version)

    async def artifact_reference(
        self,
        art_id: str,
        *,
        by_task: str,
        as_: Literal["input", "output"] = "input",
    ) -> Artifact:
        """artifact.reference (spec §4.1). Referenced by a Task as an input."""
        art = self.store.get_artifact(art_id)
        self.store.add_artifact_reference(art.id, ArtifactRef(task_id=by_task, as_=as_))
        self._audit(
            actor=by_task,
            action="artifact.referenced",
            subject=("artifact", art.id),
            task_id=by_task,
        )
        return art
