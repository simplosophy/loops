# loops

[![CI](https://github.com/simplosophy/loops/actions/workflows/ci.yml/badge.svg)](https://github.com/simplosophy/loops/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/loops-hlp.svg)](https://pypi.org/project/loops-hlp/)
[![Python](https://img.shields.io/pypi/pyversions/loops-hlp.svg)](https://pypi.org/project/loops-hlp/)
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

Run the offline **BCI (brainwave) channel** demo. HLP is compatible with
brain-computer-interface input **by design** (spec appendix C): a BCI decoder
is just a channel/sensor-plane producer of
`ControlSignal(source_kind="bci")` — HLP receives only promoted
responsibility events, never raw EEG frames. High-risk hard checkpoints
cannot be closed by BCI alone (D3, fail-closed; second-factor path shown).
No protocol changes, no EEG hardware:

```bash
uv run loops-hlp-bci-demo
```

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
| first-class | `CodexCLIAdapter`, `CodexHarnessAdapter`, `PiHarnessAdapter`, `ClaudeCodeCLIAdapter`, `ClaudeCodeHarnessAdapter`, `KimiCLIAdapter`, `KimiHarnessAdapter`, `ProcessAgentAdapter`, `PromptCLIAdapter` | Real process/CLI boundary with correlation and (where applicable) harness event projection |
| shape-compatible | `OpenAIAgentsSDKAdapter`, `OpenAIPythonSDKAdapter`, `LangGraphAdapter`, `CrewAIAdapter` | Thin Python framework entry points; useful for embedding experiments, not a claim of full harness parity |
| testing | In-memory fake adapters under `loops.hlp.adapters` | Offline unit tests and demos only |

All four first-party CLIs share the same JSONL projection pipeline, reliable
peek/ack event delivery, and chat/protocol prompt modes:

| CLI | Delegate adapter | Harness adapter (projection + peek/ack) | Wire mode | TUI |
| --- | --- | --- | --- | --- |
| Codex | `CodexCLIAdapter` | `CodexHarnessAdapter` | `codex exec --json` | yes |
| Pi | — | `PiHarnessAdapter` | `pi --mode json` | yes |
| Claude Code | `ClaudeCodeCLIAdapter` | `ClaudeCodeHarnessAdapter` | `claude -p --output-format stream-json` | yes |
| Kimi | `KimiCLIAdapter` | `KimiHarnessAdapter` | `kimi -p --output-format stream-json` | yes |

Harness adapters project explicit `hlp` / `pi` human-loop payloads into HLP
checkpoints and artifacts, validate correlation on every event line, and drop
transport-level duplicates (e.g. Claude Code's `result` envelope repeats the
final assistant text). In protocol mode, Codex and Claude Code additionally
enforce the reply envelope **natively** — `--output-schema` / `--json-schema`
against the shared `HLP_RESULT_SCHEMA` (closed object: `run_id`,
`correlation_id`, `status`, `summary`, `error`) — so the correlation echo no
longer depends on prompt discipline; Kimi and Pi have no such flag and are
covered by the robust extraction layer (markdown fences, prose, CRLF, unicode
variance all tested). End-to-end coverage: offline contract tests with
injected runners for every operation, a projection robustness suite
(`tests/test_hlp_projection_robustness.py`), plus an opt-in real-CLI
lifecycle suite (`HLP_RUN_EXTERNAL_CLI_E2E=1`, see Verification).

**Session-resume continuity** (default; `session_continuity=False` restores
one-shot behavior): delegate binds the CLI-native session id from the wire,
and follow-up ops (`block` / `resume` / `steer` / `cancel`) resume the same
native session — `codex exec resume`, `claude --resume`, `kimi --session`,
`pi --session`. Continuity means *a new turn in the same session context*,
the strongest form these CLIs offer today, not frozen-process resumption.
Persistence-disabling flags (`--ephemeral`, `--no-session`,
`--no-session-persistence`) are dropped automatically when continuity is on.
Proven live with the codeword probe (`uv run loops-hlp-continuity-e2e`):
the model recites a fact it was told before the checkpoint cycle — only
possible in a truly resumed session.

**Handoff (ownership.transfer) goes one step further**: on CLIs with native
session forking, the receiving agent inherits the full session context —
`pi --fork` and `claude --resume --fork-session` branch the source session
into a new one (verified live: the receiving run recites the pre-handoff
codeword without being told again). Codex and Kimi have no native fork yet;
handoff there stays a one-shot envelope carrying the structured context
(verified live as the documented fallback).

## Industrial Profile (Reference)

`HLP-industrial` in this repository is a **reference profile**: per-task CAS /
idempotency, adapter outbox intent, reliable harness event peek/ack, permission
scope grammar, reducer-ready audit with optional hash chain, and wire schema /
version negotiation. It proves protocol semantics offline. It is **not** a
multi-writer production backend or managed control plane.

Recovery and timeout semantics are concrete and tested:

- **Outbox recovery loop**: adapter intents are persisted before side effects
  and stay `pending` on crash. `pending_adapter_outbox()` (client and
  operations level) exposes them; retrying the original operation with the
  same `idempotency_key` reuses the persisted intent and never repeats
  committed side effects.
- **Checkpoint timeout sweep**: `expire_due_checkpoints(now)` expires every
  pending checkpoint past `expires_at` through the audited `checkpoint.expire`
  operation; the reference policy keeps the task blocked (pure suspension,
  spec §7.2).

## Transport (HTTP reference binding)

Spec §7.1 leaves transport open; this repository ships a **stdlib-only
reference binding** (zero new dependencies) so hosts and channels can talk to
a remote HLP server. The wire contract is the deliverable — production
deployments are expected to rebind with their own framework.

```bash
uv run loops-hlp-serve --adapter fake --port 8471
curl -X POST http://127.0.0.1:8471/v1/ops/task.create \
  -H 'Content-Type: application/json' -H 'X-HLP-Principal: user_alice' \
  -d '{"params":{"principal":"user_alice","goal":"ship safely"}}'
curl http://127.0.0.1:8471/v1/events   # SSE audit stream (hash-chained)
```

- `POST /v1/ops/<object.verb>` — all 23 protocol operations plus
  `human.inbox`, `pending.outbox`, `checkpoints.expire_due`; body carries
  `params`, optional `expected_task_revision` (CAS) and `idempotency_key`.
- Errors map `ProtocolError` codes to their §6.1 HTTP analogies
  (400/401/404/408/409/410/412) with the §6.2 error object.
- Mutating operations require the `X-HLP-Principal` header; real
  authentication stays deployment-side (spec §1.2 RBAC is not HLP's).
- `GET /v1/events?after=<seq>` — SSE stream of the §3.9 audit events;
  `GET /v1/version`, `GET /v1/health`.
- `HttpHLPWireClient` (`loops.hlp.transport`) is the matching wire-level
  reference client; results are wire dicts (the wire is the contract).

Non-goals for this binding: no framework dependency, no TLS, no RBAC, no
WebSocket/realtime soft-signal streaming, no remote adapter registration
(adapters stay server-local), and no typed `from_wire` reconstruction
(follow-up). The spec text is unchanged; converging §7.1 is a later proposal.

For Kimi, the smoke demo can build a temporary `kimi-cli` config from
`~/.metaworker/config.yaml` when native Kimi Code has no model configured. The
temporary file is created in the system temp directory and deleted after the
run.

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
