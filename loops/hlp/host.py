from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from loops.loop2.adapters import AgentAdapter, FakeAgentAdapter
from loops.loop2.events import HLPEvent, InMemoryEventBus
from loops.loop2.sdk import HLPClient
from loops.loop2.sqlite_store import SQLiteHumanLoopStore
from loops.loop2.store import HumanLoopStore


@dataclass
class HLPHost:
    """Embedding host for HLP applications.

    The host is the public seam for applications that want to run HLP without
    caring about the internal loop0/loop2 layout. It owns the SDK client and
    the local event stream; richer channel/session hosts can build on this.
    """

    store: HumanLoopStore = field(default_factory=HumanLoopStore)
    adapter: AgentAdapter = field(default_factory=FakeAgentAdapter)
    event_bus: InMemoryEventBus = field(default_factory=InMemoryEventBus)
    client: HLPClient = field(init=False)

    def __post_init__(self) -> None:
        self.client = HLPClient(
            store=self.store,
            adapter=self.adapter,
            event_bus=self.event_bus,
        )

    @classmethod
    def in_memory(
        cls,
        *,
        adapter: AgentAdapter | None = None,
    ) -> "HLPHost":
        return cls(adapter=adapter or FakeAgentAdapter())

    @classmethod
    def sqlite(
        cls,
        path: str | Path,
        *,
        adapter: AgentAdapter | None = None,
    ) -> "HLPHost":
        return cls(
            store=SQLiteHumanLoopStore(path),
            adapter=adapter or FakeAgentAdapter(),
        )

    @property
    def events(self) -> list[HLPEvent]:
        return list(self.event_bus.events)
