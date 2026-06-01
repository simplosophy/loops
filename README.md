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

The same run can be fully described by a JSON or TOML config file:

```toml
# loop0.toml
tools = ["shell"]

[prompt]
system_file = "prompts/system.md"
user = "{{ input.text }}"

[provider]
type = "openai-compatible"
name = "openai"
model = "gpt-4.1"
api_key_env = "LOOPS_OPENAI_API_KEY"
base_url = "https://api.openai.com/v1"

[agent]
name = "agent0"
workspace = ".loops-workspace"

[run]
input = "List the current directory"
thread_id = "default"
stream = true

[interaction]
source = "cli"

[output]
format = "text"
events_file = "events.jsonl"
```

```bash
uv run loops-loop0 --config loop0.toml
```

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
