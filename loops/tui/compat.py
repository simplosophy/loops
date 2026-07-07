from __future__ import annotations

from dataclasses import dataclass

from .commands import COMMANDS


@dataclass(frozen=True)
class CompatibilityReport:
    total: int
    covered: int
    coverage: float
    commands: tuple[str, ...]


def compatibility_report() -> CompatibilityReport:
    commands = tuple(f"/{name}" for name in sorted(COMMANDS))
    total = len(COMMANDS)
    covered = sum(1 for command in COMMANDS.values() if command.covered)
    return CompatibilityReport(
        total=total,
        covered=covered,
        coverage=covered / total,
        commands=commands,
    )
