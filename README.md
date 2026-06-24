# loops

Human Loop Protocol (HLP) Python SDK for responsible human-agent workflows.

HLP is the public surface of this project. It models the responsibility loop
around agent work: task delegation, checkpoint decisions, artifact review,
ledger writes, and audit replay. It is not a replacement agent runtime.
OpenAI Agents SDK, OpenAI Python SDK, Codex CLI, Kimi CLI, Claude Code CLI,
LangGraph, CrewAI, and similar runtimes connect through adapters.

The lower-level `loops.loop0` runtime remains available for experiments and
local agent execution, but the top-level `loops` package is HLP-first.

## What HLP Owns

- `Task`: the bounded unit of human-agent work.
- `Checkpoint`: the point where an agent needs a human decision.
- `Artifact` and `Review`: delivery and acceptance records.
- `Ledger` and `Audit`: append-only project state and replayable history.
- `AgentAdapter`: the explicit boundary from HLP into an agent runtime or CLI.

HLP does not own tool calling, agent-to-agent routing, UI delivery, or the
internal execution strategy of an agent runtime.

## Quick Start

Run the dependency-free HLP workflow demo:

```bash
uv run loops-hlp-demo
```

Run adapter compatibility checks without external services:

```bash
uv run loops-hlp-adapters-demo
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

## Optional loop0 Runtime

`loops.loop0` is an internal/minimal runtime package. Use it explicitly when you
want to experiment with a local agent loop:

```bash
export LOOPS_DEEPSEEK_API_KEY="..."
uv run loops-demo "inspect the workspace"
```

Run loop0 directly from the generic one-shot CLI:

```bash
export LOOPS_OPENAI_API_KEY="..."
uv run loops-loop0 \
  --model gpt-4.1 \
  --system-file prompts/system.md \
  --input "List the current directory" \
  --stream
```

JSON config files are supported; see `examples/loop0.config.json`.

## Documentation

- HLP spec: [docs/specs/HLP.md](docs/specs/HLP.md)
- Architecture overview: [docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md)
- loop2/HLP implementation notes: [docs/architecture/loop2.md](docs/architecture/loop2.md)
- Website source: [docs/site](docs/site)

## Verification

```bash
uv run pytest -q
uv run loops-hlp-demo
uv run loops-hlp-adapters-demo
uv run loops-hlp-local-cli-demo --adapters codex,kimi,claude
```
