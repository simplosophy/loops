from __future__ import annotations

from ._harness import HarnessAdapterBase
from .process import PromptCLIAdapter
from .protocol import HarnessCapabilities, ProcessRunner


class KimiCLIAdapter(PromptCLIAdapter):
    def __init__(
        self,
        command: tuple[str, ...] = ("kimi", "--output-format", "text", "-p"),
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
        prompt_mode: str = "protocol",
    ) -> None:
        super().__init__(
            command,
            name="kimi-cli",
            runner=runner,
            timeout=timeout,
            prompt_mode=prompt_mode,
        )


class KimiHarnessAdapter(HarnessAdapterBase):
    """Kimi CLI adapter with HLP harness event projection.

    Invoked as ``kimi --output-format stream-json -p <prompt>``. Kimi emits
    ``{"role":"assistant","content":...}`` replies plus ``role:"meta"`` lines;
    HLP result and human-loop payloads ride inside the assistant content text
    per the prompt contract and are extracted by the shared JSONL machinery.
    With session continuity (default), follow-up ops resume the native session
    via ``kimi --session <id>``.
    """

    def __init__(
        self,
        command: tuple[str, ...] = ("kimi", "--output-format", "stream-json", "-p"),
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
        capabilities: HarnessCapabilities | None = None,
        prompt_mode: str = "protocol",
        session_continuity: bool = True,
    ) -> None:
        super().__init__(
            command=command,
            name="kimi-harness",
            runner=runner,
            timeout=timeout,
            capabilities=capabilities
            or HarnessCapabilities(
                name="kimi",
                conformance=("checkpoint-capable", "artifact-aware", "event-streaming"),
                description="Projects Kimi stream-json events into HLP human-loop objects.",
            ),
            prompt_mode=prompt_mode,
            session_continuity=session_continuity,
        )

    def _resume_command(self, session_id: str, prompt: str) -> tuple[str, ...]:
        return ("kimi", "--output-format", "stream-json", "--session", session_id, "-p", prompt)

    def _fork_command(self, session_id: str, prompt: str) -> tuple[str, ...] | None:
        # Kimi has no native session-fork; handoff stays one-shot with the
        # structured context in the envelope.
        return None
