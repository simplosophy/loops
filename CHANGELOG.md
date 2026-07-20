# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- First-class harness adapters for all four first-party CLIs: new
  `ClaudeCodeHarnessAdapter` (`claude -p --output-format stream-json`) and
  `KimiHarnessAdapter` (`kimi -p --output-format stream-json`) join
  `CodexHarnessAdapter` and `PiHarnessAdapter`; all four share the JSONL
  projection pipeline with reliable peek/ack delivery.
- `prompt_mode` (protocol/chat) on `ClaudeCodeCLIAdapter` and
  `KimiCLIAdapter`.
- `format_harness_stream_line` mappings for Kimi (`role=assistant`/`meta`)
  and Claude Code (`system`/`assistant`/`result`) stream-json shapes.
- TUI: `--adapter claude` and `--adapter kimi` (chat prompt mode, live
  streaming), alongside the existing codex/pi/fake.
- Harness event queue drops transport-level duplicates (Claude Code's
  `result` envelope repeats the final assistant text) via per-batch event
  signatures.
- Offline contract tests for the new adapters (full operation surface,
  projection, correlation rejection, stream formatting, TUI wiring) and Pi
  handoff/cancel coverage; the real-CLI lifecycle E2E now includes `pi`.
- Open-source readiness: Apache-2.0 `LICENSE`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, `SECURITY.md`, and this changelog.
- Packaging metadata: license expression, keywords, classifiers, project URLs,
  and the PEP 561 `py.typed` marker so downstream type checkers see the SDK's
  annotations.
- `loops.__version__`, kept consistent with `pyproject.toml` by
  `scripts/check_release_metadata.py`.
- Toolchain: ruff (lint + format), mypy, and pytest-cov configuration in
  `pyproject.toml`, plus a `.pre-commit-config.yaml`.

### Fixed

- `.env.example` now documents only the environment variables the repository
  actually reads (the opt-in external CLI E2E toggles).

## [0.2.0] - 2026-07-13

The 0.2.0 line is the HLP-first rewrite: the `loops` package is the Human Loop
Protocol SDK, with execution harnesses external behind adapter contracts.

### Added

- HLP 0.2.0-draft protocol core: first-class objects (Task, Checkpoint,
  Artifact, Review, Ledger, Ownership, PermissionGrant), state machine, and 23
  protocol operations including CAS writes, idempotency keys, and outbox
  records.
- `HLPHost` / `HLPClient` embedding surface with in-memory and SQLite stores,
  event bus, and hash-chained audit log.
- Adapter contracts (`AgentAdapter`, `HarnessAdapter`) with first-class CLI
  adapters (Codex, Claude Code, Kimi, Pi, Process, PromptCLI),
  shape-compatible framework shims (OpenAI, LangGraph, CrewAI), and
  `Fake*`/`InMemory*` testing adapters.
- HLP-realtime 0.3.0-draft appendix C helpers: soft `ControlSignal` merge and
  promotion with audit payloads.
- JSON schemas, schema version negotiation, and the permission scope grammar
  for the HLP-industrial reference profile.
- Executable conformance suite with three profiles (`HLP-compatible`,
  `HLP-integrated`, `HLP-industrial` reference slice) under
  `tests/conformance/`.
- Optional line-oriented TUI host (`loops-hlp-tui`) as a reference channel.
- VitePress documentation site (`docs/site`, published at
  https://ontheloops.com) with the HLP/AAP/CAP specs.

[Unreleased]: https://github.com/simplosophy/loops/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/simplosophy/loops/releases/tag/v0.2.0
