# HLP Local CLI Adapter E2E Plan

## Goal

Finish the HLP Python SDK adapter path for local coding-agent CLIs and verify it
against the user's installed Codex, Kimi, and Claude Code environments.

## Current Gap

The HLP SDK already has a stable public surface, a fake adapter, framework-shaped
adapters, and a generic JSON-over-stdin/stdout process adapter. That proves the
adapter contract but not the concrete local CLI path. Codex, Kimi, and Claude
Code expose one-shot prompt modes rather than the exact HLP JSON process
contract, so HLP needs a small prompt-oriented adapter runner that keeps the
core protocol transport-agnostic.

## Scope

- Preserve `loops.hlp` as the public SDK surface.
- Keep `loop2` as HLP's control plane; do not import `loop0` or `loop1`.
- Add a Kimi CLI adapter next to Codex and Claude Code.
- Add a one-shot CLI adapter base that turns HLP operation requests into a
  prompt and parses structured JSON from CLI output.
- Add a local smoke demo that can run Codex, Kimi, and Claude Code with the
  user's installed binaries.
- Keep normal tests dependency-free by using injected process runners.

## Non-Goals

- No persistent daemon integration.
- No ACP/MCP server implementation.
- No mandatory dependency on vendor SDKs.
- No automatic mutation of CLI auth or user config files.

## Implementation Steps

1. Add failing tests for a prompt-mode CLI adapter that appends an HLP prompt to
   a command and extracts the returned JSON object.
2. Add failing tests for `KimiCLIAdapter` export and default command metadata.
3. Implement the prompt-mode CLI adapter base and specialized Codex, Kimi, and
   Claude Code adapters.
4. Add a dependency-free local CLI smoke script with injectable runners for unit
   tests and real binary execution for manual E2E.
5. Update README, architecture notes, and the 2026-06-23 change note.
6. Run focused tests, the full test suite, and real local CLI E2E for Codex,
   Kimi, and Claude Code.

## Acceptance Criteria

- `from loops.hlp import KimiCLIAdapter` works.
- Codex, Kimi, and Claude Code adapters can execute HLP `delegate` through
  injected runners in tests.
- CLI output parsing accepts direct JSON, JSONL, and text containing a JSON
  object.
- The real local smoke command produces an `ok` result for Codex, Kimi, and
  Claude Code or reports a structured adapter error without corrupting HLP
  state.
- `uv run pytest -q` passes.
