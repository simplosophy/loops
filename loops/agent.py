"""Agent definition and public factory."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loops.channels.base import Channel
from loops.components.base import Component
from loops.logging import EventLogger, LoggerLike, normalize_logger
from loops.policy import AgentPolicy
from loops.prompt import PromptTemplate
from loops.providers.base import Provider
from loops.runtime import AgentRuntime, AgentResult
from loops.state import AgentState
from loops.tools.base import BaseTool
from loops.tools.shell import ShellTool
from loops.types import UserInput


@dataclass(frozen=True)
class AgentSpec:
    """Immutable definition of an agent's capabilities."""

    prompt: PromptTemplate
    provider: Provider
    tools: tuple[BaseTool, ...] = field(default_factory=tuple)
    channels: tuple[Channel, ...] = field(default_factory=tuple)
    components: tuple[Component, ...] = field(default_factory=tuple)
    policy: AgentPolicy = field(default_factory=AgentPolicy)
    metadata: dict[str, Any] = field(default_factory=dict)
    logger: LoggerLike = None

    def validate(self) -> None:
        if not self.prompt.system.strip():
            raise ValueError("AgentSpec.prompt.system cannot be empty")
        if self.prompt.engine != "jinja":
            raise ValueError(f"Unsupported prompt engine: {self.prompt.engine}")
        if self.provider is None:
            raise ValueError("AgentSpec.provider is required")
        names: set[str] = set()
        for tool in self.tools:
            name = tool.profile.name
            if name in names:
                raise ValueError(f"Duplicate tool name: {name}")
            names.add(name)

    def fork(self, **overrides: Any) -> "AgentSpec":
        values = {
            "prompt": self.prompt,
            "provider": self.provider,
            "tools": self.tools,
            "channels": self.channels,
            "components": self.components,
            "policy": self.policy,
            "metadata": dict(self.metadata),
            "logger": self.logger,
            **overrides,
        }
        return AgentSpec(**values)

    def compile(self, *, state: AgentState | None = None, workspace: str | Path | None = None) -> "Agent":
        return Agent(spec=self, state=state, workspace=workspace)


class Agent:
    """A long-lived agent with state and a reusable runtime."""

    def __init__(
        self,
        *,
        spec: AgentSpec,
        state: AgentState | None = None,
        workspace: str | Path | None = None,
    ) -> None:
        spec.validate()
        self.spec = spec
        self.state = state or AgentState()
        self.workspace = Path(workspace or ".loops-workspace").expanduser().resolve(strict=False)
        self.logger: EventLogger = normalize_logger(spec.logger)
        self.runtime = AgentRuntime(self)
        self._setup_complete = False

    async def run(
        self,
        input: str | UserInput,
        *,
        thread_id: str | None = None,
        channel: Channel | None = None,
    ) -> AgentResult:
        return await self.runtime.run(UserInput.coerce(input), thread_id=thread_id, channel=channel)

    async def stream(
        self,
        input: str | UserInput,
        *,
        thread_id: str | None = None,
        channel: Channel | None = None,
    ):
        result = await self.run(input, thread_id=thread_id, channel=channel)
        for event in result.events:
            yield event

    def attach(
        self,
        *,
        tools: list[BaseTool] | None = None,
        channels: list[Channel] | None = None,
        components: list[Component] | None = None,
    ) -> "Agent":
        spec = self.spec.fork(
            tools=(*self.spec.tools, *(tools or [])),
            channels=(*self.spec.channels, *(channels or [])),
            components=(*self.spec.components, *(components or [])),
        )
        return Agent(spec=spec, state=self.state, workspace=self.workspace)

    def fork(self, **overrides: Any) -> "Agent":
        return Agent(spec=self.spec.fork(**overrides), state=self.state.snapshot(), workspace=self.workspace)

    async def close(self) -> None:
        for component in self.spec.components:
            await component.teardown()


def agent(
    prompt: str | PromptTemplate,
    *,
    provider: Provider,
    tools: list[BaseTool] | None = None,
    channels: list[Channel] | None = None,
    components: list[Component] | None = None,
    policy: AgentPolicy | None = None,
    metadata: dict[str, Any] | None = None,
    logger: LoggerLike = None,
    workspace: str | Path | None = None,
    state: AgentState | None = None,
) -> Agent:
    """Create an Agent from the minimal public API."""

    template = prompt if isinstance(prompt, PromptTemplate) else PromptTemplate(system=str(prompt))
    resolved_tools = [ShellTool()] if tools is None else tools
    spec = AgentSpec(
        prompt=template,
        provider=provider,
        tools=tuple(resolved_tools),
        channels=tuple(channels or []),
        components=tuple(components or []),
        policy=policy or AgentPolicy(),
        metadata=dict(metadata or {}),
        logger=logger,
    )
    return spec.compile(state=state, workspace=workspace)
