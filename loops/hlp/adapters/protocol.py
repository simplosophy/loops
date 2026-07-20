from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..objects import AdapterOperationContext
from ..types import HarnessConformance, HarnessEventKind


class AgentAdapterError(RuntimeError):
    """Structured adapter failure raised before HLP state is advanced."""

    def __init__(
        self,
        adapter: str,
        operation: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{adapter}.{operation}: {message}")
        self.adapter = adapter
        self.operation = operation
        self.details = details or {}


@dataclass(frozen=True)
class ProcessResult:
    """Result returned by a process runner."""

    exit_code: int
    stdout: str
    stderr: str


ProcessRunner = Callable[
    [tuple[str, ...], dict[str, Any], float],
    Awaitable[ProcessResult] | ProcessResult,
]


@dataclass(frozen=True)
class AgentRunHandle:
    """Handle returned by HLP when work is delegated to an external harness."""

    run_id: str
    task_id: str
    agent_id: str
    correlation_id: str
    capability: str = ""
    parent_run: str | None = None


@dataclass(frozen=True)
class HarnessCapabilities:
    """Human-interaction capabilities exposed by an existing agent harness."""

    name: str
    conformance: tuple[HarnessConformance, ...] = ("delegate-only",)
    description: str = ""


@dataclass(frozen=True)
class HarnessEvent:
    """Semantic event projected from a harness into HLP.

    This object describes human-facing interaction semantics only. It does not
    model the harness execution internals.
    """

    kind: HarnessEventKind
    task_id: str
    run_id: str
    agent_id: str
    prompt: str = ""
    options: tuple[Any, ...] = ()
    context: tuple[Any, ...] = ()
    artifact_type: str = ""
    artifact_uri: str = ""
    artifact_checksum: str = ""
    artifact_size: int = 0


@dataclass(frozen=True)
class HarnessEventDelivery:
    """A durable harness event cursor plus the HLP semantic event."""

    cursor: str
    event: HarnessEvent


@runtime_checkable
class AgentAdapter(Protocol):
    """HLP to agent-harness adapter contract.

    The adapter is the only supported boundary from HLP into an agent framework,
    CLI, or process. Implementations must keep `task_id` as the run correlation
    id.
    """

    async def delegate(
        self,
        task_id: str,
        agent_id: str,
        capability: str,
        input: dict[str, Any],
        parent_run: str | None = None,
        *,
        operation_context: AdapterOperationContext | None = None,
    ) -> str:
        """Delegate a task to an agent and return the runtime run id."""
        ...

    async def block(
        self,
        run_id: str,
        checkpoint_id: str,
        reason: str,
        *,
        context: AdapterOperationContext | None = None,
    ) -> None:
        """Block a run until the HLP checkpoint is resolved."""
        ...

    async def resume(
        self,
        run_id: str,
        resolution: Any,
        *,
        context: AdapterOperationContext | None = None,
    ) -> None:
        """Resume a blocked run with the human resolution payload."""
        ...

    async def steer(
        self,
        run_id: str,
        amendment: Any,
        *,
        context: AdapterOperationContext | None = None,
    ) -> None:
        """Inject a steering amendment without restarting the run."""
        ...

    async def handoff(
        self,
        run_id: str,
        to_agent: str,
        context: dict[str, Any],
        *,
        operation_context: AdapterOperationContext | None = None,
    ) -> str:
        """Handoff a run to another agent while preserving task correlation."""
        ...

    async def cancel(
        self,
        run_id: str,
        reason: str,
        *,
        operation_context: AdapterOperationContext | None = None,
    ) -> None:
        """Cancel a runtime run."""
        ...

    async def healthcheck(self) -> dict[str, Any]:
        """Return adapter health metadata."""
        ...


@runtime_checkable
class HarnessAdapter(AgentAdapter, Protocol):
    """Adapter for wrapping existing harnesses as HLP human-interaction sources."""

    def harness_capabilities(self) -> HarnessCapabilities:
        """Return human-interaction projection capabilities."""
        ...

    async def observe(self, run_id: str) -> tuple[HarnessEvent, ...]:
        """Return harness events that should be projected into HLP objects."""
        ...


@runtime_checkable
class ReliableHarnessEventAdapter(Protocol):
    """Optional non-destructive harness event delivery extension."""

    async def peek_events(
        self,
        run_id: str,
        *,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> tuple[HarnessEventDelivery, ...]:
        """Return unacknowledged harness events without consuming them."""
        ...

    async def ack_events(self, run_id: str, *, through: str) -> None:
        """Acknowledge projected harness events up to and including `through`."""
        ...
