from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loops.hlp import Constraints, HLPClient, ProtocolError, ReviewComment

from .commands import CommandParseError, InputIntent, parse_user_input
from .render import (
    render_audit,
    render_error,
    render_help,
    render_inbox,
    render_status,
    render_transcript,
)
from .session import SessionStore, TranscriptEvent


@dataclass(frozen=True)
class TUIResult:
    output: str
    should_exit: bool = False


class TUIUsageError(ValueError):
    pass


class TUISessionError(KeyError):
    pass


class TUIController:
    def __init__(
        self,
        *,
        client: HLPClient,
        sessions: SessionStore,
        agent_id: str = "agent_tui",
        capability: str = "coding-agent",
    ) -> None:
        self.client = client
        self.sessions = sessions
        self.agent_id = agent_id
        self.capability = capability

    async def handle(self, session_id: str, raw: str) -> TUIResult:
        try:
            intent = parse_user_input(raw)
            if intent.kind == "prompt":
                return await self._handle_prompt(session_id, intent)
            if intent.kind == "shell":
                return self._record(session_id, "shell", f"captured shell input: {intent.text}")
            return await self._handle_command(session_id, intent)
        except (CommandParseError, ProtocolError, TUIUsageError, TUISessionError) as exc:
            self._record_error_if_possible(session_id, str(exc))
            return TUIResult(render_error(exc))

    async def _handle_prompt(self, session_id: str, intent: InputIntent) -> TUIResult:
        session = self._require_session(session_id)
        self._append(session_id, kind="user", text=intent.text)

        if not session.active_task_id:
            task = await self.client.create_task(
                principal=session.principal,
                goal=intent.text,
                type="tui",
                constraints=Constraints(autonomy=_autonomy(session.permission_mode)),
            )
            run = await self.client.delegate(
                task.id,
                self.agent_id,
                capability=self.capability,
                input={
                    "goal": intent.text,
                    "mentions": intent.mentions,
                    "permission_mode": session.permission_mode,
                    "model": session.model,
                },
            )
            await self.client.start(task.id)
            self.sessions.set_active(session_id, task_id=task.id, run_id=run.run_id)
            self._append(
                session_id,
                kind="task",
                text=f"started task {task.id}",
                ref=task.id,
            )
            return TUIResult(f"started task {task.id} run {run.run_id}")

        task = await self.client.amend(
            session.active_task_id,
            by=session.principal,
            text=intent.text,
            intent="clarify",
        )
        self._append(
            session_id,
            kind="task",
            text=f"amended task {task.id}",
            ref=task.id,
        )
        return TUIResult(f"amended task {task.id}")

    async def _handle_command(self, session_id: str, intent: InputIntent) -> TUIResult:
        name = intent.name
        if name == "help":
            return TUIResult(render_help())
        if name == "clear":
            self._require_session(session_id)
            self.sessions.clear_visible(session_id)
            return TUIResult("cleared transcript")
        if name == "new":
            current = self._require_session(session_id)
            created = self.sessions.create(
                cwd=current.cwd,
                adapter=current.adapter,
                principal=current.principal,
            )
            return TUIResult(f"new session {created.id}")
        if name == "fork":
            self._require_session(session_id)
            forked = self.sessions.fork(session_id)
            return TUIResult(f"forked session {forked.id}")
        if name == "archive":
            self._require_session(session_id)
            self.sessions.archive(session_id)
            return TUIResult("archived session", should_exit=True)
        if name == "delete":
            self._require_session(session_id)
            self.sessions.delete(session_id)
            return TUIResult("deleted session", should_exit=True)
        if name == "resume":
            target = _required_arg(intent, "/resume requires a session id")
            resumed = self._require_session(target)
            return TUIResult(render_status(resumed))
        if name == "model":
            self._require_session(session_id)
            value = _required_arg(intent, "/model requires a model name")
            updated = self.sessions.set_preference(session_id, field="model", value=value)
            return TUIResult(f"model={updated.model}")
        if name == "theme":
            self._require_session(session_id)
            value = _required_arg(intent, "/theme requires a theme name")
            updated = self.sessions.set_preference(session_id, field="theme", value=value)
            return TUIResult(f"theme={updated.theme}")
        if name == "vim":
            self._require_session(session_id)
            updated = self.sessions.set_preference(
                session_id,
                field="composer_mode",
                value="vim",
            )
            return TUIResult(f"composer_mode={updated.composer_mode}")
        if name == "compact":
            session = self._require_session(session_id)
            self._append(
                session_id,
                kind="summary",
                text=render_transcript(session),
            )
            return TUIResult("compacted transcript summary recorded")
        if name == "mcp":
            return TUIResult("MCP is owned by the selected harness/tool runtime.")
        if name == "statusline":
            return await self._status(session_id)
        if name == "diff":
            session = self._require_session(session_id)
            return TUIResult(_diff_summary(Path(session.cwd)))
        return await self._handle_hlp_command(session_id, intent)

    async def _status(self, session_id: str) -> TUIResult:
        session = self._require_session(session_id)
        task_state = "none"
        if session.active_task_id:
            task_state = (await self.client.get_task(session.active_task_id)).state
        inbox = await self.client.human_inbox(session.principal)
        return TUIResult(
            render_status(session, task_state=task_state, inbox_count=len(inbox)),
        )

    async def _handle_hlp_command(self, session_id: str, intent: InputIntent) -> TUIResult:
        if intent.name == "permissions":
            return self._set_permissions(session_id, intent)
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
        if intent.name == "interrupt":
            prompt = _required_text(intent, "/interrupt requires a reason")
            session = self._require_active(session_id)
            checkpoint = await self.client.interrupt(
                session.active_task_id,
                by=session.principal,
                prompt=prompt,
            )
            return TUIResult(
                f"interrupted task {session.active_task_id} checkpoint {checkpoint.id}",
            )
        if intent.name == "review":
            return await self._review_current(session_id, intent)
        if intent.name == "audit":
            session = self._require_active(session_id)
            return TUIResult(
                render_audit(await self.client.replay_audit(session.active_task_id)),
            )
        raise TUIUsageError(f"command not wired yet: /{intent.name}")

    def _set_permissions(self, session_id: str, intent: InputIntent) -> TUIResult:
        value = _required_arg(
            intent,
            "/permissions requires suggest, auto, or read-only",
        )
        if value not in {"suggest", "auto", "read-only"}:
            raise TUIUsageError(f"unsupported permission mode: {value}")
        self._require_session(session_id)
        updated = self.sessions.set_preference(
            session_id,
            field="permission_mode",
            value=value,
        )
        return TUIResult(f"permission_mode={updated.permission_mode}")

    async def _resolve_checkpoint(
        self,
        session_id: str,
        *,
        action: str,
        choice: str | None = None,
        input_text: str | None = None,
        comment: str = "",
    ) -> TUIResult:
        session = self._require_session(session_id)
        inbox = await self.client.human_inbox(session.principal)
        checkpoint = next((item for item in inbox if item.kind == "checkpoint"), None)
        if checkpoint is None:
            raise TUIUsageError("no pending checkpoint")
        resolved = await self.client.resolve_checkpoint(
            checkpoint.subject_id,
            by=session.principal,
            action=action,  # type: ignore[arg-type]
            choice=choice,
            input=input_text,
            comment=comment or None,
        )
        label = {
            "approve": "approved",
            "reject": "rejected",
            "choose": "resolved",
            "provide": "resolved",
        }[action]
        return TUIResult(f"{label} checkpoint {resolved.id}")

    async def _review_current(self, session_id: str, intent: InputIntent) -> TUIResult:
        verdict_arg = _required_arg(
            intent,
            "/review requires approved, changes_requested, or commented",
        )
        comment_text = " ".join(intent.args[1:]).strip()
        comments = (
            (ReviewComment(anchor="artifact", body=comment_text),)
            if comment_text
            else ()
        )

        if verdict_arg == "approved":
            verdict = "approved"
            requested_changes: tuple[str, ...] = ()
        elif verdict_arg == "changes_requested":
            if not comment_text:
                raise TUIUsageError("/review changes_requested requires a comment")
            verdict = "changes_requested"
            requested_changes = (comment_text,)
        elif verdict_arg == "commented":
            if not comment_text:
                raise TUIUsageError("/review commented requires a comment")
            verdict = "approved"
            requested_changes = ()
        else:
            raise TUIUsageError(f"unsupported review verdict: {verdict_arg}")

        session = self._require_session(session_id)
        inbox = await self.client.human_inbox(session.principal)
        review_item = next((item for item in inbox if item.kind == "review"), None)
        if review_item is None:
            raise TUIUsageError("no review-ready artifact")
        review = await self.client.submit_review(
            task_id=review_item.task_id,
            artifact_id=review_item.subject_id,
            reviewer=session.principal,
            verdict=verdict,  # type: ignore[arg-type]
            comments=comments,
            requested_changes=requested_changes,
        )
        return TUIResult(f"reviewed artifact {review.artifact_id} verdict={review.verdict}")

    def _record(self, session_id: str, kind: str, text: str) -> TUIResult:
        self._append(session_id, kind=kind, text=text)
        return TUIResult(text)

    def _record_error_if_possible(self, session_id: str, message: str) -> None:
        try:
            self._append(session_id, kind="error", text=message)
        except TUISessionError:
            pass

    def _append(self, session_id: str, kind: str, text: str, ref: str = "") -> None:
        try:
            self.sessions.append(session_id, TranscriptEvent(kind=kind, text=text, ref=ref))
        except KeyError as exc:
            raise TUISessionError(f"unknown session: {session_id}") from exc

    def _require_session(self, session_id: str):
        try:
            return self.sessions.resume(session_id)
        except KeyError as exc:
            raise TUISessionError(f"unknown session: {session_id}") from exc

    def _require_active(self, session_id: str):
        session = self._require_session(session_id)
        if not session.active_task_id:
            raise TUIUsageError("no active task")
        return session


def _required_arg(intent: InputIntent, message: str) -> str:
    if not intent.args:
        raise TUIUsageError(message)
    return intent.args[0]


def _required_text(intent: InputIntent, message: str) -> str:
    value = _joined_args(intent)
    if not value:
        raise TUIUsageError(message)
    return value


def _joined_args(intent: InputIntent) -> str:
    return " ".join(intent.args).strip()


def _autonomy(permission_mode: str) -> str:
    return {
        "auto": "autonomous",
        "suggest": "confirm_each_action",
        "plan": "plan_then_implement",
        "confirm": "confirm_each_action",
        "read-only": "read_only",
    }.get(permission_mode, "autonomous")


def _diff_summary(cwd: Path) -> str:
    git_dir = Path(cwd) / ".git"
    if not git_dir.exists():
        return "diff unavailable: not a git workspace"
    return "diff available through harness or injected provider"
