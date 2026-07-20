from __future__ import annotations

from .codex import CodexHarnessAdapter
from .process import ProcessAgentAdapter, PromptCLIAdapter
from .protocol import HarnessCapabilities, ProcessRunner


class PiHarnessAdapter(CodexHarnessAdapter):
    """Pi CLI adapter with HLP harness event projection.

    Pi keeps its own execution model. Current first-party Pi CLI is invoked as
    ``pi --mode json -p --no-session <prompt>`` (not ``pi run --json``). The
    adapter appends the HLP operation prompt as the final argument and projects
    explicit ``pi`` / ``hlp`` human-loop payloads from JSON or JSONL stdout into
    HLP checkpoints and artifacts.
    """

    def __init__(
        self,
        command: tuple[str, ...] = (
            "pi",
            "--mode",
            "json",
            "-p",
            "--no-session",
        ),
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
        capabilities: HarnessCapabilities | None = None,
        prompt_mode: str = "protocol",
    ) -> None:
        super().__init__(
            command=command,
            runner=runner,
            timeout=timeout,
            capabilities=capabilities
            or HarnessCapabilities(
                name="pi",
                conformance=("checkpoint-capable", "artifact-aware", "event-streaming"),
                description="Projects Pi harness JSON events into HLP human-loop objects.",
            ),
            prompt_mode=prompt_mode,
        )
        self.name = "pi-harness"


class ClaudeCodeCLIAdapter(PromptCLIAdapter):
    def __init__(
        self,
        command: tuple[str, ...] = (
            "claude",
            "-p",
            "--output-format",
            "json",
            "--permission-mode",
            "dontAsk",
        ),
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(command, name="claude-code-cli", runner=runner, timeout=timeout)


class KimiCLIAdapter(PromptCLIAdapter):
    def __init__(
        self,
        command: tuple[str, ...] = ("kimi", "--output-format", "text", "-p"),
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(command, name="kimi-cli", runner=runner, timeout=timeout)


class HermsCLIAdapter(ProcessAgentAdapter):
    def __init__(
        self,
        command: tuple[str, ...] = ("herms", "run"),
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(command, name="herms-cli", runner=runner, timeout=timeout)


HermesCLIAdapter = HermsCLIAdapter
