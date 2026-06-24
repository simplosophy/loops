from __future__ import annotations

import asyncio
import json
from typing import Any

from loops.hlp import (
    ClaudeCodeCLIAdapter,
    CodexCLIAdapter,
    CodexHarnessAdapter,
    CrewAIAdapter,
    HLPClient,
    HermsCLIAdapter,
    LangGraphAdapter,
    OpenAIAgentsSDKAdapter,
    OpenAIPythonSDKAdapter,
    ProcessResult,
)


async def run_demo() -> dict[str, dict[str, str]]:
    """Run every first-party adapter target without external services."""

    targets = {
        "openai_python_sdk": OpenAIPythonSDKAdapter(
            client=_FakeOpenAIClient(run_id="resp_demo"),
            model="gpt-demo",
        ),
        "openai_agents_sdk": OpenAIAgentsSDKAdapter(
            agent="demo-agent",
            runner=_FakeOpenAIAgentsRunner(run_id="agents_demo"),
        ),
        "langgraph": LangGraphAdapter(graph=_FakeLangGraph(run_id="graph_demo")),
        "crewai": CrewAIAdapter(crew=_FakeCrew(run_id="crew_demo")),
        "codex_cli": CodexCLIAdapter(
            command=("codex", "exec", "--json"),
            runner=_process_runner("codex_demo"),
        ),
        "codex_harness": CodexHarnessAdapter(
            command=("codex", "exec", "--json"),
            runner=_process_runner("codex_harness_demo"),
        ),
        "claude_code_cli": ClaudeCodeCLIAdapter(
            command=("claude", "-p"),
            runner=_process_runner("claude_demo"),
        ),
        "herms_cli": HermsCLIAdapter(
            command=("herms", "run"),
            runner=_process_runner("herms_demo"),
        ),
    }

    result: dict[str, dict[str, str]] = {}
    for name, adapter in targets.items():
        client = HLPClient(adapter=adapter)
        task = await client.create_task(
            principal="user_demo",
            goal=f"Run {name} compatibility contract",
            type="adapter-compat",
        )
        run = await client.delegate(
            task.id,
            agent_id=f"agent_{name}",
            capability="adapter-compat",
            input={"goal": task.spec.goal},
        )
        result[name] = {
            "status": "ok",
            "task_id": task.id,
            "run_id": run.run_id,
            "correlation_id": adapter.task_of_run(run.run_id) or "",
        }
    return result


def main() -> None:
    print(json.dumps(asyncio.run(run_demo()), indent=2, sort_keys=True))


class _FakeOpenAIClient:
    def __init__(self, run_id: str) -> None:
        self.responses = _FakeOpenAIResponses(run_id)


class _FakeOpenAIResponses:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id

    async def create(self, **kwargs: Any) -> dict[str, str]:
        return {"id": self.run_id, "output_text": "ok"}


class _FakeOpenAIAgentsRunner:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id

    def run_sync(self, agent: Any, input: str, run_config: Any = None) -> dict[str, str]:
        return {"id": self.run_id, "final_output": "ok"}


class _FakeLangGraph:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id

    async def ainvoke(
        self,
        input: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        return {"run_id": self.run_id, "output": "ok"}


class _FakeCrew:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id

    async def akickoff(self, inputs: dict[str, Any]) -> dict[str, str]:
        return {"id": self.run_id, "raw": "ok"}


def _process_runner(run_id: str):
    async def runner(
        command: tuple[str, ...],
        request: dict[str, Any],
        timeout: float,
    ) -> ProcessResult:
        return ProcessResult(
            exit_code=0,
            stdout=json.dumps({"run_id": run_id}),
            stderr="",
        )

    return runner


if __name__ == "__main__":
    main()
