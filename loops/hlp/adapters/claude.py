from __future__ import annotations

import json

from . import _parsing as parsing
from ._harness import HarnessAdapterBase
from .process import PromptCLIAdapter
from .protocol import HarnessCapabilities, ProcessRunner


def _with_json_schema(command: tuple[str, ...], prompt_mode: str) -> tuple[str, ...]:
    """Append Claude Code's native structured-output flag in protocol mode."""
    if prompt_mode != "protocol":
        return command
    schema = json.dumps(parsing.HLP_RESULT_SCHEMA, separators=(",", ":"))
    return (*command, "--json-schema", schema)


_DEFAULT_CLAUDE_CLI_COMMAND: tuple[str, ...] = (
    "claude",
    "-p",
    "--output-format",
    "json",
    "--permission-mode",
    "dontAsk",
)
_DEFAULT_CLAUDE_HARNESS_COMMAND: tuple[str, ...] = (
    "claude",
    "-p",
    "--output-format",
    "stream-json",
    "--verbose",
    "--permission-mode",
    "dontAsk",
    "--no-session-persistence",
)


class ClaudeCodeCLIAdapter(PromptCLIAdapter):
    def __init__(
        self,
        command: tuple[str, ...] = _DEFAULT_CLAUDE_CLI_COMMAND,
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
        prompt_mode: str = "protocol",
    ) -> None:
        if command is _DEFAULT_CLAUDE_CLI_COMMAND:
            command = _with_json_schema(command, prompt_mode)
        super().__init__(
            command,
            name="claude-code-cli",
            runner=runner,
            timeout=timeout,
            prompt_mode=prompt_mode,
        )


class ClaudeCodeHarnessAdapter(HarnessAdapterBase):
    """Claude Code CLI adapter with HLP harness event projection.

    Invoked as ``claude -p --output-format stream-json --verbose
    --permission-mode dontAsk [--json-schema S] <prompt>``. Claude Code emits
    ``system`` / ``assistant`` / ``result`` JSONL events; HLP result and
    human-loop payloads ride inside the assistant/result text per the prompt
    contract and are extracted by the shared JSONL machinery. In protocol mode
    the result envelope is enforced natively via ``--json-schema``; chat mode
    stays free-form. With session continuity (default), sessions persist and
    follow-up ops resume them via ``claude --resume <id>``.
    """

    def __init__(
        self,
        command: tuple[str, ...] = _DEFAULT_CLAUDE_HARNESS_COMMAND,
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
        capabilities: HarnessCapabilities | None = None,
        prompt_mode: str = "protocol",
        session_continuity: bool = True,
    ) -> None:
        if command is _DEFAULT_CLAUDE_HARNESS_COMMAND:
            if session_continuity:
                # Sessions must persist to be resumable.
                command = tuple(part for part in command if part != "--no-session-persistence")
            command = _with_json_schema(command, prompt_mode)
        elif session_continuity:
            command = tuple(part for part in command if part != "--no-session-persistence")
        super().__init__(
            command=command,
            name="claude-code-harness",
            runner=runner,
            timeout=timeout,
            capabilities=capabilities
            or HarnessCapabilities(
                name="claude",
                conformance=("checkpoint-capable", "artifact-aware", "event-streaming"),
                description=(
                    "Projects Claude Code stream-json events into HLP human-loop objects."
                ),
            ),
            prompt_mode=prompt_mode,
            session_continuity=session_continuity,
        )

    def _resume_command(self, session_id: str, prompt: str) -> tuple[str, ...]:
        command: tuple[str, ...] = (
            "claude",
            "--resume",
            session_id,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "dontAsk",
        )
        if self.prompt_mode == "protocol" and "--json-schema" in self.command:
            index = self.command.index("--json-schema")
            command = (*command, "--json-schema", self.command[index + 1])
        return (*command, prompt)

    def _fork_command(self, session_id: str, prompt: str) -> tuple[str, ...] | None:
        # claude --resume <src> --fork-session: new session id with full history.
        command: tuple[str, ...] = (
            "claude",
            "--resume",
            session_id,
            "--fork-session",
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "dontAsk",
        )
        if self.prompt_mode == "protocol" and "--json-schema" in self.command:
            index = self.command.index("--json-schema")
            command = (*command, "--json-schema", self.command[index + 1])
        return (*command, prompt)
