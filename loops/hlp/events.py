from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class HLPEvent:
    """SDK-level lifecycle event emitted after a successful HLP operation."""

    seq: int
    action: str
    task_id: str
    subject: tuple[str, str]
    payload: dict[str, Any] = field(default_factory=dict)
    at: datetime = field(default_factory=_now)


class EventBus(Protocol):
    async def publish(self, event: HLPEvent) -> None:
        ...


@dataclass
class InMemoryEventBus:
    """Simple event bus for SDK tests, local demos, and embedding hosts."""

    events: list[HLPEvent] = field(default_factory=list)
    _seq: int = field(default=0, repr=False)

    async def emit(
        self,
        *,
        action: str,
        task_id: str,
        subject: tuple[str, str],
        payload: dict[str, Any] | None = None,
    ) -> HLPEvent:
        self._seq += 1
        event = HLPEvent(
            seq=self._seq,
            action=action,
            task_id=task_id,
            subject=subject,
            payload=payload or {},
        )
        await self.publish(event)
        return event

    async def publish(self, event: HLPEvent) -> None:
        self.events.append(event)

