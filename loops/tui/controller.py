from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loops.hlp import (
    AgentAdapterError,
    AutonomyTier,
    CheckpointResolutionAction,
    Constraints,
    ControlSignal,
    HLPClient,
    HumanLoopStore,
    InteractionRef,
    ProtocolError,
    ReviewComment,
    ReviewVerdict,
    SteeringIntent,
    merge_soft_control_signals,
)

from .commands import CommandParseError, InputIntent, parse_user_input
from .render import (
    render_agent_reply,
    render_artifact_detail,
    render_artifacts,
    render_audit,
    render_error,
    render_help,
    render_human_loop,
    render_inbox,
    render_soft_buffer,
    render_status,
    render_tasks,
    render_transcript,
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


_PERMISSION_MODES = frozenset({"auto", "plan", "confirm", "read-only"})
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
_SWITCHABLE_ADAPTERS = frozenset({"fake", "codex", "pi", "claude", "kimi"})


class TUIController:
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
            return TUIResult(f"new session {created.id}", active_session_id=created.id)
        if name == "fork":
            self._require_session(session_id)
            forked = self.sessions.fork(session_id)
            return TUIResult(f"forked session {forked.id}", active_session_id=forked.id)
        if name == "archive":
            self._require_session(session_id)
            self.sessions.archive(session_id)
            return TUIResult("archived session", should_exit=True)
        if name == "delete":
            self._require_session(session_id)
            if not intent.args or intent.args[0] != "confirm":
                raise TUIUsageError("/delete requires confirmation: /delete confirm")
            self.sessions.delete(session_id)
            return TUIResult("deleted session", should_exit=True)
        if name == "resume":
            target = _required_arg(intent, "/resume requires a session id")
            resumed = self._require_session(target)
            return TUIResult(render_status(resumed), active_session_id=resumed.id)
        if name == "model":
            session = self._require_session(session_id)
            value = _required_arg(intent, "/model requires a model name")
            updated = self.sessions.set_preference(session_id, field="model", value=value)
            rebuilt = ""
            if self._adapter_builder is not None and session.adapter != "fake":
                self.client = self._adapter_builder(
                    session.adapter,
                    value,
                    self.client.store,
                )
                rebuilt = " (client rebuilt; next prompts use it)"
            return TUIResult(f"model={updated.model}{rebuilt}")
        if name == "adapter":
            return await self._switch_adapter(session_id, intent)
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
            task = await self.client.operations.ownership_transfer(
                session.active_task_id,
                to=self.agent_id,
                via="handoff",
                actor=session.principal,
            )
            new_run_id = self.client.store.run_of_task(task.id) or ""
            self.sessions.set_active(session_id, task_id=task.id, run_id=new_run_id)
            note = f"; active task handed off (run {new_run_id or 'n/a'})"
        self._append(
            session_id,
            kind="task",
            text=f"adapter {old_adapter} → {target}{note}",
        )
        return TUIResult(f"adapter={updated.adapter}{note}")

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
        if intent.name == "tasks":
            session = self._require_session(session_id)
            tasks = await self.client.operations.task_list()
            return TUIResult(render_tasks(tasks, active_task_id=session.active_task_id))
        if intent.name == "use":
            task_id = _required_arg(intent, "/use requires a task id")
            session = self._require_session(session_id)
            task = await self.client.get_task(task_id)
            if task.is_terminal:
                raise TUIUsageError(f"task {task_id} is terminal ({task.state})")
            self.sessions.set_active(
                session_id,
                task_id=task.id,
                run_id=session.active_run_id,
            )
            inbox = await self.client.human_inbox(session.principal)
            return TUIResult(f"active task {task.id} ({task.state})\n" + render_inbox(inbox))
        if intent.name == "handoff":
            to_agent = _required_arg(intent, "/handoff requires an agent id")
            session = self._require_active(session_id)
            task = await self.client.operations.ownership_transfer(
                session.active_task_id,
                to=to_agent,
                via="handoff",
                actor=session.principal,
            )
            new_run_id = self.client.store.run_of_task(task.id) or ""
            self.sessions.set_active(session_id, task_id=task.id, run_id=new_run_id)
            text = f"handed off task {task.id} to {to_agent} (run {new_run_id or 'n/a'})"
            self._append(session_id, kind="task", text=text, ref=task.id)
            return await self._finish_with_harness_output(session_id, text)
        if intent.name == "artifacts":
            session = self._require_active(session_id)
            task = await self.client.get_task(session.active_task_id)
            artifacts = [
                await self.client.operations.artifact_get(art_id) for art_id in task.artifacts
            ]
            return TUIResult(render_artifacts(artifacts))
        if intent.name == "show":
            art_id = _required_arg(intent, "/show requires an artifact id")
            self._require_active(session_id)
            artifact = await self.client.operations.artifact_get(art_id)
            return TUIResult(render_artifact_detail(artifact))
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
        if intent.name == "soft":
            return self._handle_soft_buffer(session_id, intent)
        if intent.name == "softs":
            session = self._require_session(session_id)
            return TUIResult(render_soft_buffer(session.soft_buffer))
        if intent.name == "promote":
            return await self._promote_soft_buffer(session_id, intent)
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
            "/permissions requires auto, plan, confirm, or read-only",
        )
        if value not in _PERMISSION_MODES:
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

    def _handle_soft_buffer(self, session_id: str, intent: InputIntent) -> TUIResult:
        """Buffer multi soft controls: /soft <text>|list|pop|clear."""
        session = self._require_session(session_id)
        if not intent.args:
            return TUIResult(render_soft_buffer(session.soft_buffer))
        head = intent.args[0].lower()
        if head in {"list", "ls", "show"}:
            return TUIResult(render_soft_buffer(session.soft_buffer))
        if head in {"clear", "reset"}:
            updated = self.sessions.clear_soft(session_id)
            return TUIResult(f"soft buffer cleared (was {len(session.soft_buffer)})")
        if head == "pop":
            updated, entry = self.sessions.pop_soft(session_id)
            if entry is None:
                return TUIResult("soft buffer is empty")
            return TUIResult(
                f"soft popped: {entry.text}\n{render_soft_buffer(updated.soft_buffer)}"
            )
        # Optional: /soft --intent redirect text...
        intent_name = "constrain"
        confidence = 1.0
        args = list(intent.args)
        while args and args[0].startswith("--"):
            flag = args.pop(0)
            if flag in {"--intent", "-i"} and args:
                intent_name = args.pop(0)
            elif flag in {"--confidence", "-c"} and args:
                try:
                    confidence = float(args.pop(0))
                except ValueError as exc:
                    raise TUIUsageError("/soft --confidence requires a number") from exc
            else:
                raise TUIUsageError(f"unknown /soft flag: {flag}")
        text = " ".join(args).strip()
        if not text:
            raise TUIUsageError(
                "/soft requires text, or list|pop|clear "
                "(optional: --intent constrain --confidence 1.0)"
            )
        if intent_name not in {
            "redirect",
            "clarify",
            "constrain",
            "abort_hint",
        }:
            raise TUIUsageError("/soft --intent must be redirect|clarify|constrain|abort_hint")
        if not (0.0 <= confidence <= 1.0):
            raise TUIUsageError("/soft --confidence must be in [0, 1]")
        updated = self.sessions.add_soft(
            session_id,
            text=text,
            intent=intent_name,
            confidence=confidence,
        )
        self._append(
            session_id,
            kind="soft",
            text=f"soft[{len(updated.soft_buffer)}] {text}",
        )
        return TUIResult(
            f"soft buffered ({len(updated.soft_buffer)}): {text}\n"
            f"{render_soft_buffer(updated.soft_buffer)}"
        )

    async def _promote_soft_buffer(
        self,
        session_id: str,
        intent: InputIntent,
    ) -> TUIResult:
        """Merge buffered soft signals (optional extra text) into task.amend."""
        session = self._require_active(session_id)
        extra = _joined_args(intent).strip()
        if extra:
            self.sessions.add_soft(session_id, text=extra, intent="constrain")
            session = self._require_session(session_id)
        if not session.soft_buffer:
            raise TUIUsageError("soft buffer empty — use /soft <text> to buffer, then /promote")

        signals = tuple(
            ControlSignal(
                strength="soft",
                intent=_control_intent(entry.intent),  # type: ignore[arg-type]
                principal_binding=session.principal,
                confidence=float(entry.confidence),
                source_kind="ui",
                text=entry.text,
                promotion="steering",
                run_id=session.active_run_id or None,
                interaction=InteractionRef(channel="tui", session_id=session_id),
            )
            for entry in session.soft_buffer
        )
        last_entry = session.soft_buffer[-1]
        steering_intent = _steering_intent(last_entry.intent)
        promoted = merge_soft_control_signals(
            signals,
            by=session.principal,
            intent=steering_intent,
        )
        buffered_count = len(session.soft_buffer)
        task = await self.client.amend(
            session.active_task_id,
            by=session.principal,
            text=promoted.amendment.text,
            intent=steering_intent,
            promotion_provenance=promoted.provenance,
        )
        self.sessions.clear_soft(session_id)
        line = (
            f"promoted {buffered_count} soft → amended task {task.id} "
            f"(profile={promoted.provenance.get('profile')}, "
            f"merged={promoted.provenance.get('signal_count')})"
        )
        self._append(session_id, kind="task", text=line, ref=task.id)
        preview = promoted.amendment.text.replace("\n", " | ")
        if len(preview) > 160:
            preview = preview[:157] + "..."
        primary = f"{line}\nmerged: {preview}"
        return await self._finish_with_harness_output(session_id, primary)

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
        return TUIResult("\n".join(parts))

    def _adapter_process_payload(self, run_id: str) -> dict[str, Any] | None:
        if not run_id:
            return None
        results = getattr(self.client.adapter, "process_results", None)
        if not isinstance(results, dict):
            return None
        payload = results.get(run_id)
        return payload if isinstance(payload, dict) else None

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


def _control_intent(name: str) -> str:
    if name in {
        "redirect",
        "clarify",
        "constrain",
        "halt",
        "resume",
        "affirm",
        "deny",
    }:
        return name
    if name == "abort_hint":
        return "constrain"
    return "constrain"


_STEERING_INTENTS: dict[str, SteeringIntent] = {
    "redirect": "redirect",
    "clarify": "clarify",
    "constrain": "constrain",
    "abort_hint": "abort_hint",
}


def _steering_intent(name: str) -> SteeringIntent:
    return _STEERING_INTENTS.get(name, "constrain")


def _adapter_can_project(adapter: object) -> bool:
    return callable(getattr(adapter, "observe", None)) or callable(
        getattr(adapter, "peek_events", None)
    )


def _join_output(primary: str, secondary: str) -> str:
    if not secondary:
        return primary
    return f"{primary}\n{secondary}"


def _diff_summary(cwd: Path) -> str:
    result = subprocess.run(
        ("git", "-C", str(cwd), "diff", "--stat"),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        suffix = f": {detail}" if detail else ""
        return f"diff unavailable{suffix}"
    summary = result.stdout.strip()
    if not summary:
        return "diff is empty"
    return summary
