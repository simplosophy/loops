"""Tool authoring and execution contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loops.loop0.events import AgentEvent
from loops.loop0.policy import AgentPolicy, ApprovalRequest
from loops.loop0.profiles import ToolProfile


@dataclass
class ToolResult:
    """Result of one tool call."""

    output: str = ""
    error: str | None = None
    status: str = "success"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return self.status == "success" and self.error is None

    @classmethod
    def success(cls, output: Any = "", **metadata: Any) -> "ToolResult":
        return cls(output=str(output), metadata=metadata)

    @classmethod
    def failure(cls, error: str, *, status: str = "error", **metadata: Any) -> "ToolResult":
        return cls(output="", error=error, status=status, metadata=metadata)

    def message_content(self) -> str:
        if self.is_success:
            return self.output
        return f"Error: {self.error or self.status}"


@dataclass
class ToolContext:
    """Context available to every tool execution."""

    agent_id: str
    run_id: str
    workspace: Path
    policy: AgentPolicy
    state: Any
    emit: Callable[[AgentEvent], Awaitable[None]]
    cancellation_checker: Callable[[], bool] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    async def request_approval(self, request: ApprovalRequest) -> bool:
        return await self.policy.request_approval(request)

    def check_cancelled(self) -> bool:
        return bool(self.cancellation_checker and self.cancellation_checker())


class BaseTool:
    """Minimal tool base class."""

    profile: ToolProfile

    async def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        raise NotImplementedError


class ToolRegistry:
    """A run-local registry of model-callable tools."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        name = tool.profile.name
        if name in self._tools:
            raise ValueError(f"Tool '{name}' is already registered")
        self._tools[name] = tool

    def extend(self, tools: list[BaseTool]) -> None:
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    @property
    def tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    @property
    def profiles(self) -> list[ToolProfile]:
        return [tool.profile for tool in self.tools]

    async def execute(self, name: str, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult.failure(f"Unknown tool: {name}", status="not_found")
        try:
            return await tool.execute(ctx, args)
        except Exception as exc:
            return ToolResult.failure(f"Error executing {name}: {exc}")
