"""Minimal loop0 runtime I/O primitives."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeAlias, runtime_checkable

from loops.loop0.events import AgentEvent


@dataclass
class InMemoryEventSink:
    """Event sink useful for tests and embedding hosts."""

    events: list[AgentEvent] = field(default_factory=list)

    async def send(self, event: AgentEvent) -> None:
        self.events.append(event)


class NullEventSink:
    async def send(self, event: AgentEvent) -> None:
        del event


@runtime_checkable
class EventSink(Protocol):
    async def send(self, event: AgentEvent) -> None:
        """Consume one runtime event."""


EventCallback: TypeAlias = Callable[[AgentEvent], None | Awaitable[None]]
EventSinkLike: TypeAlias = EventSink | EventCallback | None


@dataclass
class CallableEventSink:
    callback: EventCallback

    async def send(self, event: AgentEvent) -> None:
        result = self.callback(event)
        if inspect.isawaitable(result):
            await result


def normalize_event_sink(event_sink: EventSinkLike) -> EventSink:
    if event_sink is None:
        return NullEventSink()
    if isinstance(event_sink, EventSink):
        return event_sink
    if callable(event_sink):
        return CallableEventSink(event_sink)
    raise TypeError("event_sink must implement EventSink, be callable, or be None")


def event_payload_text(event: AgentEvent, key: str = "text") -> str:
    return str(event.payload.get(key) or "")
