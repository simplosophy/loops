from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .adapters import AgentAdapter, FakeAgentAdapter
from .events import HLPEvent, InMemoryEventBus
from .sdk import HLPClient
from .sqlite_store import SQLiteHumanLoopStore
from .store import HumanLoopStore


@dataclass
class HLPHost:
    """Embedding host for HLP applications.

    The host is the public seam for applications that want to embed HLP without
    adopting a built-in execution harness. It owns the SDK client and local
    event stream; richer channel/session hosts can build on this.
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
