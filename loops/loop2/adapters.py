from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable


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
    """Generic process/CLI adapter placeholder.

    It uses the same deterministic contract recording as `FakeAgentAdapter` until
    a concrete command runner is supplied by an integration package. This keeps
    Codex CLI, Claude Code CLI, and unknown tools such as `herms` outside the HLP
    core dependency graph.
    """

    def __init__(self, command: tuple[str, ...], *, name: str = "process") -> None:
        super().__init__()
        self.command = command
        self.name = name

    async def healthcheck(self) -> dict[str, Any]:
        result = {
            "status": "ok",
            "adapter": self.name,
            "runs": len(self._runs),
            "command": self.command,
        }
        self.calls.append(("healthcheck", result))
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
    def __init__(self, handler: Callable[[dict[str, Any]], Any] | None = None) -> None:
        super().__init__("openai-python-sdk", handler)


class LangGraphAdapter(PythonCallableAgentAdapter):
    def __init__(self, handler: Callable[[dict[str, Any]], Any] | None = None) -> None:
        super().__init__("langgraph", handler)


class CrewAIAdapter(PythonCallableAgentAdapter):
    def __init__(self, handler: Callable[[dict[str, Any]], Any] | None = None) -> None:
        super().__init__("crewai", handler)


class CodexCLIAdapter(ProcessAgentAdapter):
    def __init__(self, command: tuple[str, ...] = ("codex", "exec")) -> None:
        super().__init__(command, name="codex-cli")


class ClaudeCodeCLIAdapter(ProcessAgentAdapter):
    def __init__(self, command: tuple[str, ...] = ("claude", "-p")) -> None:
        super().__init__(command, name="claude-code-cli")


class HermsCLIAdapter(ProcessAgentAdapter):
    def __init__(self, command: tuple[str, ...] = ("herms", "run")) -> None:
        super().__init__(command, name="herms-cli")


HermesCLIAdapter = HermsCLIAdapter
