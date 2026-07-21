from __future__ import annotations

from ._harness import HarnessAdapterBase
from .protocol import HarnessCapabilities, ProcessRunner

_DEFAULT_PI_HARNESS_COMMAND: tuple[str, ...] = (
    "pi",
    "--mode",
    "json",
    "-p",
    "--no-session",
)


class PiHarnessAdapter(HarnessAdapterBase):
    """Pi CLI adapter with HLP harness event projection.

    Pi keeps its own execution model. Current first-party Pi CLI is invoked as
    ``pi --mode json -p [--no-session] <prompt>`` (not ``pi run --json``). The
    adapter appends the HLP operation prompt as the final argument and projects
    explicit ``pi`` / ``hlp`` human-loop payloads from JSON or JSONL stdout into
    HLP checkpoints and artifacts. With session continuity (default), follow-up
    ops resume the native session via ``pi --session <id>`` and ``--no-session``
    is dropped so the session is recorded.
    """

    def __init__(
        self,
        command: tuple[str, ...] = _DEFAULT_PI_HARNESS_COMMAND,
        *,
        runner: ProcessRunner | None = None,
        timeout: float = 120.0,
        capabilities: HarnessCapabilities | None = None,
        prompt_mode: str = "protocol",
        session_continuity: bool = True,
    ) -> None:
        if session_continuity:
            # Sessions must be recorded to be resumable; --no-session contradicts
            # continuity and is stripped from any command, not just the default.
            command = tuple(part for part in command if part != "--no-session")
        super().__init__(
            command=command,
            name="pi-harness",
            runner=runner,
            timeout=timeout,
            capabilities=capabilities
            or HarnessCapabilities(
                name="pi",
                conformance=("checkpoint-capable", "artifact-aware", "event-streaming"),
                description="Projects Pi harness JSON events into HLP human-loop objects.",
            ),
            prompt_mode=prompt_mode,
            session_continuity=session_continuity,
        )

    def _resume_command(self, session_id: str, prompt: str) -> tuple[str, ...]:
        return ("pi", "--mode", "json", "--session", session_id, "-p", prompt)

    def _fork_command(self, session_id: str, prompt: str) -> tuple[str, ...] | None:
        # pi --fork branches the source session into a NEW session for handoff.
        return ("pi", "--mode", "json", "--fork", session_id, "-p", prompt)
