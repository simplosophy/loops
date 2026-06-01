# loops

Minimal agent runtime SDK.

loops models an agent as:

```text
AgentSpec + AgentState + AgentRuntime
```

The Rust crate is split into three layers:

- `loop0`: single Agent runtime, provider/tool loop, prompt rendering, state,
  events, and the built-in `shell` tool.
- `loop1`: user runtime/container protocol boundary for channel messages,
  sessions, routing, and user-scoped state.
- `loop2`: org/project organizer protocol boundary for projects, tasks,
  handoff, runtime inventory, and audit/project events.

## Quick Start

Run loop0 from the Rust one-shot CLI:

```bash
export LOOPS_OPENAI_API_KEY="..."
cargo run --bin loops-loop0 -- \
  --model gpt-4.1 \
  --system-file examples/prompts/loop0-system.md \
  --input "List the current directory" \
  --stream
```

The same run can be fully described by a JSON config file. See
`examples/loop0.config.json` for a complete sample.

```bash
cp .env.example .env
# Fill in LOOPS_OPENAI_API_KEY or the provider-specific key used by the config.
cargo run --bin loops-loop0 -- --config examples/loop0.config.json
```

`loops-loop0` loads `.env` automatically when present. Explicit shell
environment variables still take precedence; use `--env-file path/to/env` for a
different dotenv file.

## Architecture

See [docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md) for the
domain model, runtime lifecycle, provider/tool/I/O boundaries, logging,
tool concurrency, and extension rules.

## Verification

```bash
cargo fmt --all --check
cargo test
```
