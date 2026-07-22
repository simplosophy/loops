from __future__ import annotations

from ._base import TUIResult, TUIUsageError, _ControllerBase, _required_arg
from .commands import InputIntent
from .render import (
    render_artifact_detail,
    render_artifacts,
    render_inbox,
    render_progress,
    render_tasks,
)


class WorkCmds(_ControllerBase):
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
            current = await self.client.get_task(session.active_task_id)
            if current.ownership.assignee == to_agent:
                raise TUIUsageError(f"task is already assigned to {to_agent}")
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
        if intent.name == "progress":
            session = self._require_session(session_id)
            if not session.active_run_id:
                return TUIResult("no active run")
            snapshot = await self.client.run_progress(session.active_run_id)
            if snapshot is None:
                return TUIResult(
                    "no progress events from this adapter (pi/kimi wires carry none yet)"
                )
            return TUIResult(render_progress(snapshot))
        return await super()._handle_hlp_command(session_id, intent)
