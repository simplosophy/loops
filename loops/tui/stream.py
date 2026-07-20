"""Live harness stream rendering for the HLP TUI host channel."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from loops.hlp.adapters.process import StreamChunk


@dataclass
class StreamPrinter:
    """Print harness StreamChunks to a TUI terminal with text-delta coalescing."""

    printer: Callable[..., None] = print
    _open_text: bool = field(default=False, init=False, repr=False)

    def __call__(self, chunk: StreamChunk) -> None:
        write = self.printer
        if chunk.kind == "text" and not chunk.newline:
            if not self._open_text:
                write("⋯ agent: ", end="", flush=True)
                self._open_text = True
            write(chunk.text, end="", flush=True)
            return
        if self._open_text:
            write("", flush=True)  # newline after streaming text
            self._open_text = False
        if chunk.kind == "error":
            write(f"⋯ error: {chunk.text}", flush=True)
        elif chunk.kind == "thinking":
            write(f"⋯ {chunk.text}", flush=True)
        else:
            write(f"⋯ {chunk.text}", flush=True)

    def close(self) -> None:
        if self._open_text:
            self.printer("", flush=True)
            self._open_text = False
