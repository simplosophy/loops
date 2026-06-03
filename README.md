# loops

Minimal agent runtime SDK.

loops models an agent as:

```text
AgentSpec + AgentState + AgentRuntime
```

The core runtime includes one built-in tool, `shell`. Other capabilities such
as skills, MCP, memory backends, app-specific I/O, and knowledge systems
are intended to be added as components or integrations.

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
