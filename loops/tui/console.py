"""Interactive console layer for the HLP TUI: readline input, history,
tab completion, and minimal ANSI color. Stdlib only — no new dependencies.

Color is disabled when the output is not a TTY, when `NO_COLOR` is set, or
when the host passes ``color=False``.
"""

from __future__ import annotations

import atexit
import os
import sys
from collections.abc import Callable
from pathlib import Path

from .commands import COMMANDS

try:  # readline gives Emacs-style editing, arrow keys, and history.
    import readline as _readline
except ImportError:  # pragma: no cover - non-POSIX fallback
    _readline = None  # type: ignore[assignment]

_HISTORY_LIMIT = 1000

_CODES = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "cyan": "\033[36m",
}
_ROLES = {
    "user": "bold",
    "agent": "cyan",
    "task": "blue",
    "error": "red",
    "warn": "yellow",
    "ok": "green",
    "dim": "dim",
    "accent": "bold",
}


class Console:
    """TTY input/output: readline editing + history + completion + color."""

    def __init__(
        self,
        *,
        history_path: str | Path | None = None,
        color: bool = True,
        completer_extra: Callable[[str], list[str]] | None = None,
    ) -> None:
        self.color = color and sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        self._history_path = Path(history_path) if history_path else None
        self._completer_extra = completer_extra
        if _readline is not None:
            _readline.set_completer(self._complete)
            _readline.parse_and_bind("tab: complete")
            _readline.set_completer_delims(" ")
            if self._history_path is not None and self._history_path.exists():
                try:
                    _readline.read_history_file(str(self._history_path))
                except OSError:
                    pass
            atexit.register(self._save_history)

    # ── input ──

    def input(self, prompt: str = "> ") -> str:
        if _readline is not None and sys.stdin.isatty():
            return input(prompt)
        # Non-interactive (piped stdin): plain line reads without echoing
        # readline control sequences into the transcript.
        line = sys.stdin.readline()
        if not line:
            raise EOFError
        return line.rstrip("\n")

    def _complete(self, text: str, state: int) -> str | None:
        assert _readline is not None
        buffer = _readline.get_line_buffer()
        if buffer.startswith("/"):
            head, _, arg = buffer[1:].partition(" ")
            if not arg:
                candidates = [f"/{name}" for name in COMMANDS if name.startswith(head)]
            else:
                command, _, partial = buffer[1:].partition(" ")
                extra = self._completer_extra(command) if self._completer_extra else []
                candidates = [word for word in extra if word.startswith(partial)]
        else:
            candidates = []
        try:
            return candidates[state] if state < len(candidates) else None
        except IndexError:
            return None

    def _save_history(self) -> None:
        if _readline is None or self._history_path is None:
            return
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            _readline.set_history_length(_HISTORY_LIMIT)
            _readline.write_history_file(str(self._history_path))
        except OSError:
            pass

    # ── output ──

    def style(self, text: str, role: str) -> str:
        if not self.color:
            return text
        code = _CODES.get(_ROLES.get(role, "reset"), _CODES["reset"])
        return f"{code}{text}{_CODES['reset']}"

    def print(self, text: str, *, role: str | None = None, end: str = "\n") -> None:
        print(self.style(text, role) if role else text, end=end, flush=True)


def adapter_completions(prefix: str = "") -> list[str]:
    """Completion words for /adapter arguments."""
    return [name for name in ("codex", "pi", "claude", "kimi", "fake") if name.startswith(prefix)]
