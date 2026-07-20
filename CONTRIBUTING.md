# Contributing to loops

Thanks for your interest in improving the Human Loop Protocol (HLP) reference
SDK. This document describes the development workflow and the project's
engineering conventions.

## Development setup

Requirements: Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/simplosophy/loops.git
cd loops
uv sync --group dev
```

## Checks

All of these run in CI and must pass before a change is merged:

```bash
uv run pytest tests/              # test suite (offline by default)
uv run ruff check .               # lint
uv run ruff format --check .      # formatting
uv run mypy loops                 # type checking
uv run pytest --cov               # coverage report
uv run scripts/check_release_metadata.py   # release metadata consistency
uv run scripts/check_spec_site_sync.py     # spec <-> docs site sync
```

Installing [pre-commit](https://pre-commit.com) hooks runs lint, format, and
type checks on every commit:

```bash
uv tool install pre-commit
pre-commit install
```

## Testing conventions

- Tests live in `tests/` and must run offline. Tests that require real CLI
  binaries belong in `tests/external/` and must be gated behind
  `HLP_RUN_EXTERNAL_CLI_E2E=1`.
- Executable conformance profiles (`HLP-compatible`, `HLP-integrated`,
  `HLP-industrial` reference slice) live in `tests/conformance/`. Spec-visible
  behavior changes must keep these green and extend them when new protocol
  surface is added.
- Bug fixes come with a regression test; features come with coverage of the
  new behavior.

## Project conventions

See `AGENTS.md` for the design principles (simplicity, orthogonality, layered
architecture, fail-fast, convention over configuration) and the HLP ownership
boundary — HLP owns task/checkpoint/artifact/review/ledger/audit semantics, it
does not own model providers, tool calling, planning loops, or UI delivery.

- **Architecture**: `docs/architecture/OVERVIEW.md` is the source of truth.
  Changes that alter the architecture must update the docs and be called out
  explicitly in the pull request.
- **Plans and notes**: larger changes are planned in `docs/plans/` and recorded
  by date in `docs/notes/yyyy-MM-dd.md`.
- **Commits**: English, conventional-commit style (`feat:`, `fix:`, `chore:`,
  `docs:`, `refactor:`, `test:`), describing the *why* as well as the *what*.
- **Spec changes**: protocol semantics live in `docs/specs/HLP.md`. The
  VitePress copy under `docs/site/specs/` must stay in sync;
  `scripts/check_spec_site_sync.py` guards the shared status facts.

## Reporting bugs and proposing features

Open an issue at https://github.com/simplosophy/loops/issues using the bug
report or feature request template. Please include a minimal reproduction for
bugs, and the protocol boundary rationale for spec-affecting proposals.

## Security

Please do not report security vulnerabilities through public issues. See
`SECURITY.md` for the reporting process.

## License

By contributing, you agree that your contributions are licensed under the
Apache License 2.0 (see `LICENSE`).
