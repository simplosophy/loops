from __future__ import annotations

from loops.hlp import CheckpointResolutionAction, ReviewComment, ReviewVerdict

from ._base import (
    TUIResult,
    TUIUsageError,
    _ControllerBase,
    _joined_args,
    _required_arg,
    _required_text,
)
from .commands import InputIntent
from .render import render_audit, render_inbox

_CHECKPOINT_RESULT_LABELS: dict[CheckpointResolutionAction, str] = {
    "approve": "approved",
    "reject": "rejected",
    "choose": "resolved",
    "provide": "resolved",
    "reassign": "resolved",
}
_REVIEW_VERDICTS: dict[str, ReviewVerdict] = {
    "approved": "approved",
    "approve": "approved",
    "changes": "changes_requested",
    "changes_requested": "changes_requested",
    "rejected": "rejected",
    "reject": "rejected",
}


class HlpCmds(_ControllerBase):
    async def _handle_hlp_command(self, session_id: str, intent: InputIntent) -> TUIResult:
        if intent.name == "inbox":
            session = self._require_session(session_id)
            return TUIResult(render_inbox(await self.client.human_inbox(session.principal)))
        if intent.name == "approve":
            return await self._resolve_checkpoint(
                session_id,
                action="approve",
                comment=_joined_args(intent),
            )
        if intent.name == "reject":
            return await self._resolve_checkpoint(
                session_id,
                action="reject",
                comment=_joined_args(intent),
            )
        if intent.name == "choose":
            return await self._resolve_checkpoint(
                session_id,
                action="choose",
                choice=_required_arg(intent, "/choose requires an option id"),
            )
        if intent.name == "input":
            input_text = _required_text(intent, "/input requires text")
            return await self._resolve_checkpoint(
                session_id,
                action="provide",
                input_text=input_text,
            )
        if intent.name == "amend":
            text = _required_text(intent, "/amend requires text")
            session = self._require_active(session_id)
            task = await self.client.amend(
                session.active_task_id,
                by=session.principal,
                text=text,
                intent="clarify",
            )
            amended = f"amended task {task.id}"
            self._append(
                session_id,
                kind="task",
                text=amended,
                ref=task.id,
            )
            return await self._finish_with_harness_output(session_id, amended)
        if intent.name == "review":
            return await self._review_current(session_id, intent)
        if intent.name == "audit":
            session = self._require_active(session_id)
            return TUIResult(
                render_audit(await self.client.replay_audit(session.active_task_id)),
            )
        return await super()._handle_hlp_command(session_id, intent)

    async def _resolve_checkpoint(
        self,
        session_id: str,
        *,
        action: CheckpointResolutionAction,
        choice: str | None = None,
        input_text: str | None = None,
        comment: str = "",
    ) -> TUIResult:
        session = self._require_active(session_id)
        inbox = await self.client.human_inbox(session.principal)
        checkpoint = next(
            (
                item
                for item in inbox
                if item.kind == "checkpoint" and item.task_id == session.active_task_id
            ),
            None,
        )
        if checkpoint is None:
            raise TUIUsageError("no pending checkpoint for active task")
        resolved = await self.client.resolve_checkpoint(
            checkpoint.subject_id,
            by=session.principal,
            action=action,
            choice=choice,
            input=input_text,
            comment=comment or None,
        )
        label = _CHECKPOINT_RESULT_LABELS[action]
        resolved_line = f"{label} checkpoint {resolved.id}"
        self._append(
            session_id,
            kind="checkpoint",
            text=resolved_line,
            ref=resolved.id,
        )
        return await self._finish_with_harness_output(session_id, resolved_line)

    async def _review_current(self, session_id: str, intent: InputIntent) -> TUIResult:
        session = self._require_active(session_id)
        verdict_arg = _required_arg(
            intent,
            "/review requires approved, changes_requested, or rejected",
        )
        if verdict_arg not in _REVIEW_VERDICTS:
            raise TUIUsageError(f"unsupported review verdict: {verdict_arg}")

        verdict = _REVIEW_VERDICTS[verdict_arg]
        comment_text = " ".join(intent.args[1:]).strip()
        comments = (ReviewComment(anchor="artifact", body=comment_text),) if comment_text else ()

        requested_changes: tuple[str, ...]
        if verdict == "changes_requested":
            if not comment_text:
                raise TUIUsageError("/review changes_requested requires a comment")
            requested_changes = (comment_text,)
        else:
            requested_changes = ()

        inbox = await self.client.human_inbox(session.principal)
        review_item = next(
            (
                item
                for item in inbox
                if item.kind == "review" and item.task_id == session.active_task_id
            ),
            None,
        )
        if review_item is None:
            raise TUIUsageError("no review-ready artifact for active task")
        review = await self.client.submit_review(
            task_id=review_item.task_id,
            artifact_id=review_item.subject_id,
            reviewer=session.principal,
            verdict=verdict,
            comments=comments,
            requested_changes=requested_changes,
        )
        line = f"reviewed artifact {review.artifact_id} verdict={review.verdict}"
        self._append(session_id, kind="review", text=line, ref=review.id)
        return TUIResult(line)
