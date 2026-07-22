"""Run-registry machinery shared by real adapters and testing doubles.

This is the production base for adapter run bookkeeping: run handles,
contract-call records, and lookup helpers. `FakeAgentAdapter` (testing tier)
and `ProcessAgentAdapter` (first-class process/CLI adapters) both build on
it — production no longer inherits from a class named "Fake".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..objects import AdapterOperationContext
from ..schema import to_wire
from . import _util as util
from .protocol import AgentAdapterError, AgentRunHandle


@dataclass
class RunRegistryAdapter:
    """Run registry base: run handles, contract-call records, lookup helpers."""

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    _run_counter: int = field(default=0, repr=False)
    _runs: dict[str, AgentRunHandle] = field(default_factory=dict, repr=False)

    def run_handle(self, run_id: str) -> AgentRunHandle | None:
        return self._runs.get(run_id)

    def task_of_run(self, run_id: str) -> str | None:
        handle = self._runs.get(run_id)
        return handle.task_id if handle is not None else None

    def calls_of(self, method: str) -> list[tuple[str, dict[str, Any]]]:
        return [call for call in self.calls if call[0] == method]

    def _next_run_id(self) -> str:
        self._run_counter += 1
        return f"run_{self._run_counter:06d}"

    # ── shared record-only implementations (real adapters call these after
    # executing their own side effects to record the contract call) ──

    async def block(
        self,
        run_id: str,
        checkpoint_id: str,
        reason: str,
        *,
        context: AdapterOperationContext | None = None,
    ) -> None:
        self._require_run(run_id, "block", context=context)
        self.calls.append(
            (
                "block",
                {
                    "run_id": run_id,
                    "checkpoint_id": checkpoint_id,
                    "reason": reason,
                    "operation_context": to_wire(context) if context is not None else None,
                },
            )
        )

    async def resume(
        self,
        run_id: str,
        resolution: Any,
        *,
        context: AdapterOperationContext | None = None,
    ) -> None:
        self._require_run(run_id, "resume", context=context)
        self.calls.append(
            (
                "resume",
                {
                    "run_id": run_id,
                    "resolution": resolution,
                    "operation_context": to_wire(context) if context is not None else None,
                },
            )
        )

    async def steer(
        self,
        run_id: str,
        amendment: Any,
        *,
        context: AdapterOperationContext | None = None,
    ) -> None:
        self._require_run(run_id, "steer", context=context)
        self.calls.append(
            (
                "steer",
                {
                    "run_id": run_id,
                    "amendment": util.adapter_payload(amendment),
                    "operation_context": to_wire(context) if context is not None else None,
                },
            )
        )

    async def cancel(
        self,
        run_id: str,
        reason: str,
        *,
        operation_context: AdapterOperationContext | None = None,
    ) -> None:
        self._require_run(run_id, "cancel", context=operation_context)
        self.calls.append(
            (
                "cancel",
                {
                    "run_id": run_id,
                    "reason": reason,
                    "operation_context": (
                        to_wire(operation_context) if operation_context is not None else None
                    ),
                },
            )
        )

    def _require_run(
        self,
        run_id: str,
        operation: str,
        *,
        context: AdapterOperationContext | None = None,
    ) -> AgentRunHandle:
        handle = self._runs.get(run_id)
        if handle is None and context is not None:
            handle = AgentRunHandle(
                run_id=run_id,
                task_id=context.task_id,
                agent_id="",
                correlation_id=context.correlation_id,
            )
            self._runs[run_id] = handle
        if handle is None:
            raise AgentAdapterError(
                self.__class__.__name__,
                operation,
                "unknown run id",
                details={"run_id": run_id},
            )
        return handle
