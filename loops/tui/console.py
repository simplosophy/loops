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
        """Read one logical input; a trailing backslash continues onto the
        next line (multi-line prompts), joined with real newlines."""
        interactive = _readline is not None and sys.stdin.isatty()
        if interactive:
            first = input(prompt)
        else:
            # Non-interactive (piped stdin): plain line reads without echoing
            # readline control sequences into the transcript.
            raw = sys.stdin.readline()
            if not raw:
                raise EOFError
            first = raw.rstrip("\n")
        lines = [first]
        while lines[-1].endswith("\\"):
            lines[-1] = lines[-1][:-1]
            if interactive:
                lines.append(input("... "))
                continue
            raw = sys.stdin.readline()
            if not raw:
                break
            lines.append(raw.rstrip("\n"))
        return "\n".join(lines)

    def _complete(self, text: str, state: int) -> str | None:
        assert _readline is not None
        buffer = _readline.get_line_buffer()
        candidates = completion_candidates(
            buffer,
            completer_extra=self._completer_extra,
        )
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


def completion_candidates(
    buffer: str,
    *,
    completer_extra: Callable[[str], list[str]] | None = None,
) -> list[str]:
    """Pure completion logic (platform-independent, testable everywhere)."""
    if not buffer.startswith("/"):
        return []
    head, _, arg = buffer[1:].partition(" ")
    if not arg:
        return [f"/{name}" for name in COMMANDS if name.startswith(head)]
    extra = completer_extra(head) if completer_extra else []
    return [word for word in extra if word.startswith(arg)]


def adapter_completions(prefix: str = "") -> list[str]:
    """Completion words for /adapter arguments."""
    return [name for name in ("codex", "pi", "claude", "kimi", "fake") if name.startswith(prefix)]
