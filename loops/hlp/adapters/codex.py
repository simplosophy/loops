from __future__ import annotations

import inspect
from typing import Any

from ..objects import AdapterOperationContext
from ..schema import to_wire
from . import _parsing as parsing
from . import _util as util
from .fake import FakeAgentAdapter
from .process import PromptCLIAdapter, run_prompt_process, cli_operation_prompt
from .protocol import (
    AgentAdapterError,
    AgentRunHandle,
    HarnessCapabilities,
    HarnessEvent,
    HarnessEventDelivery,
    ProcessRunner,
)

class CodexCLIAdapter(PromptCLIAdapter):
    def __init__(
        self,
        command: tuple[str, ...] = (
            "codex",
            "exec",
            "--sandbox",
            "read-only",
            "--ephemeral",
        ),
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(command, name="codex-cli", runner=runner, timeout=timeout)


class CodexHarnessAdapter(PromptCLIAdapter):
    """Codex CLI adapter with HLP harness event projection.

    Codex keeps its own execution model. This adapter only provides the HLP
    boundary: prompt-mode command execution plus projection of explicit
    human-loop events from Codex JSONL stdout.
    """

    def __init__(
        self,
        command: tuple[str, ...] = (
            "codex",
            "exec",
            "--json",
            "--sandbox",
            "read-only",
            "--ephemeral",
        ),
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
        capabilities: HarnessCapabilities | None = None,
    ) -> None:
        super().__init__(
            command,
            name="codex-harness",
            runner=runner or run_prompt_process,
            timeout=timeout,
        )
        self._capabilities = capabilities or HarnessCapabilities(
            name="codex",
            conformance=("checkpoint-capable", "artifact-aware", "event-streaming"),
            description="Projects Codex CLI JSON events into HLP human-loop objects.",
        )
        self._codex_events: dict[str, list[dict[str, Any]]] = {}
        self._codex_event_counter = 0

    def harness_capabilities(self) -> HarnessCapabilities:
        return self._capabilities

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
        request = {
            "operation": "delegate",
            "task_id": task_id,
            "agent_id": agent_id,
            "capability": capability,
            "input": input,
            "parent_run": parent_run,
            "correlation_id": task_id,
        }
        if operation_context is not None:
            request["operation_context"] = to_wire(operation_context)
        payload = await self._execute("delegate", request)
        events = parsing.pop_codex_events(payload)
        util.validate_correlation(payload, task_id, self.name, "delegate")
        run_id = str(payload.get("run_id") or parsing.codex_run_id_from_events(events) or self._next_run_id())
        self._runs[run_id] = AgentRunHandle(
            run_id=run_id,
            task_id=task_id,
            agent_id=agent_id,
            correlation_id=task_id,
            capability=capability,
            parent_run=parent_run,
        )
        self.process_results[run_id] = payload
        self._queue_codex_events(run_id, events)
        self.calls.append((
            "delegate",
            {
                "run_id": run_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "capability": capability,
                "input": input,
                "parent_run": parent_run,
                "operation_context": (
                    to_wire(operation_context)
                    if operation_context is not None
                    else None
                ),
            },
        ))
        return run_id

    async def block(
        self,
        run_id: str,
        checkpoint_id: str,
        reason: str,
        *,
        context: AdapterOperationContext | None = None,
    ) -> None:
        handle = self._require_run(run_id, "block", context=context)
        payload = await self._execute("block", {
            "operation": "block",
            "run_id": run_id,
            "checkpoint_id": checkpoint_id,
            "reason": reason,
            "correlation_id": handle.correlation_id,
            "operation_context": to_wire(context) if context is not None else None,
        })
        events = parsing.pop_codex_events(payload)
        util.validate_correlation(payload, handle.correlation_id, self.name, "block")
        self._queue_codex_events(run_id, events)
        await FakeAgentAdapter.block(self, run_id, checkpoint_id, reason, context=context)

    async def resume(
        self,
        run_id: str,
        resolution: Any,
        *,
        context: AdapterOperationContext | None = None,
    ) -> None:
        handle = self._require_run(run_id, "resume", context=context)
        payload = await self._execute("resume", {
            "operation": "resume",
            "run_id": run_id,
            "resolution": resolution,
            "correlation_id": handle.correlation_id,
            "operation_context": to_wire(context) if context is not None else None,
        })
        events = parsing.pop_codex_events(payload)
        util.validate_correlation(payload, handle.correlation_id, self.name, "resume")
        self._queue_codex_events(run_id, events)
        await FakeAgentAdapter.resume(self, run_id, resolution, context=context)

    async def handoff(
        self,
        run_id: str,
        to_agent: str,
        context: dict[str, Any],
        *,
        operation_context: AdapterOperationContext | None = None,
    ) -> str:
        current = self._require_run(run_id, "handoff", context=operation_context)
        payload = await self._execute("handoff", {
            "operation": "handoff",
            "run_id": run_id,
            "to_agent": to_agent,
            "context": context,
            "correlation_id": current.correlation_id,
            **(
                {"operation_context": to_wire(operation_context)}
                if operation_context is not None
                else {}
            ),
        })
        events = parsing.pop_codex_events(payload)
        util.validate_correlation(payload, current.correlation_id, self.name, "handoff")
        new_run_id = str(
            payload.get("run_id")
            or payload.get("to_run")
            or parsing.codex_run_id_from_events(events)
            or self._next_run_id()
        )
        self._runs[new_run_id] = AgentRunHandle(
            run_id=new_run_id,
            task_id=current.task_id,
            agent_id=to_agent,
            correlation_id=current.correlation_id,
            capability=current.capability,
            parent_run=run_id,
        )
        self.process_results[new_run_id] = payload
        self._queue_codex_events(new_run_id, events)
        self.calls.append((
            "handoff",
            {
                "from_run": run_id,
                "to_run": new_run_id,
                "to_agent": to_agent,
                "context": context,
                "operation_context": (
                    to_wire(operation_context)
                    if operation_context is not None
                    else None
                ),
            },
        ))
        return new_run_id

    async def cancel(
        self,
        run_id: str,
        reason: str,
        *,
        operation_context: AdapterOperationContext | None = None,
    ) -> None:
        handle = self._require_run(run_id, "cancel", context=operation_context)
        payload = await self._execute("cancel", {
            "operation": "cancel",
            "run_id": run_id,
            "reason": reason,
            "correlation_id": handle.correlation_id,
            **(
                {"operation_context": to_wire(operation_context)}
                if operation_context is not None
                else {}
            ),
        })
        events = parsing.pop_codex_events(payload)
        util.validate_correlation(payload, handle.correlation_id, self.name, "cancel")
        self._queue_codex_events(run_id, events)
        await FakeAgentAdapter.cancel(
            self,
            run_id,
            reason,
            operation_context=operation_context,
        )

    async def observe(self, run_id: str) -> tuple[HarnessEvent, ...]:
        deliveries = await self.peek_events(run_id)
        if deliveries:
            await self.ack_events(run_id, through=deliveries[-1].cursor)
        events = tuple(delivery.event for delivery in deliveries)
        self.calls.append((
            "observe",
            {
                "run_id": run_id,
                "events": len(events),
            },
        ))
        return events

    async def peek_events(
        self,
        run_id: str,
        *,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> tuple[HarnessEventDelivery, ...]:
        handle = self._require_run(run_id, "peek_events")
        raw_events = self._codex_events.get(run_id, [])
        start = 0
        if cursor is not None:
            for index, raw in enumerate(raw_events):
                if parsing.codex_event_id(raw) == cursor:
                    start = index + 1
                    break
            else:
                raise AgentAdapterError(
                    self.name,
                    "peek_events",
                    "unknown event cursor",
                    details={"run_id": run_id, "cursor": cursor},
                )
        projected: list[HarnessEventDelivery] = []
        for raw in raw_events[start:]:
            event = parsing.codex_event_to_harness_event(raw, handle)
            if event is None:
                continue
            projected.append(HarnessEventDelivery(
                cursor=parsing.codex_event_id(raw) or "",
                event=event,
            ))
            if limit is not None and len(projected) >= limit:
                break
        self.calls.append((
            "peek_events",
            {
                "run_id": run_id,
                "raw_events": len(raw_events[start:]),
                "events": len(projected),
            },
        ))
        return tuple(projected)

    async def ack_events(self, run_id: str, *, through: str) -> None:
        self._require_run(run_id, "ack_events")
        events = self._codex_events.get(run_id, [])
        for index, raw in enumerate(events):
            if parsing.codex_event_id(raw) == through:
                del events[:index + 1]
                if not events:
                    self._codex_events.pop(run_id, None)
                self.calls.append(("ack_events", {"run_id": run_id, "through": through}))
                return
        raise AgentAdapterError(
            self.name,
            "ack_events",
            "unknown event cursor",
            details={"run_id": run_id, "through": through},
        )

    async def _execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        prompt = cli_operation_prompt(request)
        command = (*self.command, prompt)
        try:
            result = self.runner(command, request, self.timeout)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            raise AgentAdapterError(
                self.name,
                operation,
                "process runner raised an exception",
                details={
                    "command": command,
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                },
            ) from exc
        if result.exit_code != 0:
            raise AgentAdapterError(
                self.name,
                operation,
                "process command failed",
                details={
                    "command": command,
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
            )
        if not result.stdout.strip():
            return {}
        try:
            payload, events = parsing.parse_codex_stdout(result.stdout)
            parsing.validate_codex_event_correlations(
                events,
                str(request.get("correlation_id") or ""),
                self.name,
                operation,
            )
        except ValueError as exc:
            raise AgentAdapterError(
                self.name,
                operation,
                "process stdout did not contain Codex JSON events",
                details={"stdout": result.stdout, "stderr": result.stderr},
            ) from exc
        payload[parsing.CODEX_EVENTS_KEY] = events
        return payload

    def _queue_codex_events(
        self,
        fallback_run_id: str,
        events: tuple[dict[str, Any], ...],
    ) -> None:
        for event in events:
            if not parsing.codex_event_may_project(event):
                continue
            event = dict(event)
            if parsing.codex_event_id(event) is None:
                self._codex_event_counter += 1
                event["_hlp_event_id"] = f"evt_{self._codex_event_counter:06d}"
            run_id = parsing.codex_event_run_id(event) or fallback_run_id
            self._codex_events.setdefault(run_id, []).append(event)

