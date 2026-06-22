from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable


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
    """Handle returned by HLP when work is delegated to an agent runtime."""

    run_id: str
    task_id: str
    agent_id: str
    correlation_id: str
    capability: str = ""
    parent_run: str | None = None


@runtime_checkable
class AgentAdapter(Protocol):
    """HLP to agent-runtime adapter contract.

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
        self.calls.append((
            "block",
            {"run_id": run_id, "checkpoint_id": checkpoint_id, "reason": reason},
        ))

    async def resume(self, run_id: str, resolution: Any) -> None:
        self.calls.append((
            "resume",
            {"run_id": run_id, "resolution": resolution},
        ))

    async def handoff(self, run_id: str, to_agent: str, context: dict[str, Any]) -> str:
        current = self._runs[run_id]
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
        await self._execute("block", {
            "operation": "block",
            "run_id": run_id,
            "checkpoint_id": checkpoint_id,
            "reason": reason,
            "correlation_id": self.task_of_run(run_id),
        })
        await FakeAgentAdapter.block(self, run_id, checkpoint_id, reason)

    async def resume(self, run_id: str, resolution: Any) -> None:
        await self._execute("resume", {
            "operation": "resume",
            "run_id": run_id,
            "resolution": resolution,
            "correlation_id": self.task_of_run(run_id),
        })
        await FakeAgentAdapter.resume(self, run_id, resolution)

    async def handoff(self, run_id: str, to_agent: str, context: dict[str, Any]) -> str:
        payload = await self._execute("handoff", {
            "operation": "handoff",
            "run_id": run_id,
            "to_agent": to_agent,
            "context": context,
            "correlation_id": self.task_of_run(run_id),
        })
        current = self._runs[run_id]
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
        await self._execute("cancel", {
            "operation": "cancel",
            "run_id": run_id,
            "reason": reason,
            "correlation_id": self.task_of_run(run_id),
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
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
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
        run_id = await super().delegate(
            task_id=task_id,
            agent_id=agent_id,
            capability=capability,
            input=input,
            parent_run=parent_run,
        )
        if self.handler is not None:
            request = {
                "run_id": run_id,
                "task_id": task_id,
                "agent_id": agent_id,
                "capability": capability,
                "input": input,
                "parent_run": parent_run,
            }
            result = self.handler(request)
            if inspect.isawaitable(result):
                result = await result
            self.results[run_id] = result
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


class OpenAIAgentsSDKAdapter(PythonCallableAgentAdapter):
    def __init__(self, handler: Callable[[dict[str, Any]], Any] | None = None) -> None:
        super().__init__("openai-agents-sdk", handler)


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
    def __init__(self, handler: Callable[[dict[str, Any]], Any] | None = None) -> None:
        super().__init__("langgraph", handler)


class CrewAIAdapter(PythonCallableAgentAdapter):
    def __init__(self, handler: Callable[[dict[str, Any]], Any] | None = None) -> None:
        super().__init__("crewai", handler)


class CodexCLIAdapter(ProcessAgentAdapter):
    def __init__(
        self,
        command: tuple[str, ...] = ("codex", "exec"),
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(command, name="codex-cli", runner=runner, timeout=timeout)


class ClaudeCodeCLIAdapter(ProcessAgentAdapter):
    def __init__(
        self,
        command: tuple[str, ...] = ("claude", "-p"),
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(command, name="claude-code-cli", runner=runner, timeout=timeout)


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


def _prompt_from_input(input: dict[str, Any]) -> str:
    goal = input.get("goal")
    if goal is not None:
        return str(goal)
    return json.dumps(input, sort_keys=True)


def _response_to_dict(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        return response
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if hasattr(response, "dict"):
        return response.dict()
    result = {
        key: getattr(response, key)
        for key in ("id", "output_text")
        if hasattr(response, key)
    }
    return result or {"raw": response}
