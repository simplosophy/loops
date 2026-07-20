from __future__ import annotations

import atexit
import inspect
import json
import os
import tempfile
from typing import Any

from ..objects import AdapterOperationContext
from ..schema import to_wire
from . import _parsing as parsing
from . import _util as util
from .fake import FakeAgentAdapter
from .process import (
    PromptCLIAdapter,
    prompt_for_adapter_operation,
    run_prompt_process,
)
from .protocol import (
    AgentAdapterError,
    AgentRunHandle,
    HarnessCapabilities,
    HarnessEvent,
    HarnessEventDelivery,
    ProcessRunner,
)

_DEFAULT_CLI_COMMAND: tuple[str, ...] = (
    "codex",
    "exec",
    "--sandbox",
    "read-only",
    "--ephemeral",
)
_DEFAULT_HARNESS_COMMAND: tuple[str, ...] = (
    "codex",
    "exec",
    "--json",
    "--sandbox",
    "read-only",
    "--ephemeral",
)

_schema_file_path: str | None = None


def _unlink_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _hlp_result_schema_path() -> str:
    """Write the HLP result envelope schema once per process (codex --output-schema)."""
    global _schema_file_path
    if _schema_file_path is not None and os.path.exists(_schema_file_path):
        return _schema_file_path
    fd, path = tempfile.mkstemp(prefix="hlp-result-schema-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(parsing.HLP_RESULT_SCHEMA, handle)
    atexit.register(_unlink_quietly, path)
    _schema_file_path = path
    return path


class CodexCLIAdapter(PromptCLIAdapter):
    def __init__(
        self,
        command: tuple[str, ...] = _DEFAULT_CLI_COMMAND,
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
    ) -> None:
        if command is _DEFAULT_CLI_COMMAND:
            # Protocol-only adapter: enforce the result envelope natively.
            command = (*command, "--output-schema", _hlp_result_schema_path())
        super().__init__(command, name="codex-cli", runner=runner, timeout=timeout)


class CodexHarnessAdapter(PromptCLIAdapter):
    """Codex CLI adapter with HLP harness event projection.

    Codex keeps its own execution model. This adapter only provides the HLP
    boundary: prompt-mode command execution plus projection of explicit
    human-loop events from Codex JSONL stdout.
    """

    def __init__(
        self,
        command: tuple[str, ...] = _DEFAULT_HARNESS_COMMAND,
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
        capabilities: HarnessCapabilities | None = None,
        prompt_mode: str = "protocol",
        session_continuity: bool = True,
    ) -> None:
        if command is _DEFAULT_HARNESS_COMMAND:
            if session_continuity:
                # --ephemeral sessions are not recorded and cannot be resumed.
                command = tuple(part for part in command if part != "--ephemeral")
            if prompt_mode == "protocol":
                # Enforce the HLP result envelope natively; chat mode stays free-form.
                command = (*command, "--output-schema", _hlp_result_schema_path())
        super().__init__(
            command,
            name="codex-harness",
            runner=runner or run_prompt_process,
            timeout=timeout,
            prompt_mode=prompt_mode,
        )
        self._capabilities = capabilities or HarnessCapabilities(
            name="codex",
            conformance=("checkpoint-capable", "artifact-aware", "event-streaming"),
            description="Projects Codex CLI JSON events into HLP human-loop objects.",
        )
        self._codex_events: dict[str, list[dict[str, Any]]] = {}
        self._codex_event_counter = 0
        # run_id -> CLI-native session id (session-resume continuity).
        self._session_continuity = session_continuity
        self._run_sessions: dict[str, str] = {}

    def harness_capabilities(self) -> HarnessCapabilities:
        return self._capabilities

    def session_of_run(self, run_id: str) -> str | None:
        """The CLI-native session id bound to a run, when known."""
        return self._run_sessions.get(run_id)

    def _bind_session(self, run_id: str, events: tuple[dict[str, Any], ...]) -> None:
        session_id = parsing.session_id_from_events(events)
        if session_id:
            self._run_sessions[run_id] = session_id

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
        run_id = str(
            payload.get("run_id") or parsing.codex_run_id_from_events(events) or self._next_run_id()
        )
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
        self._bind_session(run_id, events)
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

    async def block(
        self,
        run_id: str,
        checkpoint_id: str,
        reason: str,
        *,
        context: AdapterOperationContext | None = None,
    ) -> None:
        handle = self._require_run(run_id, "block", context=context)
        payload = await self._execute(
            "block",
            {
                "operation": "block",
                "run_id": run_id,
                "checkpoint_id": checkpoint_id,
                "reason": reason,
                "correlation_id": handle.correlation_id,
                "operation_context": to_wire(context) if context is not None else None,
            },
        )
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
        payload = await self._execute(
            "resume",
            {
                "operation": "resume",
                "run_id": run_id,
                "resolution": resolution,
                "correlation_id": handle.correlation_id,
                "operation_context": to_wire(context) if context is not None else None,
            },
        )
        events = parsing.pop_codex_events(payload)
        util.validate_correlation(payload, handle.correlation_id, self.name, "resume")
        self._queue_codex_events(run_id, events)
        await FakeAgentAdapter.resume(self, run_id, resolution, context=context)

    async def steer(
        self,
        run_id: str,
        amendment: Any,
        *,
        context: AdapterOperationContext | None = None,
    ) -> None:
        handle = self._require_run(run_id, "steer", context=context)
        amendment_payload = util.adapter_payload(amendment)
        payload = await self._execute(
            "steer",
            {
                "operation": "steer",
                "run_id": run_id,
                "amendment": amendment_payload,
                "correlation_id": handle.correlation_id,
                "operation_context": to_wire(context) if context is not None else None,
            },
        )
        events = parsing.pop_codex_events(payload)
        util.validate_correlation(payload, handle.correlation_id, self.name, "steer")
        self.process_results[run_id] = payload
        self._queue_codex_events(run_id, events)
        await FakeAgentAdapter.steer(self, run_id, amendment_payload, context=context)

    async def handoff(
        self,
        run_id: str,
        to_agent: str,
        context: dict[str, Any],
        *,
        operation_context: AdapterOperationContext | None = None,
    ) -> str:
        current = self._require_run(run_id, "handoff", context=operation_context)
        payload = await self._execute(
            "handoff",
            {
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
            },
        )
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
        self._bind_session(new_run_id, events)
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

    async def cancel(
        self,
        run_id: str,
        reason: str,
        *,
        operation_context: AdapterOperationContext | None = None,
    ) -> None:
        handle = self._require_run(run_id, "cancel", context=operation_context)
        payload = await self._execute(
            "cancel",
            {
                "operation": "cancel",
                "run_id": run_id,
                "reason": reason,
                "correlation_id": handle.correlation_id,
                **(
                    {"operation_context": to_wire(operation_context)}
                    if operation_context is not None
                    else {}
                ),
            },
        )
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
        self.calls.append(
            (
                "observe",
                {
                    "run_id": run_id,
                    "events": len(events),
                },
            )
        )
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
            projected.append(
                HarnessEventDelivery(
                    cursor=parsing.codex_event_id(raw) or "",
                    event=event,
                )
            )
            if limit is not None and len(projected) >= limit:
                break
        self.calls.append(
            (
                "peek_events",
                {
                    "run_id": run_id,
                    "raw_events": len(raw_events[start:]),
                    "events": len(projected),
                },
            )
        )
        return tuple(projected)

    async def ack_events(self, run_id: str, *, through: str) -> None:
        self._require_run(run_id, "ack_events")
        events = self._codex_events.get(run_id, [])
        for index, raw in enumerate(events):
            if parsing.codex_event_id(raw) == through:
                del events[: index + 1]
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
        prompt = prompt_for_adapter_operation(request, mode=self.prompt_mode)
        command = self._command_for_prompt(operation, request, prompt)
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
        # Schema-less CLIs may omit the echo; the adapter binds correlation locally.
        # Present-but-different values were already rejected above.
        expected_correlation = str(request.get("correlation_id") or "")
        if expected_correlation and "correlation_id" not in payload:
            payload["correlation_id"] = expected_correlation
        payload[parsing.CODEX_EVENTS_KEY] = events
        return payload

    _RESUME_OPS = frozenset({"block", "resume", "steer", "cancel"})

    def _command_for_prompt(
        self,
        operation: str,
        request: dict[str, Any],
        prompt: str,
    ) -> tuple[str, ...]:
        """One-shot command, or the CLI's session-resume command for follow-up ops.

        Continuity means "a new turn in the same native session" — the strongest
        form these CLIs offer today, not frozen-process resumption.
        """
        if self._session_continuity and operation in self._RESUME_OPS:
            session_id = self._run_sessions.get(str(request.get("run_id") or ""))
            if session_id:
                return self._resume_command(session_id, prompt)
        return (*self.command, prompt)

    def _resume_command(self, session_id: str, prompt: str) -> tuple[str, ...]:
        """codex exec resume [options] <thread_id> [prompt] (options come first)."""
        command: tuple[str, ...] = ("codex", "exec", "resume")
        if "--json" in self.command:
            command = (*command, "--json")
        if "--output-schema" in self.command:
            index = self.command.index("--output-schema")
            command = (*command, "--output-schema", self.command[index + 1])
        return (*command, session_id, prompt)

    def _queue_codex_events(
        self,
        fallback_run_id: str,
        events: tuple[dict[str, Any], ...],
    ) -> None:
        seen_signatures: set[str] = set()
        for event in events:
            if not parsing.codex_event_may_project(event):
                continue
            # Drop transport-level duplicates within one batch (e.g. Claude
            # Code's result envelope repeats the final assistant text).
            signature = parsing.codex_event_signature(event)
            if signature is not None:
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
            event = dict(event)
            if parsing.codex_event_id(event) is None:
                self._codex_event_counter += 1
                event["_hlp_event_id"] = f"evt_{self._codex_event_counter:06d}"
            run_id = parsing.codex_event_run_id(event) or fallback_run_id
            self._codex_events.setdefault(run_id, []).append(event)
