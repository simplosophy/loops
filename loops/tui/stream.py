"""Live harness stream rendering for the HLP TUI host channel."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from loops.hlp.adapters.process import StreamChunk


@dataclass
class StreamPrinter:
    """Print harness StreamChunks to a TUI terminal with text-delta coalescing.

    Envelope suppression: chat-mode models end replies with an HLP JSON
    envelope; humans should see the summary text, never the raw JSON. Some
    harnesses (kimi) stream the envelope as small deltas, so text starting
    with "{" is held back until it parses as complete JSON (envelope →
    summary, anything else → raw) or the stream moves on (flush raw).
    """

    printer: Callable[..., None] = print
    style: Callable[[str, str], str] | None = None
    _open_text: bool = field(default=False, init=False, repr=False)
    _pending_text: str = field(default="", init=False, repr=False)

    def _styled(self, text: str, role: str) -> str:
        return self.style(text, role) if self.style is not None else text

    def __call__(self, chunk: StreamChunk) -> None:
        if chunk.kind == "text":
            self._pending_text += chunk.text
            self._drain_text(final=False)
            return
        self._drain_text(final=True)
        if self._open_text:
            self.printer("", flush=True)  # newline after streaming text
            self._open_text = False
        if chunk.kind == "error":
            self.printer(self._styled(f"⋯ error: {chunk.text}", "error"), flush=True)
        elif chunk.kind == "thinking":
            self.printer(self._styled(f"⋯ {chunk.text}", "dim"), flush=True)
        else:
            self.printer(f"⋯ {chunk.text}", flush=True)

    def close(self) -> None:
        self._drain_text(final=True)
        if self._open_text:
            self.printer("", flush=True)
            self._open_text = False

    def _drain_text(self, *, final: bool) -> None:
        if not self._pending_text:
            return
        stripped = self._pending_text.strip()
        if stripped.startswith("{"):
            value: Any = None
            try:
                value = json.loads(stripped)
                complete = True
            except json.JSONDecodeError:
                complete = False
            if not complete:
                if not final:
                    return  # hold back: the envelope may still be streaming in
            elif isinstance(value, dict):
                summary = value.get("summary")
                if isinstance(summary, str) and ("run_id" in value or "correlation_id" in value):
                    self._pending_text = ""
                    self._write_text(summary.strip())
                    return
            # Complete non-envelope JSON (or an unparseable final buffer)
            # falls through and prints raw.
        text = self._pending_text
        self._pending_text = ""
        self._write_text(text)

    def _write_text(self, text: str) -> None:
        if not text:
            return
        if not self._open_text:
            self.printer("⋯ agent: ", end="", flush=True)
            self._open_text = True
        self.printer(text, end="", flush=True)
