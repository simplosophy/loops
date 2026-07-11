# loops

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
```

Run the **PR Review Desk** host application (real embedding case, offline by
default):

```bash
uv run loops-hlp-pr-desk
```

This is not another adapter smoke test. `PRReviewDesk` is a host that owns PR
domain language and inbox cards; it embeds `HLPHost` as the human-control plane
and projects a code-review harness through `CodexHarnessAdapter`. The offline
runner is deterministic; pass `--live` only when a local Codex CLI is available.

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
# Or: adapter = PiHarnessAdapter(command=("pi", "run", "--json"))
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

- HLP spec: [docs/specs/HLP.md](docs/specs/HLP.md)
- Architecture overview: [docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md)
- HLP implementation notes: [docs/architecture/hlp.md](docs/architecture/hlp.md)
- Website source: [docs/site](docs/site)

## Verification

Default offline release verification:

```bash
uv run pytest -q
uv run pytest tests/conformance -q
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
