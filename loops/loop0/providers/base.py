"""Provider-neutral model adapter contracts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from loops.loop0.profiles import ProviderProfile, ToolProfile
from loops.loop0.types import Message, ToolCall


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass
class ProviderRequest:
    messages: list[Message]
    tools: list[ToolProfile] = field(default_factory=list)
    stream: bool = False
    parallel_tool_calls: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: ProviderUsage | None = None
    stop_reason: str | None = None
    message_metadata: dict[str, Any] = field(default_factory=dict)
    raw: Any | None = None


@dataclass
class ProviderEvent:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


class Provider:
    """Base provider adapter."""

    profile: ProviderProfile

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        response = await self.generate(request)
        if response.content:
            yield ProviderEvent(type="delta", payload={"text": response.content})
        yield ProviderEvent(type="response", payload={"response": response})
