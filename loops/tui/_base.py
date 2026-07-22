from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from loops.hlp import (
    AgentAdapterError,
    AutonomyTier,
    CheckpointResolutionAction,
    Constraints,
    HLPClient,
    HumanLoopStore,
    ProtocolError,
)

from .commands import CommandParseError, InputIntent, parse_user_input
from .render import (
    agent_reply_text,
    progress_summary_line,
    render_agent_reply,
    render_broadcast,
    render_error,
    render_human_loop,
    render_progress,
)
from .session import SessionStore, TranscriptEvent, TUISession


@dataclass(frozen=True)
class TUIResult:
    output: str
    should_exit: bool = False
    active_session_id: str = ""


class TUIUsageError(ValueError):
    pass


class TUISessionError(KeyError):
    pass


_SWITCHABLE_ADAPTERS = frozenset({"fake", "codex", "pi", "claude", "kimi"})


class _ControllerBase:
    def __init__(
        self,
        *,
        client: HLPClient,
        sessions: SessionStore,
        agent_id: str = "agent_tui",
        capability: str = "coding-agent",
        adapter_builder: Callable[[str, str, HumanLoopStore], HLPClient] | None = None,
    ) -> None:
        self.client = client
        self.sessions = sessions
        self.agent_id = agent_id
        self.capability = capability
        self._adapter_builder = adapter_builder

    async def handle(self, session_id: str, raw: str) -> TUIResult:
        try:
            quick = raw.strip().lower()
            if quick in {"y", "n"}:
                resolved = await self._quick_resolve(session_id, quick)
                if resolved is not None:
                    return resolved
            intent = parse_user_input(raw)
            if intent.kind == "prompt":
                return await self._handle_prompt(session_id, intent)
            if intent.kind == "shell":
                return self._record(session_id, "shell", f"captured shell input: {intent.text}")
            return await self._handle_command(session_id, intent)
        except (
            AgentAdapterError,
            CommandParseError,
            ProtocolError,
            TUIUsageError,
            TUISessionError,
        ) as exc:
            self._record_error_if_possible(session_id, str(exc))
            return TUIResult(render_error(exc))

    async def _quick_resolve(self, session_id: str, key: str) -> TUIResult | None:
        """Claude-Code-style quick keys: bare y/n resolves the pending checkpoint."""
        session = self._require_session(session_id)
        if not session.active_task_id:
            return None
        inbox = await self.client.human_inbox(session.principal)
        pending = next(
            (
                item
                for item in inbox
                if item.task_id == session.active_task_id and item.kind == "checkpoint"
            ),
            None,
        )
        if pending is None:
            return None
        action: CheckpointResolutionAction = "approve" if key == "y" else "reject"
        await self.client.resolve_checkpoint(
            pending.subject_id, by=session.principal, action=action
        )
        verdict = "approved" if action == "approve" else "rejected"
        text = f"checkpoint {verdict} ({pending.subject_id})"
        self._append(session_id, kind="task", text=text, ref=pending.subject_id)
        return await self._finish_with_harness_output(session_id, text)

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
            started = f"started task {task.id} run {run.run_id}"
            self._append(
                session_id,
                kind="task",
                text=started,
                ref=task.id,
            )
            return await self._finish_with_harness_output(session_id, started)

        # Follow-up free-text: HLP task.amend → adapter.steer. In chat prompt mode
        # that re-invokes the CLI with the new user message (not only steering log).
        task = await self.client.amend(
            session.active_task_id,
            by=session.principal,
            text=intent.text,
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

    async def _handle_command(self, session_id: str, intent: InputIntent) -> TUIResult:
        # SessionCmds overrides this and chains here via super().
        return await self._handle_hlp_command(session_id, intent)

    async def _handle_hlp_command(self, session_id: str, intent: InputIntent) -> TUIResult:
        # WorkCmds/HlpCmds/ControlCmds override this and chain here via super().
        raise TUIUsageError(f"command not wired yet: /{intent.name}")

    async def _switch_adapter(self, session_id: str, intent: InputIntent) -> TUIResult:
        """Runtime adapter switch: rebuild the client over the shared store and
        hand the active task off so its run lands on the new adapter."""
        target = _required_arg(intent, "/adapter requires a name")
        if target not in _SWITCHABLE_ADAPTERS:
            raise TUIUsageError(f"unsupported adapter: {target}")
        if self._adapter_builder is None:
            raise TUIUsageError("adapter switching is not configured for this host")
        session = self._require_session(session_id)
        old_adapter = session.adapter
        self.client = self._adapter_builder(target, session.model, self.client.store)
        updated = self.sessions.set_preference(session_id, field="adapter", value=target)

        note = ""
        if session.active_task_id:
            # Hand off to the TARGET adapter's agent identity. Handing off to the
            # current assignee is a silent no-op (no adapter call, no new run).
            task = await self.client.operations.ownership_transfer(
                session.active_task_id,
                to=f"agent_{target}",
                via="handoff",
                actor=session.principal,
            )
            new_run_id = self.client.store.run_of_task(task.id) or ""
            self.sessions.set_active(session_id, task_id=task.id, run_id=new_run_id)
            if old_adapter != target:
                # Cross-CLI: no shared session history exists, so brief the new
                # agent through the existing steer channel (steering_log + audit).
                await self.client.amend(
                    session.active_task_id,
                    by=session.principal,
                    text=(
                        f"HOST NOTE: the host switched harness adapter {old_adapter} -> "
                        f"{target}. There is no shared session history across CLIs, so "
                        "the briefing below is your ONLY source of prior context — treat "
                        "the user's earlier messages in it as authoritative facts and use "
                        "them when answering.\n\n" + _transcript_briefing(session)
                    ),
                    intent="constrain",
                )
                note = (
                    f"; active task handed off with a transcript briefing "
                    f"(no shared session history {old_adapter} -> {target})"
                )
            else:
                note = "; active task handed off via the native session"
        self._append(
            session_id,
            kind="task",
            text=f"adapter {old_adapter} → {target}{note}",
        )
        return TUIResult(f"adapter={updated.adapter}{note}")

    async def _broadcast(self, session_id: str, intent: InputIntent) -> TUIResult:
        """Fan out one prompt to every CLI harness and render a comparison.

        task.assign requires state=created, so each adapter gets its own task
        over the shared store (full per-harness audit trail). Serial v1: one
        slow harness must not lose the others' replies, so failures are caught
        per adapter and rendered inline.
        """
        text = _required_text(intent, "/broadcast requires a message")
        if self._adapter_builder is None:
            raise TUIUsageError("broadcast is not configured for this host")
        session = self._require_session(session_id)
        rows: list[dict[str, str]] = []
        for name in sorted(_SWITCHABLE_ADAPTERS - {"fake"}):
            try:
                client = self._adapter_builder(name, session.model, self.client.store)
                task = await client.create_task(
                    principal=session.principal,
                    goal=text,
                    type="tui-broadcast",
                    constraints=Constraints(autonomy=_autonomy(session.permission_mode)),
                )
                run = await client.delegate(
                    task.id,
                    f"agent_{name}",
                    capability=self.capability,
                    input={
                        "goal": text,
                        "permission_mode": session.permission_mode,
                        "model": session.model,
                    },
                )
                await client.start(task.id)
                payload = _process_payload(client, run.run_id)
                reply = agent_reply_text(payload) or f"(no reply; run {run.run_id})"
                rows.append({"adapter": name, "task": task.id, "run": run.run_id, "reply": reply})
            except (
                AgentAdapterError,
                ProtocolError,
                RuntimeError,
                TimeoutError,
                OSError,
            ) as exc:
                # Full diagnostics (exit_code, stderr tail, recovery hint) so a
                # failed harness is debuggable from the comparison block alone.
                rows.append({"adapter": name, "task": "", "run": "", "reply": render_error(exc)})
        block = render_broadcast(rows)
        self._append(session_id, kind="agent", text=block)
        return TUIResult(block)

    async def _finish_with_harness_output(
        self,
        session_id: str,
        primary: str,
    ) -> TUIResult:
        """Attach agent reply + projected human work to a primary status line."""
        parts = [primary]
        session = self._require_session(session_id)
        reply = render_agent_reply(self._adapter_process_payload(session.active_run_id))
        if reply:
            self._append(session_id, kind="agent", text=reply)
            parts.append(reply)
        human = await self._sync_harness_human_loop(session_id)
        if human:
            parts.append(human)
        progress_line = await self._progress_line(session_id)
        if progress_line:
            parts.append(progress_line)
        card = await self._approval_card(session_id)
        if card:
            parts.append(card)
        return TUIResult("\n".join(parts))

    async def _progress_line(self, session_id: str) -> str:
        """Progress panel when the adapter projects harness progress.

        Full checklist/agent tree when the snapshot carries structured items;
        one compact summary line otherwise.
        """
        session = self._require_session(session_id)
        if not session.active_run_id:
            return ""
        snapshot = await self.client.run_progress(session.active_run_id)
        if snapshot is None:
            return ""
        if snapshot.items or snapshot.agents:
            return render_progress(snapshot)
        return progress_summary_line(snapshot)

    async def _approval_card(self, session_id: str) -> str:
        """Inline approval card when the active task has a pending checkpoint.

        Pairs with the bare y/n quick keys: the card tells the human what is
        pending and which keys resolve it.
        """
        session = self._require_session(session_id)
        if not session.active_task_id:
            return ""
        inbox = await self.client.human_inbox(session.principal)
        pending = next(
            (
                item
                for item in inbox
                if item.task_id == session.active_task_id and item.kind == "checkpoint"
            ),
            None,
        )
        if pending is None:
            return ""
        card = (
            f"⚠ checkpoint pending: {pending.title}\n"
            "  [y] approve · [n] reject · /choose <option> · /input <text>"
        )
        self._append(session_id, kind="human", text=card, ref=pending.subject_id)
        return card

    def _adapter_process_payload(self, run_id: str) -> dict[str, Any] | None:
        return _process_payload(self.client, run_id)

    async def _sync_harness_human_loop(self, session_id: str) -> str:
        """Project harness human-facing events into HLP and summarize for the host."""
        session = self._require_session(session_id)
        if not session.active_run_id:
            return ""
        if not _adapter_can_project(self.client.adapter):
            return ""
        try:
            projected = await self.client.project_harness_events(session.active_run_id)
        except (RuntimeError, ProtocolError, AgentAdapterError):
            return ""
        inbox = await self.client.human_inbox(session.principal)
        active_inbox = [item for item in inbox if item.task_id == session.active_task_id]
        summary = render_human_loop(projected, active_inbox)
        if summary:
            self._append(session_id, kind="human", text=summary)
        return summary

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

    def _require_session(self, session_id: str) -> TUISession:
        try:
            return self.sessions.resume(session_id)
        except KeyError as exc:
            raise TUISessionError(f"unknown session: {session_id}") from exc

    def _require_active(self, session_id: str) -> TUISession:
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


def _autonomy(permission_mode: str) -> AutonomyTier:
    tiers: dict[str, AutonomyTier] = {
        "auto": "autonomous",
        "plan": "plan_then_implement",
        "confirm": "confirm_each_action",
        "read-only": "read_only",
    }
    return tiers.get(permission_mode, "autonomous")


def _transcript_briefing(session: TUISession, *, max_events: int = 8, max_chars: int = 80) -> str:
    """Compact recent transcript lines for cross-CLI handoff briefings."""
    events = session.transcript[-max_events:]
    if not events:
        return "(no prior conversation)"
    lines = []
    for event in events:
        text = event.text if len(event.text) <= max_chars else event.text[: max_chars - 1] + "…"
        lines.append(f"{event.kind}: {text}")
    return "\n".join(lines)


def _adapter_can_project(adapter: object) -> bool:
    return callable(getattr(adapter, "observe", None)) or callable(
        getattr(adapter, "peek_events", None)
    )


def _process_payload(client: HLPClient, run_id: str) -> dict[str, Any] | None:
    """Latest process payload a run produced (adapters that collect them)."""
    if not run_id:
        return None
    results = getattr(client.adapter, "process_results", None)
    if not isinstance(results, dict):
        return None
    payload = results.get(run_id)
    return payload if isinstance(payload, dict) else None


def _join_output(primary: str, secondary: str) -> str:
    if not secondary:
        return primary
    return f"{primary}\n{secondary}"
