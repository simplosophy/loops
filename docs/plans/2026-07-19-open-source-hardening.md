# Open-Source Hardening Plan

Date: 2026-07-19
Status: done (see docs/notes/2026-07-19.md)

## Goal

Bring `loops` (HLP spec + reference SDK) to industrial-grade open-source
readiness: legal clarity, complete packaging metadata, enforced code-quality
toolchain, hardened CI/CD with releases, and standard community files.

## Non-goals

- No protocol changes (HLP / HLP-realtime spec semantics stay untouched).
- No public API renames; `HermesCLIAdapter`/`HermsCLIAdapter` alias stays.
- No split of `loops/hlp/operations.py` (tracked as follow-up; too risky to
  bundle with release-readiness work).
- No git history rewrite (author email, historical session file stay as-is).

## Work items

1. **Legal/metadata**: add `LICENSE` (Apache-2.0); complete `pyproject.toml`
   (license, authors, keywords, classifiers, project URLs); ship `py.typed`
   markers (PEP 561); expose `loops.__version__`.
2. **Toolchain**: ruff (lint + format), mypy, pytest + coverage config in
   `pyproject.toml`; `.pre-commit-config.yaml`; `.git-blame-ignore-revs` for
   the one-time format pass.
3. **CI/CD**: harden `ci.yml` (lint, typecheck, coverage, OS matrix);
   add tag-triggered PyPI release workflow (trusted publishing);
   dependabot for GitHub Actions; issue/PR templates.
4. **Community**: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`,
   `CHANGELOG.md`; README badges.
5. **Code hygiene**: fix stale `.env.example`; translate remaining Chinese
   comments in `loops/` source to English for international contributors.
6. **Records**: dated note in `docs/notes/2026-07-19.md`; commit per repo
   conventions.

## Validation

- `uv run pytest tests/ -q` stays green (baseline: 232 passed, 2 skipped).
- `uv run ruff check` and `uv run ruff format --check` clean.
- `uv run mypy loops` clean under the configured settings.
- Coverage report generated on core `loops/hlp` modules.
