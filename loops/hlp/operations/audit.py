from __future__ import annotations

from ._base import HumanLoopOperationsBase


class AuditOps(HumanLoopOperationsBase):
    # ────────────────── Audit (spec §4.1, no write operations) ──────────────────

    async def audit_query(
        self,
        *,
        task_id: str | None = None,
        actor: str | None = None,
        action: str | None = None,
    ) -> list:
        """audit.query (spec §4.1)."""
        return self.store.audit_log.query(task_id=task_id, actor=actor, action=action)

    async def audit_replay(self, task_id: str) -> list:
        """audit.replay (spec §4.1). Replay the full history of a Task."""
        return self.store.audit_log.replay(task_id)
