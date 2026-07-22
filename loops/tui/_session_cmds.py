from __future__ import annotations

import subprocess
from pathlib import Path

from ._base import TUIResult, TUIUsageError, _ControllerBase, _required_arg
from .commands import InputIntent
from .render import render_help, render_status, render_transcript

_PERMISSION_MODES = frozenset({"auto", "plan", "confirm", "read-only"})


class SessionCmds(_ControllerBase):
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
        if name == "permissions":
            # Dispatched here (not in HlpCmds) so mixins only depend on the base.
            return self._set_permissions(session_id, intent)
        return await super()._handle_command(session_id, intent)

    async def _status(self, session_id: str) -> TUIResult:
        session = self._require_session(session_id)
        task_state = "none"
        if session.active_task_id:
            task_state = (await self.client.get_task(session.active_task_id)).state
        inbox = await self.client.human_inbox(session.principal)
        return TUIResult(
            render_status(session, task_state=task_state, inbox_count=len(inbox)),
        )

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
