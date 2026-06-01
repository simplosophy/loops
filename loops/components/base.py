"""Component contribution contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loops.profiles import ComponentProfile


@dataclass
class Contribution:
    prompt_blocks: list[str] = field(default_factory=list)
    tools: list[Any] = field(default_factory=list)
    channels: list[Any] = field(default_factory=list)
    hooks: list[Any] = field(default_factory=list)
    state_adapters: list[Any] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class Component:
    profile = ComponentProfile(name="component")

    async def setup(self, agent: Any) -> None:
        del agent

    async def contribute(self, run_context: Any) -> Contribution:
        del run_context
        return Contribution()

    async def handle_event(self, event: Any) -> None:
        del event

    async def teardown(self) -> None:
        return None
