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
from loops.loop0.providers.base import Provider, ProviderEvent, ProviderRequest, ProviderResponse, ProviderUsage
from loops.loop0.types import Message, ToolCall


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
        payload = self._build_payload(request, stream=False)
        data = await asyncio.to_thread(self._post_json, payload)
        return _response_from_openai(data)

    async def stream(self, request: ProviderRequest):
        payload = self._build_payload(request, stream=True)
        queue: asyncio.Queue[ProviderEvent | BaseException | None] = asyncio.Queue()

        def on_event(event: ProviderEvent) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        def worker() -> None:
            try:
                response = self._stream_json(payload, on_event=on_event)
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    ProviderEvent(type="response", payload={"response": response}),
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

    def _build_payload(self, request: ProviderRequest, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_message_to_openai(message) for message in request.messages],
            "tools": [_tool_to_openai(tool) for tool in request.tools],
        }
        if not payload["tools"]:
            payload.pop("tools")
        elif request.parallel_tool_calls is not None:
            payload["parallel_tool_calls"] = bool(request.parallel_tool_calls)
        if stream:
            payload["stream"] = True
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        if self.extra_body:
            payload.update(self.extra_body)
        return payload

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._open_request(payload) as response:
            return json.loads(response.read().decode("utf-8"))

    def _stream_json(self, payload: dict[str, Any], *, on_event) -> ProviderResponse:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_call_chunks: dict[int, dict[str, Any]] = {}
        finish_reason = ""
        raw_chunks: list[dict[str, Any]] = []

        with self._open_request(payload) as response:
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
                    on_event(ProviderEvent(type="delta", payload={"text": text}))
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

    def _open_request(self, payload: dict[str, Any]):
        endpoint = self.base_url.rstrip("/") + "/chat/completions"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            **self.headers,
        }
        request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
        context = None
        if self.disable_verify_ssl:
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        try:
            return urllib.request.urlopen(request, timeout=self.timeout_seconds, context=context)
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
