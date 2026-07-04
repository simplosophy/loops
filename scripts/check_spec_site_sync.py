#!/usr/bin/env python3
"""Lightweight token sync check between source HLP spec and site spec."""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SPEC = ROOT / "docs/specs/HLP.md"
SITE_SPEC = ROOT / "docs/site/specs/hlp.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def has_literal(token: str) -> Callable[[str], bool]:
    return lambda text: token in text


def has_23_operations(text: str) -> bool:
    if "23 operations" in text or "23 个" in text:
        return True
    operations = set(re.findall(r"`([a-z]+\.[a-z]+)`", text))
    return len(operations) >= 23


def has_adapter_steer(text: str) -> bool:
    normalized = text.lower()
    has_adapter_boundary = (
        "agentadapter" in normalized
        or "agent adapter" in normalized
        or "agent.steer" in normalized
        or "adapter action" in normalized
    )
    return has_adapter_boundary and "steer" in normalized


CHECKS: list[tuple[str, Callable[[str], bool]]] = [
    ("Version 0.2.0-draft", has_literal("0.2.0-draft")),
    ("23 operations", has_23_operations),
    ("task.interrupt", has_literal("task.interrupt")),
    ("task.amend", has_literal("task.amend")),
    ("PermissionGrant", has_literal("PermissionGrant")),
    ("proposed_actions", has_literal("proposed_actions")),
    ("state_patch", has_literal("state_patch")),
    ("Review.kind", has_literal("Review.kind")),
    ("AgentAdapter steer", has_adapter_steer),
    ("ProtocolError wire object", has_literal("ProtocolError")),
    ("schema_version", has_literal("schema_version")),
]


def main() -> int:
    source = read(SOURCE_SPEC)
    site = read(SITE_SPEC)
    errors: list[str] = []

    for label, predicate in CHECKS:
        source_has = predicate(source)
        site_has = predicate(site)
        if not source_has or not site_has:
            missing = []
            if not source_has:
                missing.append(str(SOURCE_SPEC.relative_to(ROOT)))
            if not site_has:
                missing.append(str(SITE_SPEC.relative_to(ROOT)))
            errors.append(f"- {label}: missing or unsynced in {', '.join(missing)}")

    if errors:
        print("Spec/site sync check failed:")
        print("\n".join(errors))
        return 1

    print("Spec/site sync check passed for HLP 0.2.0 draft tokens.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
