from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from .protocol import AgentAdapterError


def adapter_payload(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value


def validate_correlation(
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


def prompt_from_input(input: dict[str, Any]) -> str:
    import json

    goal = input.get("goal")
    if goal is not None and set(input) == {"goal"}:
        return str(goal)
    return json.dumps(input, sort_keys=True)


def hlp_payload(
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


def hlp_metadata(
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


def normalize_langgraph_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(config)
    thread_id = normalized.pop("thread_id", None)
    configurable = dict(normalized.get("configurable", {}))
    if thread_id is not None and "thread_id" not in configurable:
        configurable["thread_id"] = thread_id
    if configurable:
        normalized["configurable"] = configurable
    return normalized


def response_to_dict(response: Any) -> dict[str, Any]:
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


def tuple_value(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def int_value(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
