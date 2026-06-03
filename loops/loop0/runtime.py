"""Core agent execution loop."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from loops.loop0.components.base import Contribution
from loops.loop0.events import AgentEvent
from loops.loop0.io import EventSink, EventSinkLike, normalize_event_sink
from loops.loop0.policy import AgentPolicy
from loops.loop0.profiles import AgentProfile, ComponentProfile, InteractionContext, PolicyProfile, RunProfile
from loops.loop0.prompt import AgentStateView, ComponentPromptView, PromptRenderContext, PromptRenderer
from loops.loop0.providers.base import ProviderRequest, ProviderResponse
from loops.loop0.state import AgentState
from loops.loop0.tools.base import ToolContext, ToolRegistry, ToolResult
from loops.loop0.types import Message, ToolCall, UserInput


@dataclass
class RuntimeStats:
    turns: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class AgentResult:
    output: str
    run_id: str
    thread_id: str
    stop_reason: str = "completed"
    stats: RuntimeStats = field(default_factory=RuntimeStats)
    events: list[AgentEvent] = field(default_factory=list)
    raw: Any | None = None


@dataclass
class Run:
    agent: Any
    input: UserInput
    thread_id: str
    interaction: InteractionContext
    event_sink: EventSink
    stream: bool = False
    run_id: str = field(default_factory=lambda: f"run_{uuid4().hex[:12]}")
    messages: list[Message] = field(default_factory=list)
    tool_registry: ToolRegistry = field(default_factory=ToolRegistry)
    contributions: list[Contribution] = field(default_factory=list)
    prompt_context: PromptRenderContext | None = None
    system_prompt: str = ""
    user_prompt: str = ""
    stats: RuntimeStats = field(default_factory=RuntimeStats)
    events: list[AgentEvent] = field(default_factory=list)
    pending_state_messages: list[Message] = field(default_factory=list)


class AgentRuntime:
    """Owns the provider/tool loop for one Agent."""

    def __init__(self, agent: Any) -> None:
        self.agent = agent
        self._renderer = PromptRenderer()

    async def run(
        self,
        input: UserInput,
        *,
        thread_id: str | None = None,
        event_sink: EventSinkLike = None,
        stream: bool = False,
    ) -> AgentResult:
        await self._ensure_components_setup()
        interaction = self._resolve_interaction_context(input, thread_id=thread_id, stream=stream)
        resolved_thread_id = (
            thread_id
            or interaction.thread_id
            or interaction.session_id
            or "default"
        )
        interaction = replace(interaction, thread_id=str(resolved_thread_id), stream=stream)
        run = Run(
            agent=self.agent,
            input=input,
            thread_id=str(resolved_thread_id),
            interaction=interaction,
            event_sink=normalize_event_sink(event_sink),
            stream=stream,
        )
        try:
            await self._prepare(run)
            await self._emit(
                run,
                "run_started",
                {
                    "thread_id": run.thread_id,
                    "interaction": run.interaction.source,
                    "input_chars": len(run.input.text),
                },
            )
            result = await self._provider_tool_loop(run)
            self._commit(run, result)
            await self._emit(run, "run_finished", {"output": result.output, "stop_reason": result.stop_reason})
            result.events = list(run.events)
            return result
        except Exception as exc:
            await self._emit(
                run,
                "run_failed",
                {
                    "thread_id": run.thread_id,
                    "interaction": run.interaction.source,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            raise

    async def _ensure_components_setup(self) -> None:
        if self.agent._setup_complete:
            return
        for component in self.agent.spec.components:
            await component.setup(self.agent)
        self.agent._setup_complete = True

    async def _prepare(self, run: Run) -> None:
        run.tool_registry.extend(list(self.agent.spec.tools))
        for component in self.agent.spec.components:
            contribution = await component.contribute(run)
            run.contributions.append(contribution)
            run.tool_registry.extend(list(contribution.tools))

        prompt_blocks = [block for contribution in run.contributions for block in contribution.prompt_blocks]
        component_profiles = [
            getattr(component, "profile", ComponentProfile(name=type(component).__name__))
            for component in self.agent.spec.components
        ]

        history = self.agent.state.get_history(run.thread_id)
        memories = self.agent.state.recall(run.input.text)
        run.prompt_context = PromptRenderContext(
            agent=AgentProfile(
                name=str(self.agent.spec.metadata.get("name") or "agent"),
                description=str(self.agent.spec.metadata.get("description") or ""),
                metadata=dict(self.agent.spec.metadata),
            ),
            provider=self.agent.spec.provider.profile,
            interaction=run.interaction,
            tools=run.tool_registry.profiles,
            components=ComponentPromptView(profiles=component_profiles, prompt_blocks=prompt_blocks),
            state=AgentStateView(
                memories=memories,
                history=history,
                artifacts=list(self.agent.state.artifacts.values()),
                component_state=self.agent.state.component_state,
            ),
            input=run.input,
            run=RunProfile(run_id=run.run_id, thread_id=run.thread_id),
            policy=PolicyProfile(
                max_turns=self.agent.spec.policy.max_turns,
                allow_tool_errors=self.agent.spec.policy.allow_tool_errors,
                approval_available=self.agent.spec.policy.approval_available,
                parallel_tool_calls=self.agent.spec.policy.parallel_tool_calls,
                max_parallel_tool_calls=self.agent.spec.policy.max_parallel_tool_calls,
                metadata=dict(self.agent.spec.policy.metadata),
            ),
        )
        run.system_prompt = self._renderer.render(self.agent.spec.prompt.system, run.prompt_context)
        run.user_prompt = self._renderer.render(self.agent.spec.prompt.user, run.prompt_context)
        run.messages = [
            Message(role="system", content=run.system_prompt),
            *history,
            Message(role="user", content=run.user_prompt),
        ]
        run.pending_state_messages.append(Message(role="user", content=run.input.text, metadata=run.input.metadata))

    def _resolve_interaction_context(
        self,
        input: UserInput,
        *,
        thread_id: str | None,
        stream: bool,
    ) -> InteractionContext:
        context = input.interaction_context
        if isinstance(context, InteractionContext):
            return replace(context, thread_id=thread_id or context.thread_id, stream=stream)
        if isinstance(context, dict):
            return InteractionContext(
                source=str(context.get("source") or "external"),
                session_id=context.get("session_id"),
                thread_id=thread_id or context.get("thread_id"),
                actor_id=context.get("actor_id"),
                reply_to=context.get("reply_to"),
                audience=context.get("audience", "user"),
                interactive=bool(context.get("interactive", False)),
                stream=stream,
                locale=context.get("locale"),
                raw=dict(context),
            )
        if context is not None:
            raw = getattr(context, "raw", None) or {}
            return InteractionContext(
                source=str(getattr(context, "source", None) or "external"),
                session_id=getattr(context, "session_id", None),
                thread_id=thread_id or getattr(context, "thread_id", None),
                actor_id=getattr(context, "actor_id", None),
                reply_to=getattr(context, "reply_to", None),
                audience=getattr(context, "audience", "user"),
                interactive=bool(getattr(context, "interactive", False)),
                stream=stream,
                locale=getattr(context, "locale", None),
                raw=dict(raw),
            )
        return InteractionContext(thread_id=thread_id, stream=stream)

    async def _provider_tool_loop(self, run: Run) -> AgentResult:
        final_response: ProviderResponse | None = None
        for turn_index in range(1, self.agent.spec.policy.max_turns + 1):
            run.stats.turns += 1
            request = ProviderRequest(
                messages=list(run.messages),
                tools=run.tool_registry.profiles,
                stream=run.stream,
                parallel_tool_calls=self.agent.spec.policy.parallel_tool_calls,
                metadata={"run_id": run.run_id, "thread_id": run.thread_id},
            )
            provider_profile = self.agent.spec.provider.profile
            await self._emit(
                run,
                "provider_started",
                {
                    "turn": turn_index,
                    "provider": provider_profile.name,
                    "model": provider_profile.model,
                    "stream": request.stream,
                    "parallel_tool_calls": request.parallel_tool_calls,
                    "message_count": len(request.messages),
                    "tool_count": len(request.tools),
                },
            )
            response = await self._call_provider(run, request)
            await self._emit(
                run,
                "provider_finished",
                {
                    "turn": turn_index,
                    "tool_call_count": len(response.tool_calls),
                    "content": response.content,
                    "content_chars": len(response.content),
                    "stop_reason": response.stop_reason,
                    "usage": _usage_payload(response),
                },
            )
            self._record_usage(run, response)
            final_response = response
            if not response.tool_calls:
                output = response.content
                run.pending_state_messages.append(Message(role="assistant", content=output))
                return AgentResult(
                    output=output,
                    run_id=run.run_id,
                    thread_id=run.thread_id,
                    stats=run.stats,
                    raw=response.raw,
                )

            run.messages.append(
                Message(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                    metadata=dict(response.message_metadata),
                )
            )
            tool_results = await self._execute_tool_calls(run, response.tool_calls)
            for tool_call, result in zip(response.tool_calls, tool_results, strict=False):
                run.messages.append(
                    Message(
                        role="tool",
                        content=result.message_content(),
                        tool_call_id=tool_call.id,
                        metadata=result.metadata,
                    )
                )
        return AgentResult(
            output="",
            run_id=run.run_id,
            thread_id=run.thread_id,
            stop_reason="turn_limit_reached",
            stats=run.stats,
            raw=final_response.raw if final_response else None,
        )

    async def _call_provider(self, run: Run, request: ProviderRequest) -> ProviderResponse:
        if not request.stream:
            return await self.agent.spec.provider.generate(request)

        final_response: ProviderResponse | None = None
        async for event in self.agent.spec.provider.stream(request):
            if event.type in {"delta", "text_delta"}:
                text = str(event.payload.get("text") or "")
                if text:
                    await self._emit(run, "provider_delta", {"text": text})
            elif event.type == "reasoning_delta":
                text = str(event.payload.get("text") or "")
                if text:
                    await self._emit(run, "provider_reasoning_delta", {"text": text})
            elif event.type in {"response", "response_finished"}:
                response = event.payload.get("response")
                if isinstance(response, ProviderResponse):
                    final_response = response
            elif event.type == "provider_error":
                error = event.payload.get("error")
                await self._emit(
                    run,
                    "provider_error",
                    {"error": str(error or ""), "payload": dict(event.payload)},
                )
                if isinstance(error, BaseException):
                    raise error
                raise RuntimeError(str(error or "provider error"))
        if final_response is None:
            return ProviderResponse(content="")
        return final_response

    async def _execute_tool_calls(self, run: Run, tool_calls: list[ToolCall]) -> list[ToolResult]:
        if not tool_calls:
            return []
        max_parallel = self.agent.spec.policy.max_parallel_tool_calls
        if max_parallel is None or max_parallel > 1:
            return await self._execute_tool_calls_parallel(run, tool_calls, max_parallel=max_parallel)
        results: list[ToolResult] = []
        for tool_call in tool_calls:
            run.stats.tool_calls += 1
            results.append(await self._execute_tool_call(run, tool_call))
        return results

    async def _execute_tool_calls_parallel(
        self,
        run: Run,
        tool_calls: list[ToolCall],
        *,
        max_parallel: int | None,
    ) -> list[ToolResult]:
        semaphore = asyncio.Semaphore(max_parallel) if max_parallel is not None else None

        async def execute_one(tool_call: ToolCall) -> ToolResult:
            if semaphore is None:
                return await self._execute_tool_call(run, tool_call)
            async with semaphore:
                return await self._execute_tool_call(run, tool_call)

        run.stats.tool_calls += len(tool_calls)
        tasks = [asyncio.create_task(execute_one(tool_call)) for tool_call in tool_calls]
        try:
            return list(await asyncio.gather(*tasks))
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def _execute_tool_call(self, run: Run, tool_call: ToolCall) -> ToolResult:
        arguments = dict(tool_call.arguments)
        await self._emit(
            run,
            "tool_started",
            {"tool_name": tool_call.name, "tool_call_id": tool_call.id, "arguments": arguments},
        )
        started_at = perf_counter()
        ctx = ToolContext(
            agent_id=self.agent.state.agent_id,
            run_id=run.run_id,
            workspace=Path(self.agent.workspace),
            policy=self.agent.spec.policy,
            state=self.agent.state,
            emit=lambda event: self._emit_event_object(run, event),
            metadata={"thread_id": run.thread_id},
        )
        result = await run.tool_registry.execute(tool_call.name, arguments, ctx)
        duration_ms = (perf_counter() - started_at) * 1000
        await self._emit(
            run,
            "tool_finished",
            {
                "tool_name": tool_call.name,
                "tool_call_id": tool_call.id,
                "status": result.status,
                "output": result.output,
                "error": result.error,
                "metadata": dict(result.metadata),
                "duration_ms": duration_ms,
            },
        )
        if result.error and not self.agent.spec.policy.allow_tool_errors:
            raise RuntimeError(result.error)
        return result

    async def _emit(self, run: Run, event_type: str, payload: dict[str, Any]) -> None:
        await self._emit_event_object(run, AgentEvent(type=event_type, run_id=run.run_id, payload=payload))

    async def _emit_event_object(self, run: Run, event: AgentEvent) -> None:
        run.events.append(event)
        self._log_event(event)
        await run.event_sink.send(event)
        for component in self.agent.spec.components:
            await component.handle_event(event)

    def _commit(self, run: Run, result: AgentResult) -> None:
        if result.stop_reason not in {"completed", "turn_limit_reached"}:
            return
        for message in run.pending_state_messages:
            self.agent.state.append_message(run.thread_id, message)

    @staticmethod
    def _record_usage(run: Run, response: ProviderResponse) -> None:
        if response.usage is None:
            return
        run.stats.input_tokens += response.usage.input_tokens
        run.stats.output_tokens += response.usage.output_tokens

    def _log_event(self, event: AgentEvent) -> None:
        try:
            self.agent.logger.log_event(event)
        except Exception:
            return


def _usage_payload(response: ProviderResponse) -> dict[str, int] | None:
    if response.usage is None:
        return None
    return {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "total_tokens": response.usage.total_tokens,
        "cache_read_tokens": response.usage.cache_read_tokens,
        "cache_creation_tokens": response.usage.cache_creation_tokens,
    }
