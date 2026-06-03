"""Execution policy and approval contracts."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ApprovalRequest:
    """A request for the host app to approve a risky action."""

    reason: str
    tool_name: str
    risk: str = "medium"
    metadata: dict[str, Any] = field(default_factory=dict)


ApprovalHandler = Callable[[ApprovalRequest], bool | Awaitable[bool]]


@dataclass
class AgentPolicy:
    """Runtime defaults for one Agent."""

    max_turns: int = 20
    allow_tool_errors: bool = True
    parallel_tool_calls: bool | None = None
    max_parallel_tool_calls: int | None = 1
    approval_handler: ApprovalHandler | None = None
    shell_timeout_seconds: float = 60.0
    shell_max_output_chars: int = 30_000
    shell_require_approval_for_background: bool = True
    shell_external_path_policy: str = "ask"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def approval_available(self) -> bool:
        return self.approval_handler is not None

    async def request_approval(self, request: ApprovalRequest) -> bool:
        if self.approval_handler is None:
            return False
        decision = self.approval_handler(request)
        if inspect.isawaitable(decision):
            return bool(await decision)
        return bool(decision)
