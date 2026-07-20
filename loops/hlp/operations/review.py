from __future__ import annotations

from .._ids import gen_review_id
from ..objects import Review, ReviewComment
from ..state_machine import check_transition
from ..types import ProtocolError, ReviewKind, ReviewVerdict
from ._base import HumanLoopOperationsBase, _now, _TaskOperationReplay


class ReviewOps(HumanLoopOperationsBase):
    # ────────────────── Review (spec §4.1) ──────────────────

    async def review_submit(
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
        """review.submit (spec §4.1, §3.6).

        - review_ready/under_review → accepted (approved)
        - review_ready/under_review → in_progress (changes_requested, rework)
        - review_ready/under_review → rejected (rejected)
        """
        task = self.store._get_task_for_update(task_id)
        idempotency = self._begin_task_operation(
            task,
            "review.submit",
            {
                "artifact_id": artifact_id,
                "reviewer": reviewer,
                "verdict": verdict,
                "kind": kind,
                "comments": comments,
                "requested_changes": requested_changes,
            },
            expected_task_revision=expected_task_revision,
            idempotency_key=idempotency_key,
        )
        if isinstance(idempotency, _TaskOperationReplay):
            return idempotency.result
        if task.state not in ("review_ready", "under_review"):
            raise ProtocolError(
                "PRECONDITION_FAILED",
                f"cannot review task in state {task.state!r}",
            )
        if verdict == "changes_requested" and not requested_changes:
            raise ProtocolError(
                "INVALID_SPEC",
                "changes_requested verdict requires requested_changes",
            )
        self._require_human_actor(reviewer, "reviewer")
        if artifact_id not in task.artifacts:
            raise ProtocolError(
                "PRECONDITION_FAILED",
                f"artifact {artifact_id} is not an output of task {task_id}",
            )
        # ensure the artifact exists
        self.store.get_artifact(artifact_id)

        review = Review(
            id=gen_review_id(),
            task_id=task_id,
            artifact_id=artifact_id,
            reviewer=reviewer,
            kind=kind,
            verdict=verdict,
            comments=comments,
            requested_changes=requested_changes,
        ).seal()
        self.store.put_review(review)

        # state coordination (spec §3.6): first review_ready→under_review, then transition by verdict
        if task.state == "review_ready":
            check_transition(task.state, "under_review")
            task.state = "under_review"

        if kind == "plan" and verdict in ("approved", "changes_requested"):
            check_transition(task.state, "in_progress")
            task.state = "in_progress"
            target_agent = self._last_assignee_before(
                task,
                to=task.ownership.principal,
                via="handoff",
            )
            if target_agent is not None and task.ownership.assignee != target_agent:
                task.ownership = task.ownership.transfer(
                    target_agent,
                    via="approve" if verdict == "approved" else "reject",
                )
        elif verdict == "approved":
            check_transition(task.state, "accepted")
            task.state = "accepted"
            check_transition(task.state, "completed")
            task.state = "completed"
        elif verdict == "changes_requested":
            check_transition(task.state, "in_progress")
            task.state = "in_progress"
            target_agent = self._last_assignee_before(
                task,
                to=task.ownership.principal,
                via="handoff",
            )
            if target_agent is not None and task.ownership.assignee != target_agent:
                task.ownership = task.ownership.transfer(target_agent, via="reject")
        else:  # rejected
            check_transition(task.state, "rejected")
            task.state = "rejected"

        self._audit(
            actor=reviewer,
            action="review.submitted",
            subject=("review", review.id),
            task_id=task_id,
            after={"kind": kind, "verdict": verdict},
        )
        if kind == "deliverable" and verdict == "approved":
            self._audit(
                actor="system",
                action="task.completed",
                subject=("task", task.id),
                task_id=task_id,
                after={"review_id": review.id},
            )
        self._commit_task_operation(task, idempotency, review)
        return review

    async def review_comment(
        self,
        review_id: str,
        comment: ReviewComment,
        *,
        by: str,
    ) -> Review:
        """review.comment (spec §4.1). Append a comment.

        Note: spec §2.3 says a Review is immutable once submitted — "appending
        a comment" here means producing a new record, not modifying the original
        review. The reference implementation stores a new Review.
        """
        original = self.store._get_review_for_update(review_id)
        new_review = Review(
            id=gen_review_id(),
            task_id=original.task_id,
            artifact_id=original.artifact_id,
            reviewer=by,
            kind=original.kind,
            verdict=original.verdict,
            comments=(comment,),
            at=_now(),
        ).seal()
        self.store.put_review(new_review)
        self._audit(
            actor=by,
            action="review.commented",
            subject=("review", new_review.id),
            task_id=original.task_id,
        )
        return new_review
