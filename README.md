# loops

Human Loop Protocol (HLP) Python SDK for responsible human-agent workflows.

HLP is the human-interaction control plane for existing agent harnesses. It
models the responsibility loop around agent work: task delegation, checkpoint
decisions, artifact review, ledger writes, and audit replay. It does not unify
or replace harness execution mechanisms. OpenAI Agents SDK, OpenAI Python SDK,
Codex CLI, Kimi CLI, Claude Code CLI, LangGraph, CrewAI, and similar runtimes
keep their own execution model and connect through adapters.

This project does not ship its own agent harness. The top-level `loops` package
is the HLP SDK: protocol objects, client, host, stores, event bus, and adapters
for wrapping external harnesses.

## What HLP Owns

- `Task`: the bounded unit of human-agent work.
- `Checkpoint`: the point where an agent needs a human decision.
- `Artifact` and `Review`: delivery and acceptance records.
- `Ledger` and `Audit`: append-only project state and replayable history.
- `AgentAdapter`: the explicit boundary from HLP into an agent harness or CLI.
- `HarnessAdapter`: the projection boundary from harness events into HLP's
  human-facing semantics.

HLP does not own tool calling, agent-to-agent routing, UI delivery, or the
internal execution strategy of an agent harness.

## Quick Start

Run the dependency-free HLP workflow demo:

```bash
uv run loops-hlp-demo
```

Run adapter compatibility checks without external services:

```bash
uv run loops-hlp-adapters-demo
```

Run a dependency-free harness wrapping demo:

```bash
uv run loops-hlp-harness-demo
```

Run the local CLI smoke test against installed Codex, Kimi, and Claude Code:

```bash
uv run loops-hlp-local-cli-demo --adapters codex,kimi,claude
```

For Kimi, the smoke demo can build a temporary `kimi-cli` config from
`~/.metaworker/config.yaml` when native Kimi Code has no model configured. The
temporary file is created under `/private/tmp` and deleted after the run.

## Python SDK

Use `HLPHost` when embedding HLP in an application:

```python
from loops import ArtifactPayload, FakeAgentAdapter, HLPHost

host = HLPHost.in_memory(adapter=FakeAgentAdapter())
client = host.client

task = await client.create_task(
    principal="user_alice",
    goal="Review PR #1234 for security issues",
    type="code-review",
)
run = await client.delegate(
    task.id,
    agent_id="agent_reviewer",
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
from loops import ClaudeCodeCLIAdapter, CodexCLIAdapter, KimiCLIAdapter

codex = CodexCLIAdapter()
kimi = KimiCLIAdapter()
claude = ClaudeCodeCLIAdapter()
```

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
from loops import FakeHarnessAdapter, HarnessEvent, HLPClient

adapter = FakeHarnessAdapter()
client = HLPClient(adapter=adapter)

task = await client.create_task(
    principal="user_alice",
    goal="Review a generated patch",
)
run = await client.delegate(task.id, "agent_reviewer", capability="code-review")
await client.start(task.id)

# A real harness would emit this from its own run loop.
adapter.queue_event(run.run_id, HarnessEvent(
    kind="needs_approval",
    task_id=task.id,
    run_id=run.run_id,
    agent_id=run.agent_id,
    prompt="Apply the generated patch?",
))

await client.project_harness_events(run.run_id)
inbox = await client.human_inbox("user_alice")
```

## Documentation

- HLP spec: [docs/specs/HLP.md](docs/specs/HLP.md)
- Architecture overview: [docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md)
- HLP implementation notes: [docs/architecture/loop2.md](docs/architecture/loop2.md)
- Website source: [docs/site](docs/site)

## Verification

```bash
uv run pytest -q
uv run loops-hlp-demo
uv run loops-hlp-adapters-demo
uv run loops-hlp-harness-demo
uv run loops-hlp-local-cli-demo --adapters codex,kimi,claude
```
