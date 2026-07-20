from __future__ import annotations

from typing import Any

from ..objects import LedgerEntry
from ._base import HumanLoopOperationsBase


class LedgerOps(HumanLoopOperationsBase):
    # ────────────────── Ledger (spec §4.1) ──────────────────

    async def ledger_read(self, scope: str, key: str) -> Any | None:
        """ledger.read (spec §4.1, §3.8)."""
        ledger = self.store._find_ledger_by_scope_for_update(scope)
        if ledger is None:
            return None
        return ledger.read(key)

    async def ledger_write(
        self,
        scope: str,
        key: str,
        value: Any,
        *,
        by: str,
    ) -> LedgerEntry:
        """ledger.write (spec §4.1, §3.8). Append-only + audit."""
        ledger = self.store.get_or_create_ledger(scope)
        entry = ledger.write(key, value, by=by)
        self._audit(
            actor=by,
            action="ledger.written",
            subject=("ledger", ledger.id),
            task_id=by,
            after={"key": key, "scope": scope},
        )
        return entry

    async def ledger_history(self, scope: str, key: str) -> list[LedgerEntry]:
        """ledger.history (spec §4.1)."""
        ledger = self.store._find_ledger_by_scope_for_update(scope)
        if ledger is None:
            return []
        return ledger.history(key)
