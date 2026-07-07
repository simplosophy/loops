from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from loops.hlp import Constraints, HLPClient, ProtocolError

from .commands import CommandParseError, InputIntent, parse_user_input
from .render import (
    render_error,
    render_help,
    render_status,
    render_transcript,
)
from .session import SessionStore, TranscriptEvent


@dataclass(frozen=True)
class TUIResult:
    output: str
    should_exit: bool = False


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
        except (CommandParseError, ProtocolError, KeyError, ValueError) as exc:
            self._record_error_if_possible(session_id, str(exc))
            return TUIResult(render_error(exc))

    async def _handle_prompt(self, session_id: str, intent: InputIntent) -> TUIResult:
        session = self.sessions.resume(session_id)
        self.sessions.append(session_id, TranscriptEvent(kind="user", text=intent.text))

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
            self.sessions.append(
                session_id,
                TranscriptEvent(kind="task", text=f"started task {task.id}", ref=task.id),
            )
            return TUIResult(f"started task {task.id} run {run.run_id}")

        task = await self.client.amend(
            session.active_task_id,
            by=session.principal,
            text=intent.text,
            intent="clarify",
        )
        self.sessions.append(
            session_id,
            TranscriptEvent(kind="task", text=f"amended task {task.id}", ref=task.id),
        )
        return TUIResult(f"amended task {task.id}")

    async def _handle_command(self, session_id: str, intent: InputIntent) -> TUIResult:
        name = intent.name
        if name == "help":
            return TUIResult(render_help())
        if name == "clear":
            self.sessions.clear_visible(session_id)
            return TUIResult("cleared transcript")
        if name == "new":
            current = self.sessions.resume(session_id)
            created = self.sessions.create(
                cwd=current.cwd,
                adapter=current.adapter,
                principal=current.principal,
            )
            return TUIResult(f"new session {created.id}")
        if name == "fork":
            forked = self.sessions.fork(session_id)
            return TUIResult(f"forked session {forked.id}")
        if name == "archive":
            self.sessions.archive(session_id)
            return TUIResult("archived session", should_exit=True)
        if name == "delete":
            self.sessions.delete(session_id)
            return TUIResult("deleted session", should_exit=True)
        if name == "resume":
            target = _required_arg(intent, "/resume requires a session id")
            resumed = self.sessions.resume(target)
            return TUIResult(render_status(resumed))
        if name == "model":
            value = _required_arg(intent, "/model requires a model name")
            updated = self.sessions.set_preference(session_id, field="model", value=value)
            return TUIResult(f"model={updated.model}")
        if name == "theme":
            value = _required_arg(intent, "/theme requires a theme name")
            updated = self.sessions.set_preference(session_id, field="theme", value=value)
            return TUIResult(f"theme={updated.theme}")
        if name == "vim":
            updated = self.sessions.set_preference(
                session_id,
                field="composer_mode",
                value="vim",
            )
            return TUIResult(f"composer_mode={updated.composer_mode}")
        if name == "compact":
            session = self.sessions.resume(session_id)
            self.sessions.append(
                session_id,
                TranscriptEvent(
                    kind="summary",
                    text=render_transcript(session),
                ),
            )
            return TUIResult("compacted transcript summary recorded")
        if name == "mcp":
            return TUIResult("MCP is owned by the selected harness/tool runtime.")
        if name == "statusline":
            return await self._status(session_id)
        if name == "diff":
            session = self.sessions.resume(session_id)
            return TUIResult(_diff_summary(Path(session.cwd)))
        return await self._handle_hlp_command(session_id, intent)

    async def _status(self, session_id: str) -> TUIResult:
        session = self.sessions.resume(session_id)
        task_state = "none"
        if session.active_task_id:
            task_state = (await self.client.get_task(session.active_task_id)).state
        inbox = await self.client.human_inbox(session.principal)
        return TUIResult(
            render_status(session, task_state=task_state, inbox_count=len(inbox)),
        )

    async def _handle_hlp_command(self, session_id: str, intent: InputIntent) -> TUIResult:
        raise ValueError(f"command not wired yet: /{intent.name}")

    def _record(self, session_id: str, kind: str, text: str) -> TUIResult:
        self.sessions.append(session_id, TranscriptEvent(kind=kind, text=text))
        return TUIResult(text)

    def _record_error_if_possible(self, session_id: str, message: str) -> None:
        try:
            self.sessions.append(session_id, TranscriptEvent(kind="error", text=message))
        except KeyError:
            pass


def _required_arg(intent: InputIntent, message: str) -> str:
    if not intent.args:
        raise ValueError(message)
    return intent.args[0]


def _autonomy(permission_mode: str) -> str:
    return {
        "auto": "autonomous",
        "plan": "plan_then_implement",
        "confirm": "confirm_each_action",
        "read-only": "read_only",
    }.get(permission_mode, "autonomous")


def _diff_summary(cwd: Path) -> str:
    git_dir = Path(cwd) / ".git"
    if not git_dir.exists():
        return "diff unavailable: not a git workspace"
    return "diff available through harness or injected provider"
