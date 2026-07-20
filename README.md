# loops

[![CI](https://github.com/simplosophy/loops/actions/workflows/ci.yml/badge.svg)](https://github.com/simplosophy/loops/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/loops.svg)](https://pypi.org/project/loops/)
[![Python](https://img.shields.io/pypi/pyversions/loops.svg)](https://pypi.org/project/loops/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/simplosophy/loops/blob/main/LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)

Human Loop Protocol (HLP) Python SDK for responsible human-agent workflows.

HLP is the human-interaction control plane for existing agent harnesses. It
models the responsibility loop around agent work: task delegation, checkpoint
decisions, artifact review, ledger writes, and audit replay. It does not unify
or replace harness execution mechanisms. Codex CLI, Claude Code CLI, Kimi CLI,
Pi, and similar runtimes keep their own execution model and connect through
adapters. OpenAI Agents SDK, OpenAI Python SDK, LangGraph, and CrewAI are
**shape-compatible** entry points (thin call shims), not deep first-class
integrations.

This project does not ship its own agent harness. The top-level `loops` package
is the HLP SDK: protocol objects, client, host, stores, event bus, and adapters
for wrapping external harnesses. The line-oriented TUI (`loops-hlp-tui`) is an
optional host/channel demo, not part of the protocol core.

## What HLP Owns

- `Task`: the bounded unit of human-agent work.
- `Checkpoint`: the point where an agent needs a human decision.
- `Artifact` and `Review`: delivery and acceptance records.
- `Ledger` and `Audit`: append-only project state and replayable history.
- Continuous control values: `task.amend`, `task.interrupt`,
  `steering_log`, `PermissionGrant`, and checkpoint `proposed_actions`.
- `AgentAdapter`: the explicit boundary from HLP into an agent harness or CLI.
- `HarnessAdapter`: the projection boundary from harness events into HLP's
  human-facing semantics.

HLP does not own tool calling, agent-to-agent routing, UI delivery, or the
internal execution strategy of an agent harness.

## Quick Start

Run the HLP workflow demo through the default Codex CLI adapter:

```bash
uv run loops-hlp-demo
```

Run adapter compatibility checks without external services:

```bash
uv run loops-hlp-adapters-demo
```

Run an offline Codex harness wrapping demo with an injected runner:

```bash
uv run loops-hlp-harness-demo
```

Run the dependency-free Codex harness adapter demo:

```bash
uv run loops-hlp-codex-harness-demo
```

Run the full local CLI lifecycle test against installed Codex, Kimi, and Claude Code:

```bash
uv run loops-hlp-local-cli-demo --adapters codex,kimi,claude
```

Run the line-oriented HLP TUI channel:

```bash
uv run loops-hlp-tui --adapter codex
uv run loops-hlp-tui --adapter pi
uv run loops-hlp-tui --adapter fake   # offline, no external CLI
```

Live adapters (`codex` / `pi`) use **harness-capable** adapters
(`CodexHarnessAdapter` / `PiHarnessAdapter`) in **chat prompt mode**: free-text
prompts put the user message first (not the full “HLP adapter operation” JSON
dump). Lifecycle ops (block/resume/cancel) stay protocol-shaped. While the CLI
runs, the TUI **streams** compact harness events (`⋯ agent start`, live
`⋯ agent: …` text deltas, tool/status milestones) instead of only a wait timer.
After each prompt and checkpoint resolution, it projects human-facing events
into HLP and surfaces the final agent `summary` plus pending work (`/inbox`,
`/approve`, `/reject`, `/review`).

Live adapters block on the external process for each prompt. The TUI prints a
heartbeat while waiting and fails after `--timeout` seconds (default 60). If Pi
appears stuck, try:

```bash
uv run loops-hlp-tui --adapter pi --timeout 30
# or offline protocol UX without a model:
uv run loops-hlp-tui --adapter fake
```

Run the offline **HLP-realtime promotion** demo (soft merge → amend provenance,
BCI-alone high-risk deny; no voice/BCI hardware):

```bash
uv run loops-hlp-realtime-demo
```

Soft-control harness E2E (multi soft → merge → amend/steer; default offline):

```bash
uv run loops-hlp-soft-e2e --adapters codex,pi --strict
uv run loops-hlp-soft-e2e --inventory
# real installed CLIs (opt-in):
uv run loops-hlp-soft-e2e --live --adapters pi --timeout 120
HLP_RUN_EXTERNAL_CLI_E2E=1 uv run pytest tests/external/test_hlp_soft_real_cli_e2e.py -q
```

In the TUI, buffer multiple soft controls then merge-promote (HLP-realtime D2):

```bash
uv run loops-hlp-tui --adapter fake
> do the work
> /soft 先别动 production 配置
> /soft --intent clarify 重点看 token 过期路径
> /softs
> /promote
# or one-shot: /promote focus on auth boundaries
# /soft list | pop | clear
```

Optional profile constants: `HLP_REALTIME_PROFILE` / `HLP_REALTIME_SPEC_VERSION`
(`0.3.0-draft`). Package version remains `0.2.0`.

Run the **PR Review Desk** host application (real embedding case, offline by
default):

```bash
uv run loops-hlp-pr-desk
```

This is not another adapter smoke test. `PRReviewDesk` is a host that owns PR
domain language and inbox cards; it embeds `HLPHost` as the human-control plane
and projects a code-review harness through `CodexHarnessAdapter`. The offline
runner is deterministic and is the default CI path.

`--live` uses your installed Codex CLI. It can fail for environment reasons
outside HLP (unsupported default model, auth/provider mismatch, usage limits).
When that happens the desk prints a structured JSON error with `codex_message`
and hints instead of a traceback. Useful recovery options:

```bash
# deterministic host demo (recommended)
uv run loops-hlp-pr-desk

# live with an explicit model your Codex account supports
uv run loops-hlp-pr-desk --live --model "gpt-5.4"
```

```text
Reviewer
  -> PRReviewDesk (host)
  -> HLPHost / HLPClient (Task / Checkpoint / Artifact / Review / Ledger / Audit)
  -> CodexHarnessAdapter
  -> code-review harness
```

The TUI is an optional host/channel over HLP. It renders prompt input, slash
commands, human inbox approvals, artifact review, audit replay, and session
transcript state while keeping model calls, tool execution, sandboxing, and the
agent loop inside the selected harness adapter.

## Adapter Depth

| Level | Adapters | Meaning |
| --- | --- | --- |
| first-class | `CodexCLIAdapter`, `CodexHarnessAdapter`, `ClaudeCodeCLIAdapter`, `KimiCLIAdapter`, `PiHarnessAdapter`, `ProcessAgentAdapter`, `PromptCLIAdapter` | Real process/CLI boundary with correlation and (where applicable) harness event projection |
| shape-compatible | `OpenAIAgentsSDKAdapter`, `OpenAIPythonSDKAdapter`, `LangGraphAdapter`, `CrewAIAdapter` | Thin Python framework entry points; useful for embedding experiments, not a claim of full harness parity |
| testing | In-memory fake adapters under `loops.hlp.adapters` | Offline unit tests and demos only |

## Industrial Profile (Reference)

`HLP-industrial` in this repository is a **reference profile**: per-task CAS /
idempotency, adapter outbox intent, reliable harness event peek/ack, permission
scope grammar, reducer-ready audit with optional hash chain, and wire schema /
version negotiation. It proves protocol semantics offline. It is **not** a
multi-writer production backend or managed control plane.

For Kimi, the smoke demo can build a temporary `kimi-cli` config from
`~/.metaworker/config.yaml` when native Kimi Code has no model configured. The
temporary file is created under `/private/tmp` and deleted after the run.

## Python SDK

Use `HLPHost` when embedding HLP in an application:

```python
from loops import ArtifactPayload, CodexCLIAdapter, HLPHost

host = HLPHost.in_memory(adapter=CodexCLIAdapter())
client = host.client

task = await client.create_task(
    principal="user_alice",
    goal="Review PR #1234 for security issues",
    type="code-review",
)
run = await client.delegate(
    task.id,
    agent_id="agent_codex",
    capability="code-review",
    input={"goal": task.spec.goal, "repository": "web"},
)
await client.start(task.id)

artifact = await client.commit_artifact(
    task_id=task.id,
    type="report",
    payload=ArtifactPayload(
        kind="inline",
        uri="mem://report-v1",
        checksum="sha256:report-v1",
    ),
    produced_by=run.agent_id,
)

await client.amend(
    task.id,
    by="user_alice",
    text="Focus on authentication and permission boundaries.",
    intent="constrain",
)
```

Use `HLPClient` directly when you already own the store, event bus, or adapter:

```python
from loops import HLPClient, SQLiteHumanLoopStore

client = HLPClient(store=SQLiteHumanLoopStore("hlp.db"))
```

## Adapters

HLP separates two adapter directions:

- `AgentAdapter`: HLP commands a harness or runtime to delegate, block, resume,
  handoff, or cancel work.
- `HarnessAdapter`: a harness projects human-facing events back into HLP as
  checkpoints, artifacts, reviews, ledger entries, and audit.

Named local coding-agent adapters use one-shot prompt mode so they match the
real CLIs installed on a developer machine:

```python
from loops import ClaudeCodeCLIAdapter, CodexCLIAdapter, CodexHarnessAdapter, KimiCLIAdapter, PiHarnessAdapter

codex = CodexCLIAdapter()
codex_harness = CodexHarnessAdapter()
pi_harness = PiHarnessAdapter()
kimi = KimiCLIAdapter()
claude = ClaudeCodeCLIAdapter()
```

Use `CodexCLIAdapter` when HLP only needs to delegate a one-shot Codex task.
Use `CodexHarnessAdapter` when Codex JSONL output should also project
human-facing events back into HLP checkpoints and artifacts.
Use `PiHarnessAdapter` when Pi JSON/JSONL output should project `pi` or `hlp`
human-facing events into the same HLP checkpoint and artifact flow.

`ProcessAgentAdapter` is still available for custom JSON-over-stdin/stdout
processes:

```python
from loops import ProcessAgentAdapter

adapter = ProcessAgentAdapter(command=("my-agent", "run", "--json"))
```

Framework adapters accept native framework objects without adding those packages
to `loops` core dependencies:

```python
from loops import CrewAIAdapter, LangGraphAdapter, OpenAIAgentsSDKAdapter

openai_agents = OpenAIAgentsSDKAdapter(agent=agent, runner=Runner)
langgraph = LangGraphAdapter(
    graph=compiled_graph,
    config={"configurable": {"thread_id": "t1"}},
)
crew = CrewAIAdapter(crew=my_crew)
```

The framework adapters above are delegate adapters by default. Unless the
underlying framework object exposes a real pause/resume primitive, HLP
`block`, `resume`, `steer`, `handoff`, and `cancel` are local contract records,
not a guarantee that the framework runtime has been physically paused.

OpenAI's Python SDK can be injected without making it a hard dependency:

```python
from openai import AsyncOpenAI
from loops import OpenAIPythonSDKAdapter

adapter = OpenAIPythonSDKAdapter(
    client=AsyncOpenAI(),
    model="gpt-4.1",
)
```

Use `HarnessAdapter` semantics when an existing harness already has its own
execution loop and only needs a common human interaction surface:

```python
from loops import CodexHarnessAdapter, HLPClient, PiHarnessAdapter

adapter = CodexHarnessAdapter(command=("codex", "exec", "--json"))
# Or: adapter = PiHarnessAdapter()  # pi --mode json -p --no-session
client = HLPClient(adapter=adapter)

task = await client.create_task(
    principal="user_alice",
    goal="Review a generated patch",
)
run = await client.delegate(task.id, "agent_reviewer", capability="code-review")
await client.start(task.id)

await client.project_harness_events(run.run_id)
inbox = await client.human_inbox("user_alice")
```

`CodexHarnessAdapter` applies the same `HarnessAdapter` semantics to
`codex exec --json` output. It preserves HLP `task_id` as the run correlation
id and maps explicit Codex HLP events such as `needs_approval`, `needs_input`,
`needs_choice`, and `artifact` into the common HLP objects.
`PiHarnessAdapter` applies the same projection contract to Pi JSON/JSONL output
using `pi.event` lines or nested `pi` / `hlp` payloads.

## Documentation

- Published site: [ontheloops.com](https://ontheloops.com)
- HLP spec: [docs/specs/HLP.md](docs/specs/HLP.md)
- Architecture overview: [docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md)
- HLP implementation notes: [docs/architecture/hlp.md](docs/architecture/hlp.md)
- Website source: [docs/site](docs/site)

## Verification

Default offline release verification:

```bash
uv run pytest -q
uv run pytest tests/conformance -q
uv run ruff check .
uv run ruff format --check .
uv run mypy loops
uv run python scripts/check_release_metadata.py
uv run python scripts/check_spec_site_sync.py
npm run build
npm run verify:site
```

Opt-in CLI lifecycle tests require installed local agent CLIs:

```bash
uv run loops-hlp-local-cli-demo --adapters codex,kimi,claude --strict
HLP_RUN_EXTERNAL_CLI_E2E=1 uv run pytest tests/external/test_hlp_real_cli_e2e.py -q
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). By contributing, you agree that your
contributions are licensed under the Apache License 2.0.

## License

[Apache License 2.0](LICENSE)
