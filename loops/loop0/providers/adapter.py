"""Provider adapter registry and adapter-backed provider facade."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from loops.loop0.profiles import ProviderProfile
from loops.loop0.providers.base import Provider, ProviderEvent, ProviderRequest, ProviderResponse


@dataclass(frozen=True)
class ProviderModel:
    """Provider-neutral model identity and protocol metadata."""

    provider: str
    model: str
    api: str
    base_url: str = ""
    capabilities: frozenset[str] = frozenset()
    compat: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderOptions:
    """Runtime options passed to provider adapters."""

    api_key: str = ""
    timeout_seconds: float = 60.0
    disable_verify_ssl: bool = False
    headers: dict[str, str] = field(default_factory=dict)
    reasoning_effort: str | None = None
    extra_body: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class ProviderAdapter:
    """Protocol-specific provider adapter.

    Adapters own provider API conversion. The runtime-facing `Provider` facade
    owns profile exposure and forwards requests to an adapter.
    """

    api: str

    async def generate(
        self,
        model: ProviderModel,
        request: ProviderRequest,
        options: ProviderOptions,
    ) -> ProviderResponse:
        final_response: ProviderResponse | None = None
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        async for event in self.stream(model, request, options):
            if event.type in {"text_delta", "delta"}:
                text = str(event.payload.get("text") or "")
                if text:
                    content_parts.append(text)
            elif event.type == "reasoning_delta":
                text = str(event.payload.get("text") or "")
                if text:
                    reasoning_parts.append(text)
            elif event.type in {"response_finished", "response"}:
                response = event.payload.get("response")
                if isinstance(response, ProviderResponse):
                    final_response = response
            elif event.type == "provider_error":
                error = event.payload.get("error")
                if isinstance(error, BaseException):
                    raise error
                raise RuntimeError(str(error or "provider error"))
        if final_response is not None:
            return final_response
        reasoning_content = "".join(reasoning_parts)
        return ProviderResponse(
            content="".join(content_parts),
            message_metadata={"reasoning_content": reasoning_content} if reasoning_content else {},
        )

    async def stream(
        self,
        model: ProviderModel,
        request: ProviderRequest,
        options: ProviderOptions,
    ) -> AsyncIterator[ProviderEvent]:
        response = await self.generate(model, request, options)
        if response.content:
            yield ProviderEvent(type="text_delta", payload={"text": response.content})
        yield ProviderEvent(type="response_finished", payload={"response": response})


@dataclass
class AdapterBackedProvider(Provider):
    """Runtime-facing provider facade backed by a protocol adapter."""

    provider_model: ProviderModel
    options: ProviderOptions = field(default_factory=ProviderOptions)
    adapter: ProviderAdapter | None = None

    def __post_init__(self) -> None:
        if self.adapter is None:
            self.adapter = get_provider_adapter(self.provider_model.api)
        if self.adapter is None:
            raise ValueError(f"No provider adapter registered for api: {self.provider_model.api}")
        if self.adapter.api != self.provider_model.api:
            raise ValueError(f"Mismatched provider adapter api: {self.adapter.api} expected {self.provider_model.api}")

    @property
    def profile(self) -> ProviderProfile:
        metadata = {
            "api": self.provider_model.api,
            "base_url": self.provider_model.base_url,
            **self.provider_model.metadata,
        }
        return ProviderProfile(
            name=self.provider_model.provider,
            model=self.provider_model.model,
            capabilities=self.provider_model.capabilities,
            metadata=metadata,
        )

    async def generate(self, request: ProviderRequest) -> ProviderResponse:
        adapter = self.adapter
        if adapter is None:
            raise ValueError(f"No provider adapter registered for api: {self.provider_model.api}")
        return await adapter.generate(self.provider_model, request, self.options)

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        adapter = self.adapter
        if adapter is None:
            raise ValueError(f"No provider adapter registered for api: {self.provider_model.api}")
        async for event in adapter.stream(self.provider_model, request, self.options):
            yield event


@dataclass
class RegisteredProviderAdapter:
    adapter: ProviderAdapter
    source_id: str | None = None


_ADAPTERS: dict[str, RegisteredProviderAdapter] = {}


def register_provider_adapter(adapter: ProviderAdapter, *, source_id: str | None = None) -> None:
    if not getattr(adapter, "api", ""):
        raise ValueError("provider adapter api cannot be empty")
    _ADAPTERS[adapter.api] = RegisteredProviderAdapter(adapter=adapter, source_id=source_id)


def get_provider_adapter(api: str) -> ProviderAdapter | None:
    entry = _ADAPTERS.get(api)
    return entry.adapter if entry else None


def get_provider_adapters() -> list[ProviderAdapter]:
    return [entry.adapter for entry in _ADAPTERS.values()]


def unregister_provider_adapters(source_id: str) -> None:
    for api, entry in list(_ADAPTERS.items()):
        if entry.source_id == source_id:
            del _ADAPTERS[api]


def clear_provider_adapters() -> None:
    _ADAPTERS.clear()
