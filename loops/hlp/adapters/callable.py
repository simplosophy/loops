from __future__ import annotations

import inspect
from typing import Any, Callable

from ..objects import AdapterOperationContext
from ..schema import to_wire
from . import _util as util
from .fake import FakeAgentAdapter
from .protocol import AgentAdapterError, AgentRunHandle

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
        *,
        operation_context: AdapterOperationContext | None = None,
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
            if operation_context is not None:
                request["operation_context"] = to_wire(operation_context)
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
        call_payload = {
            "run_id": run_id,
            "task_id": task_id,
            "agent_id": agent_id,
            "capability": capability,
            "input": input,
            "parent_run": parent_run,
        }
        if operation_context is not None:
            call_payload["operation_context"] = to_wire(operation_context)
        self.calls.append(("delegate", call_payload))
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
        operation_context: AdapterOperationContext | None = None,
    ) -> str:
        payload = util.response_to_dict(result)
        util.validate_correlation(payload, task_id, self.name, "delegate")
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
        call_payload = {
            "run_id": run_id,
            "task_id": task_id,
            "agent_id": agent_id,
            "capability": capability,
            "input": input,
            "parent_run": parent_run,
        }
        if operation_context is not None:
            call_payload["operation_context"] = to_wire(operation_context)
        self.calls.append(("delegate", call_payload))
        return run_id

    def _next_framework_run_id(self, prefix: str) -> str:
        self._run_counter += 1
        return f"{prefix}_{self._run_counter:06d}"

