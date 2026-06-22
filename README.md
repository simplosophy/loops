# loops

Minimal agent runtime SDK with a Human Loop Protocol (HLP) control plane.

loops models an agent as:

```text
AgentSpec + AgentState + AgentRuntime
```

The core runtime includes one built-in tool, `shell`. Other capabilities such
as skills, MCP, memory backends, app-specific I/O, and knowledge systems
are intended to be added as components or integrations.

HLP is the public SDK surface for human responsibility loops: task delegation,
checkpoint decisions, artifact review, ledger writes, and audit replay. It is
not a new agent framework. OpenAI Agents SDK, OpenAI Python SDK, Codex CLI,
Claude Code CLI, LangGraph, CrewAI, and similar runtimes connect through
adapters.

## Quick Start

Run the dependency-free HLP end-to-end demo:

```bash
uv run loops-hlp-demo
```

Run the dependency-free adapter compatibility demo:

```bash
uv run loops-hlp-adapters-demo
```

Use the HLP SDK directly:

```python
from loops.hlp import ArtifactPayload, FakeAgentAdapter, HLPClient

client = HLPClient(adapter=FakeAgentAdapter())

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

Adapter entry points are optional-dependency friendly:

```python
from loops.hlp import (
    ClaudeCodeCLIAdapter,
    CodexCLIAdapter,
    CrewAIAdapter,
    LangGraphAdapter,
    OpenAIAgentsSDKAdapter,
    OpenAIPythonSDKAdapter,
)
```

CLI adapters use a JSON-over-stdin/stdout contract and can be tested with an
injected runner before wiring a real binary:

```python
from loops.hlp import CodexCLIAdapter

codex = CodexCLIAdapter(command=("codex", "exec", "--json"))
```

OpenAI's Python SDK can be injected without adding a hard dependency to the HLP
core package:

```python
from openai import AsyncOpenAI
from loops.hlp import OpenAIPythonSDKAdapter

adapter = OpenAIPythonSDKAdapter(
    client=AsyncOpenAI(),
    model="gpt-4.1",
)
```

Framework adapters accept native framework objects without adding those packages
to `loops` core dependencies:

```python
from loops.hlp import CrewAIAdapter, LangGraphAdapter, OpenAIAgentsSDKAdapter

openai_agents = OpenAIAgentsSDKAdapter(agent=agent, runner=Runner)
langgraph = LangGraphAdapter(graph=compiled_graph, config={"thread_id": "t1"})
crew = CrewAIAdapter(crew=my_crew)
```

Run the sample agent with DeepSeek's OpenAI-compatible API:

```bash
export LOOPS_DEEPSEEK_API_KEY="..."
uv run loops-demo
```

The sample defaults to `base_url=https://api.deepseek.com`,
`model=deepseek-v4-pro`, `disable_verify_ssl=false`, the default `shell` tool,
and a small console loop implemented outside loop0. With no positional message
it starts an interactive loop and reuses the same thread id; pass a message to
run one turn:

```bash
uv run loops-demo "inspect the workspace"
```

Enable runtime logs for provider/tool/run events:

```bash
uv run loops-demo --log-level INFO
```

It is implemented in `examples/start_agent.py`.

Run loop0 directly from the generic one-shot CLI:

```bash
export LOOPS_OPENAI_API_KEY="..."
uv run loops-loop0 \
  --model gpt-4.1 \
  --system-file prompts/system.md \
  --input "List the current directory" \
  --stream
```

The same run can be fully described by a JSON config file. See
`examples/loop0.config.json` for a complete sample.

```bash
cp .env.example .env
# Fill in LOOPS_OPENAI_API_KEY or the provider-specific key used by the config.
uv run loops-loop0 --config examples/loop0.config.json
```

`loops-loop0` loads `.env` automatically when present. Explicit shell
environment variables still take precedence; use `--env-file path/to/env` for a
different dotenv file.

Use the SDK directly:

```python
from loops import AgentPolicy, PromptTemplate, agent, get_logger
from loops.loop0.providers import OpenAICompatibleProvider

provider = OpenAICompatibleProvider(
    model="...",
    api_key="...",
    base_url="https://api.openai.com/v1",
)
logger = get_logger("my.loops.agent", level="INFO")

agent0 = agent(
    PromptTemplate(
        system="""
        You are {{ agent.name }}.
        Interaction: {{ interaction.source }}

        {% for tool in tools %}
        - {{ tool.name }}: {{ tool.description }}
        {% endfor %}
        """,
    ),
    provider=provider,
    policy=AgentPolicy(parallel_tool_calls=True, max_parallel_tool_calls=4),
    logger=logger,
    metadata={"name": "agent0"},
)

result = await agent0.run("List the current directory", stream=True)
print(result.output)
```

## Architecture

See [docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md) for the
domain model, runtime lifecycle, provider/tool/I/O boundaries, logging,
tool concurrency, and extension rules.

## Verification

```bash
uv run pytest -q
```
