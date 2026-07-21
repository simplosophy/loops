from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..objects import AdapterOperationContext
from ..schema import to_wire
from ._registry import RunRegistryAdapter
from .protocol import (
    AgentAdapterError,
    AgentRunHandle,
    HarnessCapabilities,
    HarnessEvent,
    HarnessEventDelivery,
)


@dataclass
class FakeAgentAdapter(RunRegistryAdapter):
    """Deterministic adapter for tests and demos.

    It records contract calls, creates stable run ids, and never reaches network
    or a local agent binary.
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
        run_id = self._next_run_id()
        self._runs[run_id] = AgentRunHandle(
            run_id=run_id,
            task_id=task_id,
            agent_id=agent_id,
            correlation_id=task_id,
            capability=capability,
            parent_run=parent_run,
        )
        self.calls.append(
            (
                "delegate",
                {
                    "run_id": run_id,
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "capability": capability,
                    "input": input,
                    "parent_run": parent_run,
                    "operation_context": (
                        to_wire(operation_context) if operation_context is not None else None
                    ),
                },
            )
        )
        return run_id

    async def handoff(
        self,
        run_id: str,
        to_agent: str,
        context: dict[str, Any],
        *,
        operation_context: AdapterOperationContext | None = None,
    ) -> str:
        current = self._require_run(run_id, "handoff", context=operation_context)
        new_run_id = self._next_run_id()
        self._runs[new_run_id] = AgentRunHandle(
            run_id=new_run_id,
            task_id=current.task_id,
            agent_id=to_agent,
            correlation_id=current.correlation_id,
            capability=current.capability,
            parent_run=run_id,
        )
        self.calls.append(
            (
                "handoff",
                {
                    "from_run": run_id,
                    "to_run": new_run_id,
                    "to_agent": to_agent,
                    "context": context,
                    "operation_context": (
                        to_wire(operation_context) if operation_context is not None else None
                    ),
                },
            )
        )
        return new_run_id

    async def healthcheck(self) -> dict[str, Any]:
        result = {"status": "ok", "adapter": "fake", "runs": len(self._runs)}
        self.calls.append(("healthcheck", result))
        return result


class FakeHarnessAdapter(FakeAgentAdapter):
    """Deterministic harness adapter for tests and demos."""

    def __init__(
        self,
        *,
        capabilities: HarnessCapabilities | None = None,
    ) -> None:
        super().__init__()
        self._capabilities = capabilities or HarnessCapabilities(name="fake-harness")
        self._events: dict[str, list[HarnessEventDelivery]] = {}
        self._event_counter = 0

    def harness_capabilities(self) -> HarnessCapabilities:
        return self._capabilities

    def queue_event(self, run_id: str, event: HarnessEvent) -> None:
        self._require_run(run_id, "queue_event")
        self._event_counter += 1
        delivery = HarnessEventDelivery(
            cursor=f"evt_{self._event_counter:06d}",
            event=event,
        )
        self._events.setdefault(run_id, []).append(delivery)

    async def observe(self, run_id: str) -> tuple[HarnessEvent, ...]:
        deliveries = await self.peek_events(run_id)
        if deliveries:
            await self.ack_events(run_id, through=deliveries[-1].cursor)
        events = tuple(delivery.event for delivery in deliveries)
        self.calls.append(("observe", {"run_id": run_id, "events": len(events)}))
        return events

    async def peek_events(
        self,
        run_id: str,
        *,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> tuple[HarnessEventDelivery, ...]:
        self._require_run(run_id, "peek_events")
        deliveries = self._events.get(run_id, [])
        start = 0
        if cursor is not None:
            for index, delivery in enumerate(deliveries):
                if delivery.cursor == cursor:
                    start = index + 1
                    break
            else:
                raise AgentAdapterError(
                    self.__class__.__name__,
                    "peek_events",
                    "unknown event cursor",
                    details={"run_id": run_id, "cursor": cursor},
                )
        result = deliveries[start:]
        if limit is not None:
            result = result[:limit]
        self.calls.append(("peek_events", {"run_id": run_id, "events": len(result)}))
        return tuple(result)

    async def ack_events(self, run_id: str, *, through: str) -> None:
        self._require_run(run_id, "ack_events")
        deliveries = self._events.get(run_id, [])
        for index, delivery in enumerate(deliveries):
            if delivery.cursor == through:
                del deliveries[: index + 1]
                if not deliveries:
                    self._events.pop(run_id, None)
                self.calls.append(("ack_events", {"run_id": run_id, "through": through}))
                return
        raise AgentAdapterError(
            self.__class__.__name__,
            "ack_events",
            "unknown event cursor",
            details={"run_id": run_id, "through": through},
        )


InMemoryAgentAdapter = FakeAgentAdapter
