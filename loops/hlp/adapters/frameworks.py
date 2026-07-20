from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from ..objects import AdapterOperationContext
from ..schema import to_wire
from . import _util as util
from .callable import PythonCallableAgentAdapter
from .protocol import AgentAdapterError, AgentRunHandle


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
        *,
        operation_context: AdapterOperationContext | None = None,
    ) -> str:
        if self.agent is None or self.runner is None:
            return await super().delegate(
                task_id=task_id,
                agent_id=agent_id,
                capability=capability,
                input=input,
                parent_run=parent_run,
                operation_context=operation_context,
            )
        try:
            if hasattr(self.runner, "run"):
                result = self.runner.run(
                    self.agent,
                    util.prompt_from_input(input),
                    run_config=self.run_config,
                )
            else:
                result = self.runner.run_sync(
                    self.agent,
                    util.prompt_from_input(input),
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
            operation_context=operation_context,
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
        *,
        operation_context: AdapterOperationContext | None = None,
    ) -> str:
        if self.client is None:
            return await super().delegate(
                task_id=task_id,
                agent_id=agent_id,
                capability=capability,
                input=input,
                parent_run=parent_run,
                operation_context=operation_context,
            )
        try:
            metadata = {
                "hlp_task_id": task_id,
                "hlp_agent_id": agent_id,
                "hlp_capability": capability,
                "hlp_parent_run": parent_run or "",
            }
            if operation_context is not None:
                metadata["hlp_operation_id"] = operation_context.operation_id
            response = self.client.responses.create(
                model=self.model,
                input=util.prompt_from_input(input),
                metadata=metadata,
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
        result = util.response_to_dict(response)
        util.validate_correlation(result, task_id, self.name, "delegate")
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
        *,
        operation_context: AdapterOperationContext | None = None,
    ) -> str:
        if self.graph is None:
            return await super().delegate(
                task_id=task_id,
                agent_id=agent_id,
                capability=capability,
                input=input,
                parent_run=parent_run,
                operation_context=operation_context,
            )
        graph_input = {
            "messages": [{"role": "user", "content": util.prompt_from_input(input)}],
            "hlp": util.hlp_payload(task_id, agent_id, capability, parent_run),
        }
        if isinstance(input.get("state"), dict):
            graph_input["state"] = input["state"]
        config = util.normalize_langgraph_config(self.config)
        config["metadata"] = {
            **dict(config.get("metadata", {})),
            **util.hlp_metadata(task_id, agent_id, capability, parent_run),
        }
        if operation_context is not None:
            config["metadata"]["hlp_operation_id"] = operation_context.operation_id
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
            operation_context=operation_context,
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
        *,
        operation_context: AdapterOperationContext | None = None,
    ) -> str:
        if self.crew is None:
            return await super().delegate(
                task_id=task_id,
                agent_id=agent_id,
                capability=capability,
                input=input,
                parent_run=parent_run,
                operation_context=operation_context,
            )
        crew_inputs = {
            **input,
            **util.hlp_metadata(task_id, agent_id, capability, parent_run),
        }
        if operation_context is not None:
            crew_inputs["hlp_operation_id"] = operation_context.operation_id
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
            operation_context=operation_context,
        )
