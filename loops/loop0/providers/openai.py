"""OpenAI-compatible provider adapter.

This adapter intentionally uses stdlib urllib so loops core stays dependency-light.
It can talk to OpenAI-compatible `/chat/completions` endpoints.
"""

from __future__ import annotations

import asyncio
import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from loops.loop0.profiles import ProviderProfile, ToolProfile
from loops.loop0.providers.adapter import (
    ProviderAdapter,
    ProviderModel,
    ProviderOptions,
    register_provider_adapter,
)
from loops.loop0.providers.base import Provider, ProviderEvent, ProviderRequest, ProviderResponse, ProviderUsage
from loops.loop0.types import Message, ToolCall

OPENAI_CHAT_API = "openai-chat"


@dataclass
class OpenAICompatibleProvider(Provider):
    model: str
    api_key: str
    base_url: str = "https://api.openai.com/v1"
    name: str = "openai-compatible"
    timeout_seconds: float = 60.0
    disable_verify_ssl: bool = False
    headers: dict[str, str] = field(default_factory=dict)
    reasoning_effort: str | None = None
    extra_body: dict[str, Any] = field(default_factory=dict)

    @property
    def profile(self) -> ProviderProfile:
        return ProviderProfile(
            name=self.name,
            model=self.model,
            capabilities=frozenset({"tool_calling"}),
            metadata={
                "base_url": self.base_url,
                "disable_verify_ssl": self.disable_verify_ssl,
            },
        )

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        return await OPENAI_CHAT_ADAPTER.generate(self._provider_model(), request, self._provider_options())

    async def stream(self, request: ProviderRequest):
        async for event in OPENAI_CHAT_ADAPTER.stream(self._provider_model(), request, self._provider_options()):
            yield event

    def _provider_model(self) -> ProviderModel:
        return ProviderModel(
            provider=self.name,
            model=self.model,
            api=OPENAI_CHAT_API,
            base_url=self.base_url,
            capabilities=frozenset({"tool_calling"}),
            metadata={"disable_verify_ssl": self.disable_verify_ssl},
        )

    def _provider_options(self) -> ProviderOptions:
        return ProviderOptions(
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
            disable_verify_ssl=self.disable_verify_ssl,
            headers=dict(self.headers),
            reasoning_effort=self.reasoning_effort,
            extra_body=dict(self.extra_body),
        )

    def _build_payload(self, request: ProviderRequest, *, stream: bool) -> dict[str, Any]:
        return OPENAI_CHAT_ADAPTER.build_payload(
            self._provider_model(),
            request,
            self._provider_options(),
            stream=stream,
        )

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        return OPENAI_CHAT_ADAPTER._post_json(self._provider_model(), self._provider_options(), payload)

    def _stream_json(self, payload: dict[str, Any], *, on_event) -> ProviderResponse:
        return OPENAI_CHAT_ADAPTER._stream_json(
            self._provider_model(),
            self._provider_options(),
            payload,
            on_event=on_event,
        )

    def _open_request(self, payload: dict[str, Any]):
        return OPENAI_CHAT_ADAPTER._open_request(self._provider_model(), self._provider_options(), payload)


class OpenAIChatAdapter(ProviderAdapter):
    """Adapter for OpenAI-compatible `/chat/completions` APIs."""

    api = OPENAI_CHAT_API

    async def generate(
        self,
        model: ProviderModel,
        request: ProviderRequest,
        options: ProviderOptions,
    ) -> ProviderResponse:
        payload = self.build_payload(model, request, options, stream=False)
        data = await asyncio.to_thread(self._post_json, model, options, payload)
        return _response_from_openai(data)

    async def stream(self, model: ProviderModel, request: ProviderRequest, options: ProviderOptions):
        payload = self.build_payload(model, request, options, stream=True)
        queue: asyncio.Queue[ProviderEvent | BaseException | None] = asyncio.Queue()

        def on_event(event: ProviderEvent) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        def worker() -> None:
            try:
                response = self._stream_json(model, options, payload, on_event=on_event)
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    ProviderEvent(type="response_finished", payload={"response": response}),
                )
            except BaseException as exc:
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        loop = asyncio.get_running_loop()
        task = asyncio.to_thread(worker)
        asyncio.create_task(task)
        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, BaseException):
                raise item
            yield item

    def build_payload(
        self,
        model: ProviderModel,
        request: ProviderRequest,
        options: ProviderOptions,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model.model,
            "messages": [_message_to_openai(message) for message in request.messages],
            "tools": [_tool_to_openai(tool) for tool in request.tools],
        }
        if not payload["tools"]:
            payload.pop("tools")
        elif request.parallel_tool_calls is not None:
            payload["parallel_tool_calls"] = bool(request.parallel_tool_calls)
        if stream:
            payload["stream"] = True
        if options.reasoning_effort:
            payload["reasoning_effort"] = options.reasoning_effort
        if options.extra_body:
            payload.update(options.extra_body)
        return payload

    def _post_json(self, model: ProviderModel, options: ProviderOptions, payload: dict[str, Any]) -> dict[str, Any]:
        with self._open_request(model, options, payload) as response:
            return json.loads(response.read().decode("utf-8"))

    def _stream_json(
        self,
        model: ProviderModel,
        options: ProviderOptions,
        payload: dict[str, Any],
        *,
        on_event,
    ) -> ProviderResponse:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_call_chunks: dict[int, dict[str, Any]] = {}
        finish_reason = ""
        raw_chunks: list[dict[str, Any]] = []

        with self._open_request(model, options, payload) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                raw_chunks.append(chunk)
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                finish_reason = str(choice.get("finish_reason") or finish_reason or "")
                delta = choice.get("delta") or {}
                text = str(delta.get("content") or "")
                if text:
                    content_parts.append(text)
                    on_event(ProviderEvent(type="text_delta", payload={"text": text}))
                reasoning = str(delta.get("reasoning_content") or "")
                if reasoning:
                    reasoning_parts.append(reasoning)
                    on_event(ProviderEvent(type="reasoning_delta", payload={"text": reasoning}))
                _merge_tool_call_deltas(tool_call_chunks, delta.get("tool_calls") or [])

        content = "".join(content_parts)
        reasoning_content = "".join(reasoning_parts)
        tool_calls = _tool_calls_from_stream_chunks(tool_call_chunks)
        return ProviderResponse(
            content=content,
            tool_calls=tool_calls,
            stop_reason=finish_reason,
            message_metadata={"reasoning_content": reasoning_content} if reasoning_content else {},
            raw={"chunks": raw_chunks},
        )

    def _open_request(self, model: ProviderModel, options: ProviderOptions, payload: dict[str, Any]):
        endpoint = model.base_url.rstrip("/") + "/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {options.api_key}",
            **options.headers,
        }
        request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
        context = None
        if options.disable_verify_ssl:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        try:
            return urllib.request.urlopen(request, timeout=options.timeout_seconds, context=context)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Provider HTTP {exc.code} from {endpoint}: {_compact_error_body(body)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Provider request failed for {endpoint}: {exc.reason}") from exc


def _message_to_openai(message: Message) -> dict[str, Any]:
    data: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_call_id:
        data["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        data["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in message.tool_calls
        ]
    for key in ("reasoning_content",):
        value = message.metadata.get(key)
        if value is not None:
            data[key] = value
    return data


def _tool_to_openai(tool: ToolProfile) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


def _response_from_openai(data: dict[str, Any]) -> ProviderResponse:
    choices = data.get("choices") or []
    message = (choices[0].get("message") if choices else {}) or {}
    raw_tool_calls = message.get("tool_calls") or []
    tool_calls: list[ToolCall] = []
    for raw in raw_tool_calls:
        fn = raw.get("function") or {}
        arguments = fn.get("arguments") or "{}"
        try:
            parsed_args = json.loads(arguments)
        except json.JSONDecodeError:
            parsed_args = {"raw": arguments}
        tool_calls.append(
            ToolCall(
                id=str(raw.get("id") or ""),
                name=str(fn.get("name") or ""),
                arguments=parsed_args if isinstance(parsed_args, dict) else {"value": parsed_args},
                raw=raw,
            )
        )
    usage_data = data.get("usage") or {}
    usage = ProviderUsage(
        input_tokens=int(usage_data.get("prompt_tokens") or 0),
        output_tokens=int(usage_data.get("completion_tokens") or 0),
        total_tokens=int(usage_data.get("total_tokens") or 0),
    )
    return ProviderResponse(
        content=str(message.get("content") or ""),
        tool_calls=tool_calls,
        usage=usage,
        stop_reason=str(choices[0].get("finish_reason") or "") if choices else None,
        message_metadata=_message_metadata_from_openai(message),
        raw=data,
    )


def _merge_tool_call_deltas(target: dict[int, dict[str, Any]], deltas: list[dict[str, Any]]) -> None:
    for delta in deltas:
        index = int(delta.get("index") or 0)
        current = target.setdefault(index, {"id": "", "name": "", "arguments": ""})
        if delta.get("id"):
            current["id"] = str(delta.get("id") or "")
        function = delta.get("function") or {}
        if function.get("name"):
            current["name"] = str(function.get("name") or "")
        if function.get("arguments"):
            current["arguments"] += str(function.get("arguments") or "")


def _tool_calls_from_stream_chunks(chunks: dict[int, dict[str, Any]]) -> list[ToolCall]:
    tool_calls: list[ToolCall] = []
    for index in sorted(chunks):
        chunk = chunks[index]
        raw_arguments = str(chunk.get("arguments") or "{}")
        try:
            parsed_args = json.loads(raw_arguments)
        except json.JSONDecodeError:
            parsed_args = {"raw": raw_arguments}
        tool_calls.append(
            ToolCall(
                id=str(chunk.get("id") or f"call_{index}"),
                name=str(chunk.get("name") or ""),
                arguments=parsed_args if isinstance(parsed_args, dict) else {"value": parsed_args},
                raw=chunk,
            )
        )
    return tool_calls


def _message_metadata_from_openai(message: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("reasoning_content",):
        if key in message and message[key] is not None:
            metadata[key] = message[key]
    return metadata


def _compact_error_body(body: str, *, limit: int = 2000) -> str:
    text = str(body or "").strip()
    if not text:
        return "<empty response body>"
    try:
        parsed = json.loads(text)
        text = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
    except Exception:
        pass
    if len(text) > limit:
        return text[:limit].rstrip() + "... [truncated]"
    return text


OPENAI_CHAT_ADAPTER = OpenAIChatAdapter()
register_provider_adapter(OPENAI_CHAT_ADAPTER)
