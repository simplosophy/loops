# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- TUI terminal UX hardening: animated braille spinner on TTY (heartbeat
  fallback otherwise), dim thinking / red error stream styling, multi-line
  input via `\` continuation, and an inline approval card — when the active
  task has a pending checkpoint the TUI shows `⚠ checkpoint pending` with
  bare `y`/`n` quick keys to approve/reject (plain prompt semantics kept
  when nothing is pending). Prompt output now renders the full progress
  panel (todo checklist + sub-agent tree) whenever the run projects one.
- `/broadcast <text>`: fans one prompt out to every CLI harness
  (claude/codex/kimi/pi) as independent HLP tasks over the shared store
  (task.assign requires `created`, so one task each — full per-harness audit
  trail), then renders a side-by-side comparison block. Per-adapter failures
  are isolated and rendered inline; the active task is not disturbed.
- Stream envelope suppression: `StreamPrinter` holds back text starting
  with `{` until it parses — HLP result envelopes (including delta-streamed
  ones, e.g. kimi) render as their `summary` only, never raw JSON.
  `run_prompt_process_streaming` / `make_streaming_prompt_runner` gained an
  `on_close` hook so streamed text is properly terminated before the result
  line prints.

## [0.4.0] - 2026-07-21

### Added

- TUI industrial hardening: readline input with persistent history and tab
  completion (`loops/tui/console.py`), role-colored output with
  `--no-color`/`NO_COLOR`/non-TTY handling, per-turn status line, and an
  actionable error UX (did-you-mean suggestions for unknown commands plus
  recovery hints per error family).
- Harness progress projection (`RunProgressSnapshot`, appendix C §C.2):
  adapters accumulate each CLI's aggregate state — codex `todo_list` items,
  claude `TodoWrite` todos and `Task` sub-agents (with parent links) — into
  an ephemeral per-run snapshot. `HLPClient.run_progress` facade and TUI
  `/progress` (checklist + agent tree) plus a compact progress line after
  each prompt. Ephemeral by design: never audited, never a responsibility
  record; pi/kimi wires carry no progress events and return None.
- Runtime adapter and model switching in the TUI: `/adapter` rebuilds the
  client over the shared store (task history survives) and hands the active
  task off to the new adapter; `/model` rebuilds with a different model.
  `build_client` accepts a shared `store`; `set_preference` supports the
  `adapter` field. Live-verified (pi → kimi switch with handoff).
- `loops-hlp-tui` is now a full standalone harness host: `/tasks` `/use`
  `/handoff` `/artifacts` `/show` commands, Ctrl+C seizing control via
  `task.interrupt` instead of dying, `--resume <session_id>` startup with
  open-inbox banner, `--model` passthrough for all four CLI adapters, and
  grouped `/help`. Handoff uses session forking on fork-capable CLIs
  (pi/claude), proven live end-to-end (codeword probe through the TUI).
- Multi-reviewer aggregation (spec §7.5 converged): optional
  `TaskSpec.review_policy` (required reviewers + `all`/`majority`/`any`
  quorum) with deterministic per-artifact-version aggregation — veto >
  quorum-approve > changes_requested > pending. `Review.artifact_version`
  pins review rounds; reviewers must be policy members (`UNAUTHORIZED`
  otherwise). Fully backward-compatible (no policy = single-reviewer
  semantics unchanged); wire/transport support included
  (`tests/test_hlp_multi_reviewer.py`).

## [0.3.0] - 2026-07-20

### Added

- Typed `from_wire(name, value)` reconstruction (counterpart of `to_wire`):
  29 registered wire objects (all first-class objects and value objects)
  round-trip through wire dicts with alias inversion (`from`/`as`), nested
  dataclasses, and ISO datetimes. `HttpHLPWireClient.call(..., as_="Task")`
  returns typed results. Suite: `tests/test_hlp_from_wire.py`.
- HTTP reference transport binding (`loops.hlp.transport`, spec §7.1):
  stdlib-only `HLPHttpServer` serving all 23 operations via
  `POST /v1/ops/<object.verb>` (CAS + idempotency pass-through), audit-event
  SSE stream (`GET /v1/events`), version and health endpoints, §6.1 error
  status mapping, and `X-HLP-Principal` binding for mutating ops.
  `HttpHLPWireClient` reference client and `loops-hlp-serve` console entry.
  Zero new dependencies; real-socket test suite
  (`tests/test_hlp_transport.py`).
- Session forking for handoff: on CLIs with native fork support the
  receiving agent inherits the full session context — `pi --fork` and
  `claude --resume --fork-session` (new session id bound from the wire).
  Codex/Kimi have no native fork; handoff there stays a one-shot envelope
  with the structured context (documented fallback, live-verified both ways).
- Session-resume continuity for all four CLI harness adapters: delegate binds
  the CLI-native session id from the wire (`thread.started`, `session_id`,
  meta line, `type=session` event) and follow-up ops (`block` / `resume` /
  `steer` / `cancel`) resume the same native session via
  `codex exec resume`, `claude --resume`, `kimi --session`, `pi --session`.
  `session_continuity=False` restores one-shot behavior; persistence-disabling
  flags are dropped automatically. `session_of_run()` exposes the binding.
  Proven live by the codeword probe (`loops-hlp-continuity-e2e`,
  `tests/external/test_hlp_session_continuity_real_cli.py`) and offline
  contract tests (`tests/test_hlp_session_continuity.py`).
- Native structured output for the CLI projection contract: protocol-mode
  Codex (`--output-schema`) and Claude Code (`--json-schema`) adapters now
  enforce the shared `HLP_RESULT_SCHEMA` envelope (`run_id`,
  `correlation_id`, `status`, `summary`, `error`; closed object per Codex
  strict mode), so the correlation echo no longer depends on prompt
  discipline. Chat mode stays free-form; Kimi/Pi keep the prompt contract.
- `pending_adapter_outbox()` recovery surface (operations + `HLPClient`):
  crash-pending adapter intents are discoverable; retrying the original
  idempotency-keyed operation completes them without duplicate side effects
  (conformance-covered).
- `expire_due_checkpoints(now)` checkpoint timeout sweep (spec §7.2
  reference policy: pure suspension, audited, idempotent).
- `tests/test_hlp_projection_robustness.py`: wire-variance fixtures for all
  four CLIs (markdown fences, prose, CRLF, unicode, duplicate events,
  missing correlation, malformed lines) plus structured-output wiring tests.
- Reference BCI (brainwave) channel slice: `examples/hlp_bci_channel_demo.py`
  (`loops-hlp-bci-demo`) demonstrating appendix-C compatibility of
  brain-computer-interface input with zero protocol changes — soft BCI stream
  merge-promotion (D1/D2), low-risk hard resolve, and D3 fail-closed denial
  of BCI-alone high-risk resolves with a second-factor path; offline tests in
  `tests/test_hlp_realtime.py`.
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
- Full HLP spec review (`docs/reviews/2026-07-19-hlp-spec-review.md`): the
  spec's audit-mapping, state-definition, and adapter-mapping tables were
  completed (`review.commented`, `artifact.referenced`, `task.completed`
  side-effect row; `rejected` state; `ownership.transfer → handoff` and
  `task.cancel → cancel` adapter rows). No semantic changes.
- Docs site: four-CLI harness adapter matrix, BCI compatibility note,
  adapter-level conformance evidence, and a reference demo index.

### Changed

- `loops/tui/controller.py` (833 lines) split into a 23-line composition
  over `_base.py` plus four domain mixins (`_session_cmds`, `_work_cmds`,
  `_hlp_cmds`, `_control_cmds`), mirroring the operations package structure.
- Adapter testing tier demoted: the run-registry machinery moved from
  `FakeAgentAdapter` into a production base `RunRegistryAdapter`
  (`loops/hlp/adapters/_registry.py`), which `ProcessAgentAdapter` now
  extends — production adapters no longer inherit from a class named Fake.
  `Fake*`/`InMemory*` stay importable from `loops.hlp` and
  `loops.hlp.adapters.fake` but are no longer re-exported from the top-level
  `loops` package. `HLPClient`'s default adapter and TUI `--adapter fake`
  offline mode are unchanged.
- Adapters package restructured: the shared CLI harness machinery moved from
  `codex.py` into `HarnessAdapterBase` (`loops/hlp/adapters/_harness.py`,
  now public), and each CLI got a dedicated module — `pi.py`, `claude.py`,
  `kimi.py`, `hermes.py` (replacing `cli.py`). Codex's file is now codex-only
  (553 → 114 lines). Pure code motion; the public API is unchanged.
- `loops/hlp/operations.py` (1.6k-line god class) split into the
  `loops/hlp/operations/` package: per-domain mixins (task / checkpoint /
  ownership / review / artifact / ledger / audit) composed in
  `HumanLoopOperations`. Pure code motion; the public import path and
  behavior are unchanged.

### Removed

- `docs/intro.html`, an orphaned pre-HLP marketing page with no references.

### Fixed

- Adapters now fill an absent `correlation_id` echo from the request (local
  binding) for schema-less CLIs (Pi/Kimi prompt-contract variance);
  present-but-mismatched echoes are still rejected.
- Payload extraction now also digs `structured_output` — the field Claude
  Code fills when `--json-schema` validates the reply envelope.
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

[Unreleased]: https://github.com/simplosophy/loops/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/simplosophy/loops/releases/tag/v0.4.0
[0.3.0]: https://github.com/simplosophy/loops/releases/tag/v0.3.0
[0.2.0]: https://github.com/simplosophy/loops/releases/tag/v0.2.0
