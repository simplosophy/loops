"""Channel contracts and default channel profiles."""

from __future__ import annotations

import asyncio
import builtins
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from loops.loop0.events import AgentEvent
from loops.loop0.logging import format_duration_ms, format_tool_arguments_lines, preview_text
from loops.loop0.profiles import ChannelContext, ChannelProfile
from loops.loop0.types import UserInput

try:
    # Importing readline lets Python's input() use readline/libedit line editing
    # on real terminals, which handles UTF-8 characters as characters rather
    # than bytes when editing input.
    import readline as _readline  # noqa: F401
except ImportError:  # pragma: no cover - platform dependent
    _readline = None


class Channel:
    profile: ChannelProfile

    async def receive(self) -> AsyncIterator[UserInput]:
        if False:
            yield UserInput("")

    async def send(self, event: AgentEvent) -> None:
        del event

    def default_context(self) -> ChannelContext:
        return ChannelContext(channel_name=self.profile.name)


@dataclass
class InMemoryChannel(Channel):
    profile: ChannelProfile
    events: list[AgentEvent] = field(default_factory=list)

    async def send(self, event: AgentEvent) -> None:
        self.events.append(event)


class TuiChannel(InMemoryChannel):
    def __init__(self) -> None:
        super().__init__(
            ChannelProfile(
                name="tui",
                interactive=True,
                duplex="half",
                output_mode="stream",
                supports_interrupt=True,
                supports_questions=True,
                supports_approval=True,
                delivery="ephemeral",
            )
        )


class ConsoleChannel(TuiChannel):
    """Default terminal channel.

    It is interactive, half-duplex, supports provider streaming, writes deltas
    to stdout immediately, and reads user input from stdin.
    """

    def __init__(
        self,
        *,
        prompt: str = "loops> ",
        show_events: bool = False,
        input_stream: Any | None = None,
        output_stream: Any | None = None,
    ) -> None:
        super().__init__()
        self.profile = ChannelProfile(
            name="console",
            interactive=True,
            duplex="half",
            output_mode="stream",
            supports_interrupt=True,
            supports_questions=True,
            supports_approval=True,
            delivery="ephemeral",
        )
        self.prompt = prompt
        self.show_events = show_events
        self.input_stream = input_stream or sys.stdin
        self.output_stream = output_stream or sys.stdout
        self.saw_delta = False

    async def receive(self) -> AsyncIterator[UserInput]:
        while True:
            line = await asyncio.to_thread(self._read_line)
            if line is None:
                break
            text = line.strip()
            if not text:
                continue
            if text in {"/exit", "/quit"}:
                break
            yield UserInput(text=text)

    def _read_line(self) -> str | None:
        if self._uses_default_stdio():
            try:
                return builtins.input(self.prompt)
            except EOFError:
                return None
        if self.prompt:
            self.output_stream.write(self.prompt)
            self.output_stream.flush()
        line = self.input_stream.readline()
        if line == "":
            return None
        return str(line)

    def _uses_default_stdio(self) -> bool:
        return self.input_stream is sys.stdin and self.output_stream is sys.stdout

    async def send(self, event: AgentEvent) -> None:
        await super().send(event)
        if event.type == "provider_delta":
            self.saw_delta = True
            self.output_stream.write(str(event.payload.get("text") or ""))
            self.output_stream.flush()
            return
        if event.type == "tool_started":
            self.output_stream.write(_format_tool_started(event.payload))
            self.output_stream.flush()
            return
        if event.type == "tool_finished":
            self.output_stream.write(_format_tool_finished(event.payload))
            self.output_stream.flush()
            return
        if self.show_events:
            self.output_stream.write(f"\n[event] {event.type}\n")
            self.output_stream.flush()


class LarkChannel(InMemoryChannel):
    def __init__(self, *, metadata: dict[str, Any] | None = None) -> None:
        super().__init__(
            ChannelProfile(
                name="lark",
                interactive=True,
                duplex="full",
                output_mode="message",
                supports_interrupt=True,
                supports_questions=True,
                supports_approval=True,
                delivery="persistent",
                metadata=metadata or {},
            )
        )


class ScheduledChannel(InMemoryChannel):
    def __init__(self, *, output_mode: str = "message", metadata: dict[str, Any] | None = None) -> None:
        super().__init__(
            ChannelProfile(
                name="scheduled",
                interactive=False,
                duplex="half",
                output_mode=output_mode,  # type: ignore[arg-type]
                supports_interrupt=False,
                supports_questions=False,
                supports_approval=False,
                delivery="persistent",
                metadata=metadata or {},
            )
        )


def _format_tool_started(payload: dict[str, Any]) -> str:
    tool_name = str(payload.get("tool_name") or "tool")
    call_id = str(payload.get("tool_call_id") or "")
    arguments = payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {}
    lines = [f"\n\n[tool] {tool_name} started"]
    if call_id:
        lines[0] += f" ({call_id})"
    for line in format_tool_arguments_lines(tool_name, arguments):
        lines.append(f"  {line}")
    return "\n".join(lines) + "\n"


def _format_tool_finished(payload: dict[str, Any]) -> str:
    tool_name = str(payload.get("tool_name") or "tool")
    call_id = str(payload.get("tool_call_id") or "")
    status = str(payload.get("status") or "done")
    duration = format_duration_ms(payload.get("duration_ms"))
    header = f"[tool] {tool_name} {status} in {duration}"
    if call_id:
        header += f" ({call_id})"

    lines = [header]
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    if "returncode" in metadata:
        lines.append(f"  returncode: {metadata.get('returncode')}")
    if "session_id" in metadata:
        lines.append(f"  session_id: {metadata.get('session_id')}")
    if error := payload.get("error"):
        lines.append("  error:")
        lines.extend(_indent_block(preview_text(error, max_chars=1200), prefix="    "))
    elif output := payload.get("output"):
        lines.append("  output:")
        lines.extend(_indent_block(preview_text(output, max_chars=1200), prefix="    "))
    return "\n".join(lines) + "\n\n"


def _indent_block(text: Any, *, prefix: str) -> list[str]:
    value = str(text)
    if not value:
        return [prefix.rstrip()]
    return [prefix + line for line in value.splitlines()]
