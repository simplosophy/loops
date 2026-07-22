from __future__ import annotations

from loops.hlp import (
    ControlSignal,
    InteractionRef,
    SteeringIntent,
    merge_soft_control_signals,
)

from ._base import TUIResult, TUIUsageError, _ControllerBase, _joined_args, _required_text
from .commands import InputIntent
from .render import render_soft_buffer

_STEERING_INTENTS: dict[str, SteeringIntent] = {
    "redirect": "redirect",
    "clarify": "clarify",
    "constrain": "constrain",
    "abort_hint": "abort_hint",
}


class ControlCmds(_ControllerBase):
    async def _handle_hlp_command(self, session_id: str, intent: InputIntent) -> TUIResult:
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
        return await super()._handle_hlp_command(session_id, intent)

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


def _steering_intent(name: str) -> SteeringIntent:
    return _STEERING_INTENTS.get(name, "constrain")
