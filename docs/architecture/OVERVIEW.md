# loops Architecture Overview

loops 的目标架构分为 `loop0`、`loop1`、`loop2` 三层。三层整体边界、状态和扩展点见 [LOOPS_STACK.md](LOOPS_STACK.md)。

本文主要描述当前单 Agent runtime 内核，也就是目标架构中的 `loop0`：一个稳定、可组合、可扩展的运行时内核。

核心只内置一个工具能力：`shell`。skills、MCP、memory、业务 channel、知识库、审批系统等都应通过 component 或外部集成扩展进来。

## 设计目标

loops 的第一性原理是把 Agent 拆成四类正交问题：

- 模型如何被调用：`Provider`
- 能力如何被暴露给模型：`Tool`
- 用户或系统如何与 Agent 交互：`Channel`
- 一次输入如何经过 prompt、模型、工具和状态提交形成结果：`Runtime`

核心 runtime 只负责协调这些对象，不承载具体业务能力。

## 非目标

当前核心刻意不做以下事情：

- 不内置 skills、MCP、memory backend、知识库、向量检索等高阶能力。
- 不把 Lark、定时任务、WebSocket、HTTP API 等业务通道写死进 runtime。
- 不把 provider 绑定到某一个云厂商或某一个模型协议。
- 不把复杂权限、审计、审批系统做成核心强依赖。
- 不默认开启有副作用工具的并行执行。

这些能力都可以在边界明确的组件层扩展。

## 总体结构

```text
User/System
    |
    v
Channel ---- UserInput ----+
                           |
                           v
                      AgentRuntime
                           |
        +------------------+------------------+
        |                  |                  |
        v                  v                  v
 PromptRenderer       Provider          ToolRegistry
        |                  |                  |
        v                  v                  v
 PromptRenderContext  ProviderResponse  ToolResult
                           |
                           v
                      AgentState
                           |
                           v
                      AgentResult
```

核心对象关系：

```text
Agent
  - spec: AgentSpec
  - state: AgentState
  - runtime: AgentRuntime
  - logger: EventLogger

AgentSpec
  - prompt: PromptTemplate
  - provider: Provider
  - tools: tuple[BaseTool, ...]
  - channels: tuple[Channel, ...]
  - components: tuple[Component, ...]
  - policy: AgentPolicy
  - metadata: dict
  - logger: LoggerLike
```

## 领域模型

### AgentSpec

`AgentSpec` 是 Agent 的不可变定义，描述这个 Agent 有什么 prompt、provider、tools、channels、components、policy 和 metadata。

关键属性：

- `prompt`: `PromptTemplate`，必须非空。
- `provider`: 模型适配器，必须存在。
- `tools`: 初始工具集合。通过 `agent(..., tools=None)` 创建时默认注入 `ShellTool()`。
- `channels`: 可用交互通道。未指定时 runtime 默认使用 `ConsoleChannel()`。
- `components`: 扩展单元，运行时按 run 贡献 prompt block、tool 等。
- `policy`: 控制最大轮数、工具错误、并发工具、shell 安全策略、审批等。
- `logger`: runtime event sink，可传标准库 logger、callable 或 loops `EventLogger`。

关键行为：

- `validate()`: 校验 prompt/provider/tool name 唯一性。
- `fork()`: 基于当前 spec 派生新 spec。
- `compile()`: 编译成长生命周期 `Agent`。

### Agent

`Agent` 是长生命周期对象。它持有 `AgentSpec`、`AgentState`、workspace 和 `AgentRuntime`。

关键行为：

- `run(input, thread_id=None, channel=None)`: 执行一次输入。
- `stream(input, ...)`: 当前是基于事件列表的便捷接口。
- `attach(...)`: 在共享 state/workspace 的基础上附加 tool/channel/component。
- `fork(...)`: 基于 state snapshot 派生新 Agent。
- `close()`: 触发 component teardown。

### AgentRuntime

`AgentRuntime` 是唯一的主循环拥有者，负责：

- setup components
- 解析 active channel 和 thread id
- 构造 `Run`
- 准备 prompt context
- 调用 provider
- 执行 tool calls
- 发送 channel events
- 记录 logger events
- 提交 state
- 返回 `AgentResult`

runtime 不应该直接实现业务能力。业务能力应在 `Provider`、`Tool`、`Channel` 或 `Component` 中实现。

### Run

`Run` 表示一次输入在 runtime 中的执行上下文。

关键属性：

- `run_id`: 一次执行的唯一 id。
- `thread_id`: 对话线程 id，用于读取和提交 history。
- `input`: `UserInput`。
- `channel`: 当前交互通道。
- `messages`: 本轮 provider 请求消息。
- `tool_registry`: 本轮可用工具集合。
- `contributions`: component 贡献结果。
- `prompt_context`: 渲染 prompt 时使用的结构化上下文。
- `pending_state_messages`: 本轮结束后要提交进 `AgentState` 的消息。
- `events`: 本轮产生的结构化事件。

### AgentState

`AgentState` 是 Agent 的长生命周期状态。

当前包含：

- `threads`: 每个 thread 的 history。
- `memories`: 一个最小内存记录模型。
- `artifacts`: 运行时产物索引。
- `component_state`: component 的私有状态空间。
- `checkpoints`: 预留 checkpoint 存储。

当前实现是内存态。持久化、外部 memory backend、压缩策略应通过 component 或后续 state adapter 扩展。

### PromptTemplate

`PromptTemplate` 包含 `system` 和 `user` 两个 Jinja2 模板。

模板输入是结构化 `PromptRenderContext`，包含：

- `agent`
- `provider`
- `channel`
- `tools`
- `components`
- `state`
- `input`
- `run`
- `policy`

示例：

```jinja2
You are {{ agent.name }}.
Channel: {{ channel.profile.name }}

Available tools:
{% for tool in tools %}
- {{ tool.name }}: {{ tool.description }}
{% endfor %}
```

设计约束：

- 模板引擎使用 Jinja2，不自研变量解析和控制流。
- prompt 只能从 profile/context 注入信息，不应直接访问 runtime 内部对象。
- component 只通过 `Contribution.prompt_blocks` 注入额外 prompt 内容。

### Provider

`Provider` 是模型后端适配层。

接口：

- `generate(request: ProviderRequest) -> ProviderResponse`
- `stream(request: ProviderRequest) -> AsyncIterator[ProviderEvent]`

`ProviderRequest` 关键字段：

- `messages`: provider-neutral 消息列表。
- `tools`: `ToolProfile` 列表。
- `stream`: 当前 channel 是否要求流式输出。
- `parallel_tool_calls`: 是否提示 provider 允许一次返回多个并行 tool call。
- `metadata`: run/thread 等 runtime 元数据。

`OpenAICompatibleProvider` 会把 `ProviderRequest` 转成 `/chat/completions` payload，并在有 tools 且 `parallel_tool_calls` 不为 `None` 时传递 `parallel_tool_calls`。

### Tool

`Tool` 是模型可调用能力。

核心协议：

```python
class BaseTool:
    profile: ToolProfile

    async def execute(self, ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        ...
```

`ToolProfile` 是 prompt 和 provider 暴露工具时的稳定描述，包含：

- `name`
- `description`
- `input_schema`
- `effects`
- `risk`
- `source`
- `requires_approval`
- `metadata`

`ToolContext` 包含：

- `agent_id`
- `run_id`
- `workspace`
- `policy`
- `state`
- `emit`
- `metadata`

设计约束：

- 工具负责自己的参数解释和副作用执行。
- runtime 只负责调用、事件、错误包装、并发调度和结果回填。
- tool output 必须通过 `ToolResult` 返回，避免直接写 provider message。

### ShellTool

`shell` 是核心唯一内置工具。

支持操作：

- `run`
- `list`
- `poll`
- `log`
- `write`
- `kill`

`run` 接受两种输入形态：

- `command`: 单条 shell 命令，保持最小兼容路径。
- `commands`: 多条 shell 命令，按顺序执行，遇到非零退出码、timeout 或取消立即停止。

为了兼容常见 shell tool 调用形态，`run` 同时接受：

- `timeout_seconds` 或 `timeout_ms`
- `max_output_chars` 或 `max_output_length`
- `cwd` / `working_directory`
- `env`

foreground `run` 内部把每条命令规范化成结构化输出：

- `command`
- `stdout`
- `stderr`
- `status`
- `outcome`

工具返回给模型的 `output` 仍是可读文本，结构化结果写入 `ToolResult.metadata["outputs"]`。单条成功命令继续返回裸 stdout；多条命令会带 `$ command` 前缀，便于模型区分不同命令的输出。

安全策略由 `AgentPolicy` 控制：

- `shell_timeout_seconds`
- `shell_max_output_chars`
- `shell_require_approval_for_background`
- `shell_external_path_policy`
- `approval_handler`

默认 shell policy 保守处理外部路径和后台任务。`background=True` 可以启动 shell session，但这不同于 runtime 的 tool call 并行调度。

### Channel

`Channel` 是 Agent 与外部世界交互的 I/O 端口。

接口：

- `receive() -> AsyncIterator[UserInput]`
- `send(event: AgentEvent) -> None`
- `default_context() -> ChannelContext`

`ChannelProfile` 描述通道能力：

- `interactive`
- `duplex`: `half` 或 `full`
- `output_mode`: `stream`、`message`、`update`、`none`
- `supports_interrupt`
- `supports_questions`
- `supports_approval`
- `supports_attachments`
- `delivery`
- `metadata`

典型通道：

- `ConsoleChannel`: 交互式、半双工、支持 streaming，默认 channel。
- `TuiChannel`: 基础 TUI profile，目前是 in-memory 行为。
- `LarkChannel`: 交互式、全双工、不支持 token streaming，适合聚合成消息。
- `ScheduledChannel`: 非交互式触发通道。

Channel 决定事件如何展示。比如 `ConsoleChannel` 会立即打印 `provider_delta`，并友好打印 tool call 的参数、状态、耗时和输出摘要。

### Component

`Component` 是扩展单元，不替代主循环。

生命周期：

- `setup(agent)`
- `contribute(run_context) -> Contribution`
- `handle_event(event)`
- `teardown()`

`Contribution` 可以贡献：

- `prompt_blocks`
- `tools`
- `channels`
- `hooks`
- `state_adapters`
- `metadata`

当前 runtime 已使用 `prompt_blocks` 和 `tools`。其他字段是架构预留，后续扩展时应保持向后兼容。

适合通过 component 扩展的能力：

- skills
- MCP tool discovery
- memory backend
- domain tools
- audit hook
- channel bridge
- policy adapter

### Logger

Logger 是 runtime event 的旁路观察者。

支持传入：

- `logging.Logger`
- `Callable[[AgentEvent], None]`
- 实现 `EventLogger.log_event(event)` 的对象
- `None`

内置：

- `NoopEventLogger`
- `StdlibEventLogger`
- `InMemoryEventLogger`
- `get_logger(...)`

Runtime 会在 `_emit_event_object` 中先记录 event，再发送给 channel 和 component。logger 失败不会影响主流程。

## Runtime 执行流程

一次 `Agent.run(...)` 的执行流程：

```text
Agent.run(input)
  -> UserInput.coerce
  -> AgentRuntime.run
     -> ensure component setup
     -> resolve channel
     -> resolve thread_id
     -> create Run
     -> prepare Run
        -> register spec tools
        -> collect component contributions
        -> build PromptRenderContext
        -> render system/user prompt
        -> load history
        -> build provider messages
     -> emit run_started
     -> provider/tool loop
        -> emit provider_started
        -> Provider.generate or Provider.stream
        -> emit provider_delta events when streaming
        -> emit provider_finished
        -> if no tool calls: finish
        -> append assistant tool-call message
        -> execute tool calls
        -> append tool messages in original tool_call order
        -> next provider turn
     -> commit state
     -> emit run_finished
     -> return AgentResult
```

失败路径：

```text
Exception
  -> emit run_failed
  -> logger/channel/components see event
  -> exception is re-raised
```

## Provider Streaming

Streaming 由 channel 决定：

```python
stream = run.channel.profile.output_mode == "stream"
```

当 `stream=True`：

- runtime 调用 `provider.stream(request)`
- provider 产生 `ProviderEvent(type="delta")`
- runtime 转成 `AgentEvent(type="provider_delta")`
- `ConsoleChannel` 等 stream channel 立即输出
- 最终 provider 必须给出 `ProviderEvent(type="response")`，用于工具调用和最终结果

当 channel 不是 stream 输出模式时，`provider_delta` 不会发送到 channel。

## Tool 并发模型

loops 区分两个并发控制：

### Provider hint

`AgentPolicy.parallel_tool_calls` 会写入 `ProviderRequest.parallel_tool_calls`。

OpenAI-compatible provider 会把它序列化成 API payload 的 `parallel_tool_calls` 字段。

含义：告诉模型是否允许在一个 turn 中返回多个 tool call。

### Runtime concurrency

`AgentPolicy.max_parallel_tool_calls` 控制本地 runtime 是否并发执行同一轮的多个 tool call。

- 默认值是 `1`，即串行执行。
- 设置为大于 `1` 时，用 asyncio task 并发执行。
- 设置为 `None` 时，不限制并发数量。

并发执行时，事件可能按实际完成顺序产生，但 tool message 会按 provider 返回的原始 `tool_calls` 顺序 append 回 `run.messages`。

这个顺序稳定性很重要。模型下一轮看到的上下文必须和它发出的 tool call 顺序对应。

示例：

```python
AgentPolicy(
    parallel_tool_calls=True,
    max_parallel_tool_calls=4,
)
```

设计约束：

- 默认不并发，避免 shell 和其他有副作用工具产生非预期竞态。
- 后续可以在 `ToolProfile.metadata` 或 policy 中进一步声明 per-tool concurrency safety。
- 对文件系统、进程、网络等副作用工具，并发应由 host 明确开启。

## Event 模型

`AgentEvent` 是 runtime、channel、component、logger 之间的统一事件。

当前关键事件：

- `run_started`
- `run_finished`
- `run_failed`
- `provider_started`
- `provider_delta`
- `provider_reasoning_delta`
- `provider_finished`
- `tool_started`
- `tool_finished`

事件传播顺序：

```text
runtime emits event
  -> append run.events
  -> logger.log_event(event)
  -> channel.send(event)
  -> component.handle_event(event)
```

其中 channel 可能根据 profile 过滤事件，例如非 stream channel 不接收 `provider_delta`。

## State 提交模型

runtime 使用 `pending_state_messages` 暂存本轮要提交的消息。

正常完成时提交：

- user message
- assistant final message

工具调用中间消息用于 provider loop，不直接提交到长期 thread history。这样 history 保持用户输入和最终 assistant 输出为主，避免无限膨胀。

后续如果需要完整 trace 或 tool transcript，应通过 logger/event store/component 扩展，而不是把所有 runtime 中间消息塞进 thread history。

## 扩展边界

### 增加新 Provider

实现：

- `profile`
- `generate`
- 可选 `stream`

Provider 内部负责协议转换，runtime 只理解 `ProviderRequest` 和 `ProviderResponse`。

### 增加新 Tool

实现：

- `profile: ToolProfile`
- `execute(ctx, args) -> ToolResult`

工具应把业务输出写入 `ToolResult.output`，把结构化元数据写入 `ToolResult.metadata`。

### 增加新 Channel

实现：

- `profile: ChannelProfile`
- `receive`
- `send`

Channel 的 metadata 应描述自身交互特征，而不是让 runtime 用类型判断行为。

### 增加新 Component

实现：

- `setup`
- `contribute`
- `handle_event`
- `teardown`

Component 是 skills、MCP、memory 等扩展能力的默认入口。

## 当前目录映射

```text
loops/
  agent.py          AgentSpec, Agent, agent factory
  runtime.py        AgentRuntime, Run, AgentResult
  prompt.py         PromptTemplate, PromptRenderContext, Jinja2 renderer
  policy.py         AgentPolicy, ApprovalRequest
  profiles.py       Profile and prompt-injected view objects
  state.py          AgentState, MemoryRecord, ThreadState
  events.py         AgentEvent
  logging.py        EventLogger adapters and formatting helpers
  providers/        Provider protocol and OpenAI-compatible adapter
  tools/            Tool protocol and ShellTool
  channels/         Channel protocol and built-in channels
  components/       Component protocol and Contribution
examples/
  start_agent.py    DeepSeek/OpenAI-compatible console example
tests/
  test_loops_core.py
```

## 设计决策记录

### 只内置 shell

shell 是最底层、最通用的 runtime capability。其他能力都可以通过 shell 或 component 演化出来，但不应成为核心强依赖。

### Prompt 使用 Jinja2

模板能力交给成熟库，runtime 只负责构建结构化上下文和注册少量 serialization filter。

### Channel 用 profile 描述能力

runtime 不能硬编码 `LarkChannel`、`ConsoleChannel` 等具体类型。它只根据 `ChannelProfile` 判断 streaming、交互性等行为。

### Logger 是旁路，不影响主流程

logger 用于观测、审计和调试，不能因为日志系统故障阻断 agent run。

### Tool 并发默认关闭

并发工具会改变副作用顺序。默认串行符合最小惊讶原则；需要并发时由 host 显式配置。

## 后续演进方向

- per-tool concurrency safety 声明。
- 更完整的 hook 生命周期。
- component 贡献 channels/hooks/state adapters 的 runtime 支持。
- 持久化 AgentState backend。
- event store 和可重放 trace。
- channel 级审批、问题询问和 interrupt 协议。
- provider capability negotiation。
