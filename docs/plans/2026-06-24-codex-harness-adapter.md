# Codex Harness Adapter Implementation Plan

## Goal

Implement an end-to-end Codex harness adapter for HLP so Codex CLI JSON event
streams can be delegated through HLP and projected back into HLP checkpoints,
artifacts, reviews, and human inbox items.

## Architecture

HLP remains SDK-only and does not own Codex execution internals. The adapter
lives at the existing `AgentAdapter` / `HarnessAdapter` boundary:

- HLP -> Codex uses the existing prompt-mode process execution shape.
- Codex -> HLP uses a narrow JSONL event projection layer.
- `task_id` remains the run `correlation_id`.
- Adapter failures continue to fail-before-commit through `AgentAdapterError`.

## Tasks

1. Add failing tests for `CodexHarnessAdapter`.
   - Verify it is exported from `loops` and `loops.hlp`.
   - Verify `delegate` consumes injected Codex JSONL output and preserves
     `task_id` correlation.
   - Verify `observe` maps Codex human-loop events to `HarnessEvent`.
   - Verify `HLPClient.project_harness_events` turns those events into a
     pending checkpoint and reviewable artifact.

2. Implement `CodexHarnessAdapter`.
   - Extend Codex CLI process behavior without adding a Codex dependency.
   - Default command should run `codex exec --json` in read-only ephemeral mode.
   - Parse JSONL events into a per-run event queue.
   - Recognize explicit HLP event payloads first, then conservative generic
     artifact fields.
   - Reject mismatched `correlation_id` when Codex events include one.

3. Add a dependency-free demo.
   - Create `examples/hlp_codex_harness_demo.py`.
   - Use an injected runner that emits Codex-style JSONL events.
   - Demonstrate delegate -> start -> project checkpoint -> resolve ->
     project artifact -> review.
   - Add a console script.

4. Update docs and exports.
   - Export `CodexHarnessAdapter`.
   - Add README adapter example and verification command.
   - Update `docs/architecture/hlp.md`.
   - Add notes to `docs/notes/2026-06-24.md`.

5. Verify.
   - Run targeted tests while red/green cycling.
   - Run full `uv run pytest -q`.
   - Run dependency-free demos, including the new Codex harness demo.

## Acceptance Criteria

- `from loops import CodexHarnessAdapter` works.
- `CodexHarnessAdapter` implements both HLP command and harness projection
  directions.
- Injected Codex JSONL event streams can produce HLP checkpoints and artifacts.
- Mismatched Codex/HLP correlation fails with `AgentAdapterError`.
- The end-to-end Codex harness demo runs without external services.
- Existing protocol, SDK, adapter, and demo tests still pass.
