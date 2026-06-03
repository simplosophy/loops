"""Stable profile objects that can be injected into prompts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class AgentProfile:
    name: str = "agent"
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    model: str = ""
    capabilities: frozenset[str] = field(default_factory=frozenset)
    limits: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolProfile:
    name: str
    description: str
    input_schema: dict[str, Any]
    effects: frozenset[str] = field(default_factory=frozenset)
    risk: Literal["low", "medium", "high"] = "low"
    source: str = "core"
    requires_approval: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InteractionContext:
    source: str = "direct"
    session_id: str | None = None
    thread_id: str | None = None
    actor_id: str | None = None
    reply_to: str | None = None
    audience: Literal["user", "group", "system"] = "user"
    interactive: bool = False
    stream: bool = False
    locale: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ComponentProfile:
    name: str
    kind: str = "component"
    priority: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyProfile:
    max_turns: int
    allow_tool_errors: bool
    approval_available: bool
    parallel_tool_calls: bool | None = None
    max_parallel_tool_calls: int | None = 1
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RunProfile:
    run_id: str
    thread_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
