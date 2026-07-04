#!/usr/bin/env python3
"""Offline release metadata checks for the HLP 0.2.0 draft line."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.2.0"
EXPECTED_SPEC_VERSION = "0.2.0-draft"
EXPECTED_SCHEMA_VERSION = "0.2"
EXPECTED_PROFILE = "HLP-industrial"
EXPECTED_CNAME = "ontheloops.com"


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def fail(errors: list[str], message: str) -> None:
    errors.append(f"- {message}")


def status_flags(text: str) -> set[str]:
    normalized = re.sub(r"\s+", " ", text).lower()
    flags: set[str] = set()
    if EXPECTED_SPEC_VERSION in normalized:
        flags.add("version")
    if "draft" in normalized:
        flags.add("draft")
    if "reference implementation" in normalized or "参考实现" in normalized:
        flags.add("reference")
    if "conformance suite" in normalized:
        flags.add("conformance-suite")
    return flags


def main() -> int:
    errors: list[str] = []

    pyproject = tomllib.loads(read_text("pyproject.toml"))
    py_version = pyproject.get("project", {}).get("version")
    if py_version != EXPECTED_VERSION:
        fail(
            errors,
            f"pyproject.toml project.version is {py_version!r}; expected {EXPECTED_VERSION!r}",
        )

    package = json.loads(read_text("package.json"))
    package_version = package.get("version")
    if package_version != EXPECTED_VERSION:
        fail(
            errors,
            f"package.json version is {package_version!r}; expected {EXPECTED_VERSION!r}",
        )

    package_lock = json.loads(read_text("package-lock.json"))
    lock_versions = {
        "package-lock.json version": package_lock.get("version"),
        "package-lock.json packages[''].version": (
            package_lock.get("packages", {}).get("", {}).get("version")
        ),
    }
    for label, version in lock_versions.items():
        if version != EXPECTED_VERSION:
            fail(errors, f"{label} is {version!r}; expected {EXPECTED_VERSION!r}")

    sys.path.insert(0, str(ROOT))
    try:
        from loops.hlp import HLP_PROFILE, HLP_SCHEMA_VERSION, HLP_SPEC_VERSION
    except Exception as exc:  # pragma: no cover - diagnostic path
        fail(errors, f"could not import HLP version constants: {exc}")
    else:
        if HLP_SPEC_VERSION != EXPECTED_SPEC_VERSION:
            fail(
                errors,
                f"loops.hlp.HLP_SPEC_VERSION is {HLP_SPEC_VERSION!r}; expected {EXPECTED_SPEC_VERSION!r}",
            )
        if HLP_SCHEMA_VERSION != EXPECTED_SCHEMA_VERSION:
            fail(
                errors,
                f"loops.hlp.HLP_SCHEMA_VERSION is {HLP_SCHEMA_VERSION!r}; expected {EXPECTED_SCHEMA_VERSION!r}",
            )
        if HLP_PROFILE != EXPECTED_PROFILE:
            fail(
                errors,
                f"loops.hlp.HLP_PROFILE is {HLP_PROFILE!r}; expected {EXPECTED_PROFILE!r}",
            )

    cname = read_text("docs/site/public/CNAME").strip()
    if cname != EXPECTED_CNAME:
        fail(
            errors,
            f"docs/site/public/CNAME is {cname!r}; expected {EXPECTED_CNAME!r}",
        )

    source_spec = read_text("docs/specs/HLP.md")
    site_spec = read_text("docs/site/specs/hlp.md")
    expected_flags = {"version", "draft", "reference", "conformance-suite"}
    for label, text in (
        ("docs/specs/HLP.md", source_spec),
        ("docs/site/specs/hlp.md", site_spec),
    ):
        missing = sorted(expected_flags - status_flags(text))
        if missing:
            fail(
                errors,
                f"{label} does not express required 0.2.0 status facts: {', '.join(missing)}",
            )

    if status_flags(source_spec) != status_flags(site_spec):
        fail(
            errors,
            "docs/specs/HLP.md and docs/site/specs/hlp.md express different 0.2.0 status facts",
        )

    if errors:
        print("Release metadata check failed:")
        print("\n".join(errors))
        return 1

    print("Release metadata check passed for HLP 0.2.0 draft metadata.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
