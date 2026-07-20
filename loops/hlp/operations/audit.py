from __future__ import annotations

from ..objects import AdapterOutboxRecord
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

    async def pending_adapter_outbox(self) -> tuple[AdapterOutboxRecord, ...]:
        """Snapshot of adapter outbox records still pending (HLP-industrial).

        Recovery loop: retry the recorded operation with the same
        idempotency_key. The idempotency path reuses the persisted outbox
        intent and never repeats already-committed side effects.
        """
        return tuple(
            record for record in self.store.adapter_outbox_records() if record.state == "pending"
        )
