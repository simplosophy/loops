"""Provider-neutral runtime data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class ToolCall:
    """A provider-neutral request to execute one tool."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: f"call_{uuid4().hex[:12]}")
    raw: Any | None = None


@dataclass
class Message:
    """Provider-neutral chat message."""

    role: str
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class UserInput:
    """Normalized input passed to an Agent run."""

    text: str
    attachments: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    channel_context: Any | None = None

    @classmethod
    def coerce(cls, value: str | "UserInput") -> "UserInput":
        if isinstance(value, UserInput):
            return value
        return cls(text=str(value))
