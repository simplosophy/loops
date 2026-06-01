"""Prompt templates rendered by Jinja2."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from jinja2 import ChainableUndefined, DictLoader, Environment

from loops.loop0.profiles import (
    AgentProfile,
    ComponentProfile,
    InteractionContext,
    PolicyProfile,
    ProviderProfile,
    RunProfile,
    ToolProfile,
)
from loops.loop0.types import UserInput


@dataclass(frozen=True)
class PromptTemplate:
    """System/user prompt templates.

    The v1 engine uses Jinja2. Templates receive a structured
    PromptRenderContext and can use normal Jinja expressions, control flow, and
    filters. loops adds a `json` filter for profile/dataclass serialization.
    """

    system: str
    user: str = "{{ input.text }}"
    engine: str = "jinja"
    partials: dict[str, str] | None = None


@dataclass
class ComponentPromptView:
    profiles: list[ComponentProfile]
    prompt_blocks: list[str]


@dataclass
class AgentStateView:
    memories: list[Any]
    history: list[Any]
    artifacts: list[Any]
    component_state: dict[str, Any]


@dataclass
class PromptRenderContext:
    agent: AgentProfile
    provider: ProviderProfile
    interaction: InteractionContext
    tools: list[ToolProfile]
    components: ComponentPromptView
    state: AgentStateView
    input: UserInput
    run: RunProfile
    policy: PolicyProfile

    def to_mapping(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "provider": self.provider,
            "interaction": self.interaction,
            "tools": self.tools,
            "components": self.components,
            "state": self.state,
            "input": self.input,
            "run": self.run,
            "policy": self.policy,
        }


class PromptRenderer:
    """Render loops prompt templates with Jinja2."""

    def __init__(self, *, partials: dict[str, str] | None = None) -> None:
        self._env = Environment(
            loader=DictLoader(partials or {}),
            autoescape=False,
            undefined=ChainableUndefined,
            trim_blocks=False,
            lstrip_blocks=False,
        )
        self._env.filters["json"] = _json_filter

    def render(self, template: str, context: PromptRenderContext | dict[str, Any]) -> str:
        mapping = context.to_mapping() if isinstance(context, PromptRenderContext) else dict(context)
        return self._env.from_string(template).render(**mapping)


def _json_filter(value: Any) -> str:
    return json.dumps(_to_jsonable(value), ensure_ascii=False, sort_keys=True)


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_to_jsonable(item) for item in value)
    return value
