# First-Class Harness Adapters for Pi / Claude Code / Kimi

Date: 2026-07-19
Status: in progress

## Goal

Bring all four CLIs to first-class, end-to-end-verified HLP adapter depth:
`HarnessAdapter` parity with the Codex reference (projection + reliable
peek/ack delivery), TUI wiring, offline contract tests with injected runners,
and a real-CLI E2E run across all four.

## Current state (verified 2026-07-19)

| CLI | Classes | Harness projection | peek/ack | prompt_mode | TUI | Real E2E |
|---|---|---|---|---|---|---|
| Codex | `CodexCLIAdapter`, `CodexHarnessAdapter` | yes | yes | harness | yes | lifecycle + soft |
| Pi | `PiHarnessAdapter(CodexHarnessAdapter)` | inherited | inherited | inherited | yes | soft only |
| Claude Code | `ClaudeCodeCLIAdapter` | no | no | no | no | lifecycle + soft(opt) |
| Kimi | `KimiCLIAdapter` (text mode!) | no | no | no | no | lifecycle + soft(opt) |

## Probed wire facts (this machine, 2026-07-19)

- `kimi -p --output-format stream-json` (0.27.0): JSONL of
  `{"role":"assistant","content":...}` and `{"role":"meta","type":...}`
  (meta carries `session_id`; `kimi -r <id>` resumes — follow-up only).
- `claude -p --output-format stream-json --verbose` (2.1.81): JSONL of
  `system` (init/hooks), `assistant` (message.content[] = thinking/text
  blocks), `result` (`subtype:"success"`, final text in `result`,
  `session_id`, usage). Flags: `--no-session-persistence`,
  `--permission-mode dontAsk`.
- `pi --mode json -p --no-session`: already the Pi adapter command.
- `codex exec --json --sandbox read-only --ephemeral`: reference.

HLP semantics for kimi/claude therefore ride inside the assistant/result
**text** (chat-mode prompt requires one final JSON object with
run_id/correlation_id/status/summary plus optional `hlp.*`/`pi.*` human-loop
event objects) — extracted with the existing `_parsing` text-JSON machinery.

## Work items

1. **Parse layer**: refactor `CodexHarnessAdapter._execute` to delegate to an
   overridable `parse_harness_stdout(stdout) -> payload` (events attached
   under the existing `_codex_events` key so projection/queueing/peek/ack are
   inherited unchanged). Add `parse_kimi_stdout` / `parse_claude_stdout` in
   `_parsing.py`.
2. **`KimiHarnessAdapter(CodexHarnessAdapter)`**: command
   `("kimi","--output-format","stream-json","-p")`; payload = last assistant
   content's extracted HLP JSON; events = embedded `hlp.*`/`pi.*` objects.
   Add `prompt_mode` to `KimiCLIAdapter` too (text mode stays its default).
3. **`ClaudeCodeHarnessAdapter(CodexHarnessAdapter)`**: command
   `("claude","-p","--output-format","stream-json","--verbose",
   "--permission-mode","dontAsk","--no-session-persistence")`; payload from
   `type="result"`; thinking/text blocks feed streaming chunks. Add
   `prompt_mode` to `ClaudeCodeCLIAdapter`.
4. **Streaming**: extend `format_harness_stream_line` for kimi
   (`role=assistant`→text, `meta`→status) and claude (`assistant`→text/
   thinking, `result`→status, `system`→ignored) shapes.
5. **Pi gap fill**: offline tests for handoff/cancel/projection edge cases;
   add `"pi"` to the full-lifecycle real E2E parametrization.
6. **TUI**: wire `claude` and `kimi` in `build_client` /
   `_SUPPORTED_ADAPTERS` / argparse choices (chat prompt_mode, streaming
   runners); update the rejection test.
7. **Offline tests**: per-CLI parse fixtures (from probed shapes), full op
   surface with injected runners, projection → checkpoint/artifact through
   `HLPClient.project_harness_events`, peek/ack cursor semantics,
   correlation-mismatch failures. Mirror the existing Codex suite layout.
8. **Real-CLI E2E**: run `HLP_RUN_EXTERNAL_CLI_E2E=1 pytest tests/external/`
   locally against all four CLIs; record results.
9. **Docs**: README Adapter Depth matrix, `docs/architecture/hlp.md`
   capability table, CHANGELOG [Unreleased], notes entry; commit per
   AGENTS.md.

## Non-goals

- Session-resume continuity (`kimi -r`, `claude -r`, `pi --resume`): the
  reference architecture stays one-shot with correlation echo; resume is a
  documented follow-up.
- No changes to `AgentAdapter`/`HarnessAdapter` contracts or HLP spec.

## Validation

- Offline: `ruff check`, `ruff format --check`, `mypy loops`, full pytest
  green including new per-CLI suites.
- Live: `HLP_RUN_EXTERNAL_CLI_E2E=1 uv run pytest tests/external/ -q` passes
  for codex, pi, claude, kimi on this machine.
