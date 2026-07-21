from __future__ import annotations

from .process import ProcessAgentAdapter
from .protocol import ProcessRunner


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
