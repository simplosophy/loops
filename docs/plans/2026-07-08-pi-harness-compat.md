# Pi Harness Compatibility Plan

| | |
|---|---|
| **日期** | 2026-07-08 |
| **状态** | 已实现 |
| **关联** | HLP AgentAdapter/HarnessAdapter, TUI adapter selection |

## Goal

Add first-party Pi harness compatibility as a full HLP harness adapter: HLP can delegate to Pi, block/resume runs, and project Pi human-facing events into HLP checkpoints, artifacts, inbox items, review, and audit.

## Contract

Pi integration uses the same adapter boundary as Codex harness support. The adapter runs a prompt-mode command and reads JSON/JSONL stdout. It accepts:

- lifecycle payloads containing `run_id`, `correlation_id`, `status`, and optional `summary`
- HLP-compatible events under `hlp`, `human_loop`, or `pi`
- `type="pi.event"` lines where `pi.kind` is one of `needs_approval`, `needs_choice`, `needs_input`, or `artifact`

The adapter must reject mismatched `correlation_id` before mutating HLP state.

## Implementation Tasks

1. Add failing SDK tests for `PiHarnessAdapter`:
   - public export and healthcheck
   - JSONL event projection from `pi.event`
   - mismatch rejection
2. Implement `PiHarnessAdapter` in `loops/hlp/adapters.py` with default command `("pi", "run", "--json")`, adapter name `pi-harness`, and conformance `checkpoint-capable`, `artifact-aware`, `event-streaming`.
3. Export it from `loops.hlp` and top-level `loops`.
4. Add Pi to offline adapter compatibility demo and tests.
5. Add Pi to `loops-hlp-tui --adapter pi`, with tests proving adapter selection and line-oriented execution work through an injected Pi client.
6. Document Pi in README and relevant architecture/TUI plan text.

## Verification

- `uv run pytest tests/test_hlp_sdk.py -q`
- `uv run pytest tests/test_hlp_tui.py -q`
- `uv run pytest tests/test_hlp_protocol.py -q`
- `uv run python -m compileall loops tests examples`
- `uv run python scripts/check_release_metadata.py`
- `git diff --check`
