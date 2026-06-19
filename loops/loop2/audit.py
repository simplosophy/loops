from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ._ids import gen_audit_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class AuditEvent:
    """不可变的审计日志条目 (spec §3.9)。

    - seq: scope 内单调递增
    - action: "<object>.<verb>" (spec §4.2)
    - subject: 操作目标 {kind, id}
    - task_id: 始终关联聚合根
    - before/after: 变更前后状态 (可选)
    """

    seq: int
    at: datetime = field(default_factory=_now)
    actor: str = ""
    action: str = ""                       # 如 "task.created"
    subject: "tuple[str, str]" = ("", "")  # (kind, id)
    task_id: str | None = None
    before: Any = None
    after: Any = None
    id: str = field(default_factory=gen_audit_id)


class AuditLog:
    """append-only 审计日志 (spec §3.9)。

    - 永不删除/修改
    - seq 单调递增
    - 支持 query / replay
    """

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._seq = 0

    def append(
        self,
        *,
        actor: str,
        action: str,
        subject: tuple[str, str] = ("", ""),
        task_id: str | None = None,
        before: Any = None,
        after: Any = None,
    ) -> AuditEvent:
        """追加一条审计事件，返回该事件。永不失败、永不阻塞业务 (spec §3.9)。"""
        self._seq += 1
        event = AuditEvent(
            seq=self._seq,
            actor=actor,
            action=action,
            subject=subject,
            task_id=task_id,
            before=before,
            after=after,
        )
        self._events.append(event)
        return event

    def query(
        self,
        *,
        task_id: str | None = None,
        actor: str | None = None,
        action: str | None = None,
    ) -> list[AuditEvent]:
        """按条件查询 (spec §4.1 audit.query)。"""
        result = self._events
        if task_id is not None:
            result = [e for e in result if e.task_id == task_id]
        if actor is not None:
            result = [e for e in result if e.actor == actor]
        if action is not None:
            result = [e for e in result if e.action == action]
        return list(result)

    def replay(self, task_id: str) -> list[AuditEvent]:
        """回放某 Task 的完整历史 (spec §4.1 audit.replay)。"""
        return [e for e in self._events if e.task_id == task_id]

    def all(self) -> list[AuditEvent]:
        """全部事件，按 seq 升序。"""
        return list(self._events)

    @property
    def count(self) -> int:
        return len(self._events)
