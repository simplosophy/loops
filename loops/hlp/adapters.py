from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from .types import HarnessConformance, HarnessEventKind


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

_CODEX_EVENTS_KEY = "_codex_events"


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
    ) -> str:
        """Delegate a task to an agent and return the runtime run id."""
        ...

    async def block(self, run_id: str, checkpoint_id: str, reason: str) -> None:
        """Block a run until the HLP checkpoint is resolved."""
        ...

    async def resume(self, run_id: str, resolution: Any) -> None:
        """Resume a blocked run with the human resolution payload."""
        ...

    async def handoff(self, run_id: str, to_agent: str, context: dict[str, Any]) -> str:
        """Handoff a run to another agent while preserving task correlation."""
        ...

    async def cancel(self, run_id: str, reason: str) -> None:
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


@dataclass
class FakeAgentAdapter:
    """Deterministic adapter for tests and demos.

    It records contract calls, creates stable run ids, and never reaches network
    or a local agent binary.
    """

    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    _run_counter: int = field(default=0, repr=False)
    _runs: dict[str, AgentRunHandle] = field(default_factory=dict, repr=False)

    async def delegate(
        self,
        task_id: str,
        agent_id: str,
        capability: str,
        input: dict[str, Any],
        parent_run: str | None = None,
    ) -> str:
        self._run_counter += 1
        run_id = f"run_{self._run_counter:06d}"
        self._runs[run_id] = AgentRunHandle(
            run_id=run_id,
            task_id=task_id,
            agent_id=agent_id,
            correlation_id=task_id,
            capability=capability,
            parent_run=parent_run,
        )
        self.calls.append((
            "delegate",
            {
                "run_id": run_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "capability": capability,
                "input": input,
                "parent_run": parent_run,
            },
        ))
        return run_id

    async def block(self, run_id: str, checkpoint_id: str, reason: str) -> None:
        self._require_run(run_id, "block")
        self.calls.append((
            "block",
            {"run_id": run_id, "checkpoint_id": checkpoint_id, "reason": reason},
        ))

    async def resume(self, run_id: str, resolution: Any) -> None:
        self._require_run(run_id, "resume")
        self.calls.append((
            "resume",
            {"run_id": run_id, "resolution": resolution},
        ))

    async def handoff(self, run_id: str, to_agent: str, context: dict[str, Any]) -> str:
        current = self._require_run(run_id, "handoff")
        self._run_counter += 1
        new_run_id = f"run_{self._run_counter:06d}"
        self._runs[new_run_id] = AgentRunHandle(
            run_id=new_run_id,
            task_id=current.task_id,
            agent_id=to_agent,
            correlation_id=current.correlation_id,
            capability=current.capability,
            parent_run=run_id,
        )
        self.calls.append((
            "handoff",
            {
                "from_run": run_id,
                "to_run": new_run_id,
                "to_agent": to_agent,
                "context": context,
            },
        ))
        return new_run_id

    async def cancel(self, run_id: str, reason: str) -> None:
        self._require_run(run_id, "cancel")
        self.calls.append((
            "cancel",
            {"run_id": run_id, "reason": reason},
        ))

    async def healthcheck(self) -> dict[str, Any]:
        result = {"status": "ok", "adapter": "fake", "runs": len(self._runs)}
        self.calls.append(("healthcheck", result))
        return result

    def run_handle(self, run_id: str) -> AgentRunHandle | None:
        return self._runs.get(run_id)

    def task_of_run(self, run_id: str) -> str | None:
        handle = self._runs.get(run_id)
        return handle.task_id if handle is not None else None

    def calls_of(self, method: str) -> list[tuple[str, dict[str, Any]]]:
        return [call for call in self.calls if call[0] == method]

    def _require_run(self, run_id: str, operation: str) -> AgentRunHandle:
        handle = self._runs.get(run_id)
        if handle is None:
            raise AgentAdapterError(
                self.__class__.__name__,
                operation,
                "unknown run id",
                details={"run_id": run_id},
            )
        return handle


class FakeHarnessAdapter(FakeAgentAdapter):
    """Deterministic harness adapter for tests and demos."""

    def __init__(
        self,
        *,
        capabilities: HarnessCapabilities | None = None,
    ) -> None:
        super().__init__()
        self._capabilities = capabilities or HarnessCapabilities(name="fake-harness")
        self._events: dict[str, list[HarnessEvent]] = {}

    def harness_capabilities(self) -> HarnessCapabilities:
        return self._capabilities

    def queue_event(self, run_id: str, event: HarnessEvent) -> None:
        self._require_run(run_id, "queue_event")
        self._events.setdefault(run_id, []).append(event)

    async def observe(self, run_id: str) -> tuple[HarnessEvent, ...]:
        self._require_run(run_id, "observe")
        events = tuple(self._events.pop(run_id, ()))
        self.calls.append(("observe", {"run_id": run_id, "events": len(events)}))
        return events


class ProcessAgentAdapter(FakeAgentAdapter):
    """Generic JSON-over-stdin/stdout adapter for CLI agents."""

    def __init__(
        self,
        command: tuple[str, ...],
        *,
        name: str = "process",
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__()
        self.command = command
        self.name = name
        self.runner = runner or _run_json_process
        self.timeout = timeout
        self.process_results: dict[str, dict[str, Any]] = {}

    async def delegate(
        self,
        task_id: str,
        agent_id: str,
        capability: str,
        input: dict[str, Any],
        parent_run: str | None = None,
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
        payload = await self._execute("delegate", request)
        _validate_correlation(payload, task_id, self.name, "delegate")
        run_id = str(payload.get("run_id") or self._next_run_id())
        self._runs[run_id] = AgentRunHandle(
            run_id=run_id,
            task_id=task_id,
            agent_id=agent_id,
            correlation_id=task_id,
            capability=capability,
            parent_run=parent_run,
        )
        self.process_results[run_id] = payload
        self.calls.append((
            "delegate",
            {
                "run_id": run_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "capability": capability,
                "input": input,
                "parent_run": parent_run,
            },
        ))
        return run_id

    async def block(self, run_id: str, checkpoint_id: str, reason: str) -> None:
        handle = self._require_run(run_id, "block")
        await self._execute("block", {
            "operation": "block",
            "run_id": run_id,
            "checkpoint_id": checkpoint_id,
            "reason": reason,
            "correlation_id": handle.correlation_id,
        })
        await FakeAgentAdapter.block(self, run_id, checkpoint_id, reason)

    async def resume(self, run_id: str, resolution: Any) -> None:
        handle = self._require_run(run_id, "resume")
        await self._execute("resume", {
            "operation": "resume",
            "run_id": run_id,
            "resolution": resolution,
            "correlation_id": handle.correlation_id,
        })
        await FakeAgentAdapter.resume(self, run_id, resolution)

    async def handoff(self, run_id: str, to_agent: str, context: dict[str, Any]) -> str:
        current = self._require_run(run_id, "handoff")
        payload = await self._execute("handoff", {
            "operation": "handoff",
            "run_id": run_id,
            "to_agent": to_agent,
            "context": context,
            "correlation_id": current.correlation_id,
        })
        _validate_correlation(payload, current.correlation_id, self.name, "handoff")
        new_run_id = str(payload.get("run_id") or payload.get("to_run") or self._next_run_id())
        self._runs[new_run_id] = AgentRunHandle(
            run_id=new_run_id,
            task_id=current.task_id,
            agent_id=to_agent,
            correlation_id=current.correlation_id,
            capability=current.capability,
            parent_run=run_id,
        )
        self.process_results[new_run_id] = payload
        self.calls.append((
            "handoff",
            {
                "from_run": run_id,
                "to_run": new_run_id,
                "to_agent": to_agent,
                "context": context,
            },
        ))
        return new_run_id

    async def cancel(self, run_id: str, reason: str) -> None:
        handle = self._require_run(run_id, "cancel")
        await self._execute("cancel", {
            "operation": "cancel",
            "run_id": run_id,
            "reason": reason,
            "correlation_id": handle.correlation_id,
        })
        await FakeAgentAdapter.cancel(self, run_id, reason)

    async def healthcheck(self) -> dict[str, Any]:
        result = {
            "status": "ok",
            "adapter": self.name,
            "runs": len(self._runs),
            "command": self.command,
            "executable": self.command[0] if self.command else "",
            "timeout": self.timeout,
        }
        self.calls.append(("healthcheck", result))
        return result

    async def _execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self.runner(self.command, request, self.timeout)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            raise AgentAdapterError(
                self.name,
                operation,
                "process runner raised an exception",
                details={
                    "command": self.command,
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
                    "command": self.command,
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                },
            )
        if not result.stdout.strip():
            return {}
        try:
            payload = _parse_process_stdout(result.stdout)
        except ValueError as exc:
            raise AgentAdapterError(
                self.name,
                operation,
                "process stdout was not valid JSON",
                details={"stdout": result.stdout, "stderr": result.stderr},
            ) from exc
        if not isinstance(payload, dict):
            raise AgentAdapterError(
                self.name,
                operation,
                "process stdout JSON must be an object",
                details={"stdout": result.stdout},
            )
        return payload

    def _next_run_id(self) -> str:
        self._run_counter += 1
        return f"run_{self._run_counter:06d}"


class PromptCLIAdapter(ProcessAgentAdapter):
    """One-shot prompt adapter for local agent CLIs.

    Codex, Kimi, and Claude Code expose non-interactive prompt modes rather
    than HLP's generic JSON-over-stdin process contract. This adapter keeps the
    HLP boundary structured by embedding the operation request in the prompt and
    requiring the CLI to print a JSON result that carries the correlation id.
    """

    def __init__(
        self,
        command: tuple[str, ...],
        *,
        name: str = "prompt-cli",
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(
            command,
            name=name,
            runner=runner or _run_prompt_process,
            timeout=timeout,
        )

    async def _execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        prompt = _cli_operation_prompt(request)
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
            payload = _parse_cli_stdout(result.stdout)
        except ValueError as exc:
            raise AgentAdapterError(
                self.name,
                operation,
                "process stdout did not contain a JSON object",
                details={"stdout": result.stdout, "stderr": result.stderr},
            ) from exc
        if not isinstance(payload, dict):
            raise AgentAdapterError(
                self.name,
                operation,
                "process stdout JSON must be an object",
                details={"stdout": result.stdout},
            )
        return payload

    async def healthcheck(self) -> dict[str, Any]:
        result = await super().healthcheck()
        result["prompt_mode"] = True
        return result


InMemoryAgentAdapter = FakeAgentAdapter


class PythonCallableAgentAdapter(FakeAgentAdapter):
    """Adapter for in-process Python agent frameworks.

    The handler can wrap OpenAI Agents SDK, OpenAI Python SDK, LangGraph, CrewAI,
    or any framework that can be invoked as a Python callable.
    """

    def __init__(
        self,
        name: str,
        handler: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        super().__init__()
        self.name = name
        self.handler = handler
        self.results: dict[str, Any] = {}

    async def delegate(
        self,
        task_id: str,
        agent_id: str,
        capability: str,
        input: dict[str, Any],
        parent_run: str | None = None,
    ) -> str:
        self._run_counter += 1
        run_id = f"run_{self._run_counter:06d}"
        if self.handler is not None:
            request = {
                "run_id": run_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "capability": capability,
                "input": input,
                "parent_run": parent_run,
            }
            try:
                result = self.handler(request)
                if inspect.isawaitable(result):
                    result = await result
            except Exception as exc:
                raise AgentAdapterError(
                    self.name,
                    "delegate",
                    "Python callable handler failed",
                    details={
                        "error_type": exc.__class__.__name__,
                        "error": str(exc),
                    },
                ) from exc
            self.results[run_id] = result
        self._runs[run_id] = AgentRunHandle(
            run_id=run_id,
            task_id=task_id,
            agent_id=agent_id,
            correlation_id=task_id,
            capability=capability,
            parent_run=parent_run,
        )
        self.calls.append((
            "delegate",
            {
                "run_id": run_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "capability": capability,
                "input": input,
                "parent_run": parent_run,
            },
        ))
        return run_id

    async def healthcheck(self) -> dict[str, Any]:
        result = {
            "status": "ok",
            "adapter": self.name,
            "runs": len(self._runs),
            "callable": self.handler is not None,
        }
        self.calls.append(("healthcheck", result))
        return result

    def _record_framework_result(
        self,
        result: Any,
        *,
        fallback_prefix: str,
        task_id: str,
        agent_id: str,
        capability: str,
        input: dict[str, Any],
        parent_run: str | None,
    ) -> str:
        payload = _response_to_dict(result)
        _validate_correlation(payload, task_id, self.name, "delegate")
        run_id = str(
            payload.get("id")
            or payload.get("run_id")
            or self._next_framework_run_id(fallback_prefix)
        )
        self._runs[run_id] = AgentRunHandle(
            run_id=run_id,
            task_id=task_id,
            agent_id=agent_id,
            correlation_id=task_id,
            capability=capability,
            parent_run=parent_run,
        )
        self.results[run_id] = payload
        self.calls.append((
            "delegate",
            {
                "run_id": run_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "capability": capability,
                "input": input,
                "parent_run": parent_run,
            },
        ))
        return run_id

    def _next_framework_run_id(self, prefix: str) -> str:
        self._run_counter += 1
        return f"{prefix}_{self._run_counter:06d}"


class OpenAIAgentsSDKAdapter(PythonCallableAgentAdapter):
    def __init__(
        self,
        handler: Callable[[dict[str, Any]], Any] | None = None,
        *,
        agent: Any = None,
        runner: Any = None,
        run_config: Any = None,
    ) -> None:
        super().__init__("openai-agents-sdk", handler)
        self.agent = agent
        self.runner = runner
        self.run_config = run_config

    async def delegate(
        self,
        task_id: str,
        agent_id: str,
        capability: str,
        input: dict[str, Any],
        parent_run: str | None = None,
    ) -> str:
        if self.agent is None or self.runner is None:
            return await super().delegate(
                task_id=task_id,
                agent_id=agent_id,
                capability=capability,
                input=input,
                parent_run=parent_run,
            )
        try:
            if hasattr(self.runner, "run"):
                result = self.runner.run(
                    self.agent,
                    _prompt_from_input(input),
                    run_config=self.run_config,
                )
            else:
                result = self.runner.run_sync(
                    self.agent,
                    _prompt_from_input(input),
                    run_config=self.run_config,
                )
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            raise AgentAdapterError(
                self.name,
                "delegate",
                "OpenAI Agents SDK runner failed",
                details={
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                },
            ) from exc
        return self._record_framework_result(
            result,
            fallback_prefix="agents_run",
            task_id=task_id,
            agent_id=agent_id,
            capability=capability,
            input=input,
            parent_run=parent_run,
        )


class OpenAIPythonSDKAdapter(PythonCallableAgentAdapter):
    def __init__(
        self,
        handler: Callable[[dict[str, Any]], Any] | None = None,
        *,
        client: Any = None,
        model: str = "gpt-4.1",
    ) -> None:
        super().__init__("openai-python-sdk", handler)
        self.client = client
        self.model = model

    async def delegate(
        self,
        task_id: str,
        agent_id: str,
        capability: str,
        input: dict[str, Any],
        parent_run: str | None = None,
    ) -> str:
        if self.client is None:
            return await super().delegate(
                task_id=task_id,
                agent_id=agent_id,
                capability=capability,
                input=input,
                parent_run=parent_run,
            )
        try:
            response = self.client.responses.create(
                model=self.model,
                input=_prompt_from_input(input),
                metadata={
                    "hlp_task_id": task_id,
                    "hlp_agent_id": agent_id,
                    "hlp_capability": capability,
                    "hlp_parent_run": parent_run or "",
                },
            )
            if inspect.isawaitable(response):
                response = await response
        except Exception as exc:
            raise AgentAdapterError(
                self.name,
                "delegate",
                "OpenAI client request failed",
                details={
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                },
            ) from exc
        result = _response_to_dict(response)
        _validate_correlation(result, task_id, self.name, "delegate")
        run_id = str(result.get("id") or self._next_response_run_id())
        self._runs[run_id] = AgentRunHandle(
            run_id=run_id,
            task_id=task_id,
            agent_id=agent_id,
            correlation_id=task_id,
            capability=capability,
            parent_run=parent_run,
        )
        self.results[run_id] = result
        self.calls.append((
            "delegate",
            {
                "run_id": run_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "capability": capability,
                "input": input,
                "parent_run": parent_run,
            },
        ))
        return run_id

    def _next_response_run_id(self) -> str:
        self._run_counter += 1
        return f"openai_run_{self._run_counter:06d}"


class LangGraphAdapter(PythonCallableAgentAdapter):
    def __init__(
        self,
        handler: Callable[[dict[str, Any]], Any] | None = None,
        *,
        graph: Any = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        super().__init__("langgraph", handler)
        self.graph = graph
        self.config = config or {}

    async def delegate(
        self,
        task_id: str,
        agent_id: str,
        capability: str,
        input: dict[str, Any],
        parent_run: str | None = None,
    ) -> str:
        if self.graph is None:
            return await super().delegate(
                task_id=task_id,
                agent_id=agent_id,
                capability=capability,
                input=input,
                parent_run=parent_run,
            )
        graph_input = {
            "messages": [{"role": "user", "content": _prompt_from_input(input)}],
            "hlp": _hlp_payload(task_id, agent_id, capability, parent_run),
        }
        if isinstance(input.get("state"), dict):
            graph_input["state"] = input["state"]
        config = _normalize_langgraph_config(self.config)
        config["metadata"] = {
            **dict(config.get("metadata", {})),
            **_hlp_metadata(task_id, agent_id, capability, parent_run),
        }
        try:
            if hasattr(self.graph, "ainvoke"):
                result = self.graph.ainvoke(graph_input, config=config)
            else:
                result = self.graph.invoke(graph_input, config=config)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            raise AgentAdapterError(
                self.name,
                "delegate",
                "LangGraph invocation failed",
                details={
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                },
            ) from exc
        return self._record_framework_result(
            result,
            fallback_prefix="langgraph_run",
            task_id=task_id,
            agent_id=agent_id,
            capability=capability,
            input=input,
            parent_run=parent_run,
        )


class CrewAIAdapter(PythonCallableAgentAdapter):
    def __init__(
        self,
        handler: Callable[[dict[str, Any]], Any] | None = None,
        *,
        crew: Any = None,
    ) -> None:
        super().__init__("crewai", handler)
        self.crew = crew

    async def delegate(
        self,
        task_id: str,
        agent_id: str,
        capability: str,
        input: dict[str, Any],
        parent_run: str | None = None,
    ) -> str:
        if self.crew is None:
            return await super().delegate(
                task_id=task_id,
                agent_id=agent_id,
                capability=capability,
                input=input,
                parent_run=parent_run,
            )
        crew_inputs = {
            **input,
            **_hlp_metadata(task_id, agent_id, capability, parent_run),
        }
        try:
            if hasattr(self.crew, "akickoff"):
                result = self.crew.akickoff(inputs=crew_inputs)
            elif hasattr(self.crew, "kickoff_async"):
                result = self.crew.kickoff_async(inputs=crew_inputs)
            else:
                result = self.crew.kickoff(inputs=crew_inputs)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            raise AgentAdapterError(
                self.name,
                "delegate",
                "CrewAI kickoff failed",
                details={
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                },
            ) from exc
        return self._record_framework_result(
            result,
            fallback_prefix="crewai_run",
            task_id=task_id,
            agent_id=agent_id,
            capability=capability,
            input=input,
            parent_run=parent_run,
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
            runner=runner or _run_prompt_process,
            timeout=timeout,
        )
        self._capabilities = capabilities or HarnessCapabilities(
            name="codex",
            conformance=("checkpoint-capable", "artifact-aware", "event-streaming"),
            description="Projects Codex CLI JSON events into HLP human-loop objects.",
        )
        self._codex_events: dict[str, list[dict[str, Any]]] = {}

    def harness_capabilities(self) -> HarnessCapabilities:
        return self._capabilities

    async def delegate(
        self,
        task_id: str,
        agent_id: str,
        capability: str,
        input: dict[str, Any],
        parent_run: str | None = None,
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
        payload = await self._execute("delegate", request)
        events = _pop_codex_events(payload)
        _validate_correlation(payload, task_id, self.name, "delegate")
        run_id = str(payload.get("run_id") or _codex_run_id_from_events(events) or self._next_run_id())
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
            },
        ))
        return run_id

    async def block(self, run_id: str, checkpoint_id: str, reason: str) -> None:
        handle = self._require_run(run_id, "block")
        payload = await self._execute("block", {
            "operation": "block",
            "run_id": run_id,
            "checkpoint_id": checkpoint_id,
            "reason": reason,
            "correlation_id": handle.correlation_id,
        })
        events = _pop_codex_events(payload)
        _validate_correlation(payload, handle.correlation_id, self.name, "block")
        self._queue_codex_events(run_id, events)
        await FakeAgentAdapter.block(self, run_id, checkpoint_id, reason)

    async def resume(self, run_id: str, resolution: Any) -> None:
        handle = self._require_run(run_id, "resume")
        payload = await self._execute("resume", {
            "operation": "resume",
            "run_id": run_id,
            "resolution": resolution,
            "correlation_id": handle.correlation_id,
        })
        events = _pop_codex_events(payload)
        _validate_correlation(payload, handle.correlation_id, self.name, "resume")
        self._queue_codex_events(run_id, events)
        await FakeAgentAdapter.resume(self, run_id, resolution)

    async def handoff(self, run_id: str, to_agent: str, context: dict[str, Any]) -> str:
        current = self._require_run(run_id, "handoff")
        payload = await self._execute("handoff", {
            "operation": "handoff",
            "run_id": run_id,
            "to_agent": to_agent,
            "context": context,
            "correlation_id": current.correlation_id,
        })
        events = _pop_codex_events(payload)
        _validate_correlation(payload, current.correlation_id, self.name, "handoff")
        new_run_id = str(
            payload.get("run_id")
            or payload.get("to_run")
            or _codex_run_id_from_events(events)
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
            },
        ))
        return new_run_id

    async def cancel(self, run_id: str, reason: str) -> None:
        handle = self._require_run(run_id, "cancel")
        payload = await self._execute("cancel", {
            "operation": "cancel",
            "run_id": run_id,
            "reason": reason,
            "correlation_id": handle.correlation_id,
        })
        events = _pop_codex_events(payload)
        _validate_correlation(payload, handle.correlation_id, self.name, "cancel")
        self._queue_codex_events(run_id, events)
        await FakeAgentAdapter.cancel(self, run_id, reason)

    async def observe(self, run_id: str) -> tuple[HarnessEvent, ...]:
        handle = self._require_run(run_id, "observe")
        raw_events = tuple(self._codex_events.pop(run_id, ()))
        projected = tuple(
            event
            for raw in raw_events
            if (event := _codex_event_to_harness_event(raw, handle)) is not None
        )
        self.calls.append((
            "observe",
            {
                "run_id": run_id,
                "raw_events": len(raw_events),
                "events": len(projected),
            },
        ))
        return projected

    async def _execute(self, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        prompt = _cli_operation_prompt(request)
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
            payload, events = _parse_codex_stdout(result.stdout)
            _validate_codex_event_correlations(
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
        payload[_CODEX_EVENTS_KEY] = events
        return payload

    def _queue_codex_events(
        self,
        fallback_run_id: str,
        events: tuple[dict[str, Any], ...],
    ) -> None:
        for event in events:
            run_id = _codex_event_run_id(event) or fallback_run_id
            self._codex_events.setdefault(run_id, []).append(event)


class ClaudeCodeCLIAdapter(PromptCLIAdapter):
    def __init__(
        self,
        command: tuple[str, ...] = (
            "claude",
            "-p",
            "--output-format",
            "json",
            "--permission-mode",
            "dontAsk",
        ),
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(command, name="claude-code-cli", runner=runner, timeout=timeout)


class KimiCLIAdapter(PromptCLIAdapter):
    def __init__(
        self,
        command: tuple[str, ...] = ("kimi", "--output-format", "text", "-p"),
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(command, name="kimi-cli", runner=runner, timeout=timeout)


class HermsCLIAdapter(ProcessAgentAdapter):
    def __init__(
        self,
        command: tuple[str, ...] = ("herms", "run"),
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(command, name="herms-cli", runner=runner, timeout=timeout)


HermesCLIAdapter = HermsCLIAdapter


async def _run_json_process(
    command: tuple[str, ...],
    request: dict[str, Any],
    timeout: float,
) -> ProcessResult:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    payload = json.dumps(request, sort_keys=True).encode()
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(payload),
            timeout=timeout,
        )
    except TimeoutError:
        process.kill()
        stdout, stderr = await process.communicate()
        return ProcessResult(
            exit_code=124,
            stdout=stdout.decode(errors="replace"),
            stderr=(stderr.decode(errors="replace") + "\nprocess timed out").strip(),
        )
    return ProcessResult(
        exit_code=process.returncode or 0,
        stdout=stdout.decode(errors="replace"),
        stderr=stderr.decode(errors="replace"),
    )


async def _run_prompt_process(
    command: tuple[str, ...],
    request: dict[str, Any],
    timeout: float,
) -> ProcessResult:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout,
        )
    except TimeoutError:
        process.kill()
        stdout, stderr = await process.communicate()
        return ProcessResult(
            exit_code=124,
            stdout=stdout.decode(errors="replace"),
            stderr=(stderr.decode(errors="replace") + "\nprocess timed out").strip(),
        )
    return ProcessResult(
        exit_code=process.returncode or 0,
        stdout=stdout.decode(errors="replace"),
        stderr=stderr.decode(errors="replace"),
    )


def _cli_operation_prompt(request: dict[str, Any]) -> str:
    return (
        "You are executing an HLP adapter operation.\n"
        "Return exactly one JSON object and no markdown. The JSON object must "
        "include correlation_id exactly as provided. For delegate, include a "
        "stable run_id string, status, and a short summary.\n\n"
        "HLP request:\n"
        f"{json.dumps(request, indent=2, sort_keys=True)}"
    )


def _prompt_from_input(input: dict[str, Any]) -> str:
    goal = input.get("goal")
    if goal is not None and set(input) == {"goal"}:
        return str(goal)
    return json.dumps(input, sort_keys=True)


def _parse_process_stdout(stdout: str) -> dict[str, Any]:
    stripped = stdout.strip()
    if not stripped:
        return {}
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        events: list[dict[str, Any]] = []
        for line in stripped.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("stdout line was not valid JSON") from exc
            if not isinstance(event, dict):
                raise ValueError("stdout JSONL lines must be objects")
            events.append(event)
        if not events:
            return {}
        for event in reversed(events):
            if "run_id" in event:
                return event
        return events[-1]
    if not isinstance(payload, dict):
        raise ValueError("stdout JSON must be an object")
    return payload


def _parse_cli_stdout(stdout: str) -> dict[str, Any]:
    stripped = stdout.strip()
    if not stripped:
        return {}
    try:
        parsed = _parse_process_stdout(stripped)
    except ValueError:
        parsed = None
    payload = _extract_hlp_json_payload(parsed)
    if payload is not None:
        return payload
    payload = _extract_hlp_json_payload(stripped)
    if payload is not None:
        return payload
    raise ValueError("stdout did not contain JSON object")


def _extract_hlp_json_payload(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        for key in ("result", "output_text", "final_output", "raw", "message", "text", "content"):
            nested = _extract_hlp_json_payload(value.get(key))
            if nested is not None:
                return nested
        item = value.get("item")
        if isinstance(item, dict):
            nested = _extract_hlp_json_payload(item)
            if nested is not None:
                return nested
        if _looks_like_hlp_payload(value):
            return value
        return None
    if isinstance(value, list):
        for item in reversed(value):
            nested = _extract_hlp_json_payload(item)
            if nested is not None:
                return nested
        return None
    if isinstance(value, str):
        return _extract_last_json_object(value)
    return None


def _looks_like_hlp_payload(value: dict[str, Any]) -> bool:
    return any(key in value for key in ("run_id", "correlation_id", "status", "summary"))


def _extract_last_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            nested = _extract_hlp_json_payload(value)
            candidates.append(nested or value)
    for candidate in reversed(candidates):
        if _looks_like_hlp_payload(candidate):
            return candidate
    return candidates[-1] if candidates else None


def _parse_codex_stdout(stdout: str) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    events: list[dict[str, Any]] = []
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            if line.startswith(("{", "[")):
                raise ValueError("Codex JSON event line was invalid") from exc
            continue
        if not isinstance(event, dict):
            raise ValueError("Codex JSONL events must be objects")
        events.append(event)

    if not events:
        payload = _parse_cli_stdout(stdout)
        events = [payload]

    payload = _codex_result_payload(tuple(events))
    return payload, tuple(events)


def _codex_result_payload(events: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    for event in reversed(events):
        if "run_id" in event:
            return dict(event)
        payload = _extract_hlp_json_payload(event)
        if payload is not None and ("run_id" in payload or "correlation_id" in payload):
            return dict(payload)
    return dict(events[-1]) if events else {}


def _pop_codex_events(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    raw_events = payload.pop(_CODEX_EVENTS_KEY, ())
    if isinstance(raw_events, tuple):
        return tuple(event for event in raw_events if isinstance(event, dict))
    if isinstance(raw_events, list):
        return tuple(event for event in raw_events if isinstance(event, dict))
    return ()


def _codex_run_id_from_events(events: tuple[dict[str, Any], ...]) -> str | None:
    for event in reversed(events):
        run_id = _codex_event_run_id(event)
        if run_id is not None:
            return run_id
    return None


def _codex_event_run_id(event: dict[str, Any]) -> str | None:
    payload = _codex_hlp_payload(event)
    for value in (
        event.get("run_id"),
        event.get("id") if str(event.get("type", "")).endswith("run") else None,
        payload.get("run_id") if payload is not None else None,
    ):
        if value:
            return str(value)
    return None


def _validate_codex_event_correlations(
    events: tuple[dict[str, Any], ...],
    expected: str,
    adapter: str,
    operation: str,
) -> None:
    if not expected:
        return
    for event in events:
        actual = _codex_event_correlation(event)
        if actual is not None and actual != expected:
            raise AgentAdapterError(
                adapter,
                operation,
                "runtime returned mismatched correlation_id",
                details={"expected": expected, "actual": actual},
            )


def _codex_event_correlation(event: dict[str, Any]) -> str | None:
    payload = _codex_hlp_payload(event)
    for value in (
        event.get("correlation_id"),
        event.get("hlp_task_id"),
        payload.get("correlation_id") if payload is not None else None,
        payload.get("task_id") if payload is not None else None,
        payload.get("hlp_task_id") if payload is not None else None,
    ):
        if value:
            return str(value)
    return None


def _codex_event_to_harness_event(
    event: dict[str, Any],
    handle: AgentRunHandle,
) -> HarnessEvent | None:
    payload = _codex_hlp_payload(event)
    if payload is not None:
        kind = _normalize_codex_hlp_kind(payload.get("kind") or event.get("kind") or event.get("type"))
        if kind is None:
            return None
        return HarnessEvent(
            kind=kind,
            task_id=str(
                payload.get("task_id")
                or event.get("correlation_id")
                or handle.task_id
            ),
            run_id=str(payload.get("run_id") or event.get("run_id") or handle.run_id),
            agent_id=str(payload.get("agent_id") or event.get("agent_id") or handle.agent_id),
            prompt=str(payload.get("prompt") or event.get("message") or ""),
            options=_tuple_value(payload.get("options")),
            context=_tuple_value(payload.get("context")),
            artifact_type=str(payload.get("artifact_type") or payload.get("type") or "artifact"),
            artifact_uri=str(payload.get("artifact_uri") or payload.get("uri") or ""),
            artifact_checksum=str(payload.get("artifact_checksum") or payload.get("checksum") or ""),
            artifact_size=_int_value(payload.get("artifact_size") or payload.get("size")),
        )

    artifact_uri = (
        event.get("artifact_uri")
        or event.get("patch_uri")
        or event.get("diff_uri")
    )
    if artifact_uri:
        return HarnessEvent(
            kind="artifact",
            task_id=str(event.get("correlation_id") or handle.task_id),
            run_id=str(event.get("run_id") or handle.run_id),
            agent_id=str(event.get("agent_id") or handle.agent_id),
            artifact_type=str(event.get("artifact_type") or "artifact"),
            artifact_uri=str(artifact_uri),
            artifact_checksum=str(event.get("artifact_checksum") or event.get("checksum") or ""),
            artifact_size=_int_value(event.get("artifact_size") or event.get("size")),
        )
    return None


def _codex_hlp_payload(event: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("hlp", "human_loop", "humanLoop"):
        payload = event.get(key)
        if isinstance(payload, dict):
            return payload
    nested = _extract_hlp_json_payload(event)
    if nested is not None and nested is not event:
        for key in ("hlp", "human_loop", "humanLoop"):
            payload = nested.get(key)
            if isinstance(payload, dict):
                merged = dict(payload)
                for metadata_key in (
                    "task_id",
                    "correlation_id",
                    "hlp_task_id",
                    "run_id",
                    "agent_id",
                ):
                    if metadata_key in nested and metadata_key not in merged:
                        merged[metadata_key] = nested[metadata_key]
                return merged
        return nested
    event_type = str(event.get("type") or "")
    if event_type.startswith("hlp.") or event_type in {
        "needs_approval",
        "needs_choice",
        "needs_input",
        "artifact",
    }:
        return event
    return None


def _normalize_codex_hlp_kind(value: Any) -> HarnessEventKind | None:
    aliases = {
        "approval": "needs_approval",
        "approval_required": "needs_approval",
        "needs_approval": "needs_approval",
        "choice": "needs_choice",
        "choice_required": "needs_choice",
        "needs_choice": "needs_choice",
        "input": "needs_input",
        "input_required": "needs_input",
        "needs_input": "needs_input",
        "artifact": "artifact",
        "artifact_ready": "artifact",
        "patch": "artifact",
    }
    normalized = aliases.get(str(value or ""))
    if normalized in {"needs_approval", "needs_choice", "needs_input", "artifact"}:
        return normalized  # type: ignore[return-value]
    return None


def _tuple_value(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _int_value(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _validate_correlation(
    payload: dict[str, Any],
    expected: str,
    adapter: str,
    operation: str,
) -> None:
    actual = payload.get("correlation_id")
    if actual is not None and actual != expected:
        raise AgentAdapterError(
            adapter,
            operation,
            "runtime returned mismatched correlation_id",
            details={"expected": expected, "actual": actual},
        )


def _hlp_payload(
    task_id: str,
    agent_id: str,
    capability: str,
    parent_run: str | None,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "agent_id": agent_id,
        "capability": capability,
        "parent_run": parent_run,
    }


def _hlp_metadata(
    task_id: str,
    agent_id: str,
    capability: str,
    parent_run: str | None,
) -> dict[str, str]:
    return {
        "hlp_task_id": task_id,
        "hlp_agent_id": agent_id,
        "hlp_capability": capability,
        "hlp_parent_run": parent_run or "",
    }


def _normalize_langgraph_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(config)
    thread_id = normalized.pop("thread_id", None)
    configurable = dict(normalized.get("configurable", {}))
    if thread_id is not None and "thread_id" not in configurable:
        configurable["thread_id"] = thread_id
    if configurable:
        normalized["configurable"] = configurable
    return normalized


def _response_to_dict(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if hasattr(response, "dict"):
        return response.dict()
    result = {
        key: getattr(response, key)
        for key in ("id", "run_id", "output_text", "final_output", "raw")
        if hasattr(response, key)
    }
    return result or {"raw": response}
