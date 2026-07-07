from __future__ import annotations

from dataclasses import dataclass

from .commands import COMMANDS, CommandDefinition

COMPATIBILITY_TARGETS: dict[str, CommandDefinition] = {
    "login": CommandDefinition(
        "login",
        "Authenticate and establish human credentials.",
        "compat",
        covered=False,
    ),
    "doctor": CommandDefinition(
        "doctor",
        "Run environment and network diagnostics.",
        "compat",
        covered=False,
    ),
}


@dataclass(frozen=True)
class CompatibilityReport:
    total: int
    covered: int
    coverage: float
    commands: tuple[str, ...]


def compatibility_report() -> CompatibilityReport:
    catalog = {**COMMANDS, **COMPATIBILITY_TARGETS}
    commands = tuple(f"/{name}" for name in sorted(catalog))
    total = len(catalog)
    covered = sum(1 for command in catalog.values() if command.covered)
    return CompatibilityReport(
        total=total,
        covered=covered,
        coverage=covered / total,
        commands=commands,
    )
