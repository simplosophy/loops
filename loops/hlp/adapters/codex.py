from __future__ import annotations

import atexit
import json
import os
import tempfile

from . import _parsing as parsing
from ._harness import HarnessAdapterBase
from .process import PromptCLIAdapter
from .protocol import HarnessCapabilities, ProcessRunner

_DEFAULT_CLI_COMMAND: tuple[str, ...] = (
    "codex",
    "exec",
    "--sandbox",
    "read-only",
    "--ephemeral",
)
_DEFAULT_HARNESS_COMMAND: tuple[str, ...] = (
    "codex",
    "exec",
    "--json",
    "--sandbox",
    "read-only",
    "--ephemeral",
)

_schema_file_path: str | None = None


def _unlink_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _hlp_result_schema_path() -> str:
    """Write the HLP result envelope schema once per process (codex --output-schema)."""
    global _schema_file_path
    if _schema_file_path is not None and os.path.exists(_schema_file_path):
        return _schema_file_path
    fd, path = tempfile.mkstemp(prefix="hlp-result-schema-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(parsing.HLP_RESULT_SCHEMA, handle)
    atexit.register(_unlink_quietly, path)
    _schema_file_path = path
    return path


class CodexCLIAdapter(PromptCLIAdapter):
    def __init__(
        self,
        command: tuple[str, ...] = _DEFAULT_CLI_COMMAND,
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
    ) -> None:
        if command is _DEFAULT_CLI_COMMAND:
            # Protocol-only adapter: enforce the result envelope natively.
            command = (*command, "--output-schema", _hlp_result_schema_path())
        super().__init__(command, name="codex-cli", runner=runner, timeout=timeout)


class CodexHarnessAdapter(HarnessAdapterBase):
    """Codex CLI adapter with HLP harness event projection.

    Codex keeps its own execution model. This adapter only provides the HLP
    boundary: prompt-mode command execution plus projection of explicit
    human-loop events from Codex JSONL stdout.
    """

    def __init__(
        self,
        command: tuple[str, ...] = _DEFAULT_HARNESS_COMMAND,
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
        capabilities: HarnessCapabilities | None = None,
        prompt_mode: str = "protocol",
        session_continuity: bool = True,
    ) -> None:
        if command is _DEFAULT_HARNESS_COMMAND:
            if session_continuity:
                # --ephemeral sessions are not recorded and cannot be resumed.
                command = tuple(part for part in command if part != "--ephemeral")
            if prompt_mode == "protocol":
                # Enforce the HLP result envelope natively; chat mode stays free-form.
                command = (*command, "--output-schema", _hlp_result_schema_path())
        super().__init__(
            command,
            name="codex-harness",
            runner=runner,
            timeout=timeout,
            capabilities=capabilities
            or HarnessCapabilities(
                name="codex",
                conformance=("checkpoint-capable", "artifact-aware", "event-streaming"),
                description="Projects Codex CLI JSON events into HLP human-loop objects.",
            ),
            prompt_mode=prompt_mode,
            session_continuity=session_continuity,
        )

    def _resume_command(self, session_id: str, prompt: str) -> tuple[str, ...]:
        """codex exec resume [options] <thread_id> [prompt] (options come first)."""
        command: tuple[str, ...] = ("codex", "exec", "resume")
        if "--json" in self.command:
            command = (*command, "--json")
        if "--output-schema" in self.command:
            index = self.command.index("--output-schema")
            command = (*command, "--output-schema", self.command[index + 1])
        return (*command, session_id, prompt)
