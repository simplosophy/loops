# loop0 Architecture Overview

本文定义 `loops.loop0` 的当前目标架构。`loop0` 是单个 Agent 的运行时内核，只负责一次 Agent run 的执行；`loop1` 才负责 TUI、WebUI、IM、scheduler 等 channel 协议，`loop2` 负责组织级项目协作和云端运行时编排。

## 设计边界

`loop0` 的职责是把一次输入变成一次可观测、可提交状态的 Agent run：

```text
UserInput + AgentSpec + AgentState
  -> AgentRuntime
  -> AgentEvent* + AgentResult
```

`loop0` 不拥有用户、channel、session、storage backend、项目空间或组织协作语义。embedding host 可以是 CLI、测试、loop1 container 或其他服务，但 host 只能通过显式输入、事件输出和状态接口嵌入 loop0。

## 核心原则

- 极简：核心只内置一个默认 tool：`shell`。skills、MCP、memory backend、业务系统连接都通过 component、tool、provider 或上层容器扩展。
- 正交：provider 只负责模型，tool 只负责可调用能力，prompt 只负责上下文组装，runtime 只负责执行循环和事件。
- 分层：loop0 不能 import 或感知 loop1/loop2。跨层通信通过 `UserInput`、`InteractionContext`、`EventSink`、`AgentEvent` 和 `AgentResult`。
- Fail Fast：spec 校验、provider/tool 错误、policy 拒绝应快速暴露，不在 runtime 内长时间阻塞。
- 约定优先：默认 state、workspace、shell tool 和 prompt renderer 可直接使用，高级 host 再按需注入替代实现。

## 运行时模型

```text
AgentSpec
  prompt: PromptTemplate
  provider: Provider
  tools: tuple[BaseTool, ...]
  components: tuple[Component, ...]
  policy: AgentPolicy
  metadata: dict
  logger: EventLogger

Agent
  spec: AgentSpec
  state: AgentState
  runtime: AgentRuntime

Run
  run_id
  thread_id
  input: UserInput
  interaction: InteractionContext
  event_sink: EventSink
  stream: bool
  messages
  tool_registry
  contributions
  events
  pending_state_messages
```

`AgentSpec` 是 Agent 的不可变定义。`AgentState` 是长生命周期状态。`Run` 是单次执行态，只在一次 `Agent.run()` 内存在。

## Public API

```python
result = await agent0.run(
    "inspect the workspace",
    thread_id="default",
    event_sink=sink,
    stream=True,
)
```

`Agent.run()` 的核心参数：

- `input`: `str | UserInput`，一次运行的用户输入。
- `thread_id`: 可选 thread 选择器，优先级高于 `InteractionContext.thread_id`。
- `event_sink`: 可选事件输出端，实现 `async send(AgentEvent)` 或传入 callback。
- `stream`: 是否请求 provider streaming，并向 `event_sink` 发送 `provider_delta`。

`Agent.stream()` 是便利 API：它以 `stream=True` 执行一次 run，并回放该 run 的事件。

## UserInput 与 InteractionContext

`UserInput` 只描述输入内容和输入附带的元信息：

```python
UserInput(
    text="hello",
    attachments=[],
    metadata={},
    interaction_context=InteractionContext(source="console", session_id="s1"),
)
```

`InteractionContext` 是 loop0 接收的最小交互上下文，不是 channel：

- `source`: 输入来源名称，例如 `direct`、`console`、`web`、`im`、`scheduled`。
- `session_id`: 上层 session id，可用于默认 thread 选择。
- `thread_id`: 目标 Agent thread。
- `actor_id`: 上层用户或系统 actor 标识。
- `reply_to`: 上层消息 id 或回包目标。
- `audience`: `user`、`group` 或 `system`。
- `interactive`: 这次输入是否允许交互式追问或审批。
- `stream`: 当前 run 是否请求 streaming。
- `locale`: 语言区域。
- `raw`: 上层保留的原始协议字段。

loop0 可以把这些字段注入 prompt，也可以把它们写入事件 payload，但不能根据具体 channel 类型分支。

## Prompt Context

Prompt 使用 Jinja2 渲染，模板可以访问稳定的结构化上下文：

- `agent`
- `provider`
- `interaction`
- `tools`
- `components`
- `state`
- `input`
- `run`
- `policy`

示例：

```jinja2
You are {{ agent.name }}.
Input source: {{ interaction.source }}
Streaming: {{ interaction.stream | json }}

Available tools:
{% for tool in tools %}
- {{ tool.name }}: {{ tool.description }}
{% endfor %}
```

prompt 层不应依赖上层 channel 对象。需要上层协议信息时，由 loop1 映射成 `InteractionContext` 或 `UserInput.metadata`。

## EventSink

`EventSink` 是 loop0 的最小输出端口：

```python
class EventSink(Protocol):
    async def send(self, event: AgentEvent) -> None:
        ...
```

内置实现：

- `NullEventSink`: 默认 sink，丢弃事件。
- `InMemoryEventSink`: 收集事件，适合测试和 embedding。
- `CallableEventSink`: 包装 sync/async callback。

runtime 对所有事件执行同一条路径：

```text
emit AgentEvent
  -> append run.events
  -> EventLogger.log_event
  -> EventSink.send
  -> Component.handle_event
```

`EventSink` 不做 channel 协议、ack、retry、message id 映射或 UI 格式化。这些都属于 loop1。

## Provider

`Provider` 是模型后端接口：

```python
async def generate(request: ProviderRequest) -> ProviderResponse
async def stream(request: ProviderRequest) -> AsyncIterator[ProviderEvent]
```

`ProviderRequest` 包含：

- `messages`
- `tools`
- `stream`
- `parallel_tool_calls`
- `metadata`

`ProviderResponse` 包含：

- `content`
- `tool_calls`
- `usage`
- `stop_reason`
- `message_metadata`
- `raw`

Provider adapter 层把不同模型 API 统一成 loop0 的 provider 协议：

- `ProviderModel`: provider、model、api、capabilities、limits、metadata。
- `ProviderOptions`: api_key、base_url、headers、timeout、metadata。
- `ProviderAdapter`: 具体 API 协议适配器。
- `AdapterBackedProvider`: loop0 runtime 使用的 provider 包装。

OpenAI-compatible API 由 `OpenAIChatAdapter` 实现，`OpenAICompatibleProvider` 是便利用法。

## Tool

`Tool` 是模型可调用能力。每个 tool 必须提供 `ToolProfile`：

- `name`
- `description`
- `input_schema`
- `effects`
- `risk`
- `source`
- `requires_approval`
- `metadata`

runtime 只通过 `ToolRegistry` 找到 tool 并调用：

```python
await tool.execute(ctx, args)
```

`ToolContext` 提供 run_id、workspace、policy、state、metadata 和 `emit` callback。tool 可以发出自定义 `AgentEvent`，但不能直接依赖 channel、session 或 loop1 storage。

## Component

`Component` 是 loop0 的组合扩展点：

- `setup(agent)`
- `contribute(run_context) -> Contribution`
- `handle_event(event)`
- `teardown()`

`Contribution` 当前可以贡献：

- `prompt_blocks`
- `tools`
- `metadata`

component 可以观察事件、注入工具、注入 prompt block，但不拥有 runtime 主循环。

## AgentPolicy

`AgentPolicy` 管理单 run 的执行约束：

- `max_turns`
- `allow_tool_errors`
- `approval_handler`
- `parallel_tool_calls`
- `max_parallel_tool_calls`
- `metadata`

审批函数属于 policy，但真正的用户交互通道属于上层 host。loop0 只调用 handler 并处理允许/拒绝结果。

## State

`AgentState` 维护单 Agent 的状态模型：

- threads/history
- memories
- artifacts
- component_state
- checkpoints

runtime 只在 run 成功结束后提交 pending messages。持久化 backend 不在 loop0 内硬编码；loop1 后续可以通过 state adapter 或 agent factory 注入持久化状态。

## Streaming

Streaming 由 `Agent.run(stream=True)` 显式请求，而不是由 channel profile 隐式决定。

```text
stream=True
  -> ProviderRequest.stream=True
  -> provider.stream(...)
  -> provider_delta events
  -> EventSink.send(...)
```

如果 `stream=False`，runtime 调用 `provider.generate(...)`，不会生成 `provider_delta`。上层如果需要把 token 流变成 IM 消息聚合、WebSocket 推送或 TUI 输出，应在 loop1 的 channel adapter 中处理。

## Logging

`EventLogger` 是观测接口，和 `EventSink` 分离：

- logger 面向日志、trace、调试；
- sink 面向 embedding host 的运行事件消费。

logger 失败不会中断主流程。event sink 失败会快速暴露，因为 sink 是 host 接入 loop0 的显式 IO 边界。

## loop0 不包含 Channel

明确删除 loop0 channel 层：

- 没有 `Channel` protocol。
- 没有 `ChannelProfile` / `ChannelContext`。
- 没有 `ConsoleChannel` / `TuiChannel` / `LarkChannel` / `ScheduledChannel`。
- 没有顶层 `loops.channels` 兼容入口。

原因：

- channel 需要 session、连接状态、消息确认、重试、外部 message id、用户身份和 storage，这些都是 loop1 状态。
- runtime 只需要知道本次 run 是否 streaming，以及把事件交给谁。
- prompt 只需要稳定的 `interaction` 视图，不应感知具体 channel 实现。

loop1 后续可以定义：

```text
ChannelMessage -> Session -> Agent.run(..., event_sink=...)
AgentEvent -> ChannelOutput
```

## 目录结构

当前 loop0 目录：

```text
loops/loop0/
  agent.py
  runtime.py
  io.py
  prompt.py
  profiles.py
  policy.py
  state.py
  events.py
  logging.py
  types.py
  providers/
  tools/
  components/
```

各文件职责：

- `agent.py`: public Agent / AgentSpec / factory。
- `runtime.py`: provider/tool 主循环和 run 生命周期。
- `io.py`: `EventSink`、`NullEventSink`、`InMemoryEventSink`、callback adapter。
- `prompt.py`: prompt template、render context 和 renderer。
- `profiles.py`: prompt 可注入的稳定 profile/view 对象。
- `policy.py`: 执行策略和审批请求。
- `state.py`: 单 Agent 状态。
- `events.py`: `AgentEvent`。
- `logging.py`: event logger。
- `types.py`: provider-neutral message、tool call、user input。
- `providers/`: provider 协议和 adapter。
- `tools/`: tool 协议和内置 shell tool。
- `components/`: component 协议。

## 扩展规则

新增 provider：

- 实现 `Provider`，或实现 `ProviderAdapter` 后用 `AdapterBackedProvider`。
- 将 provider 能力写进 `ProviderProfile.capabilities`。
- 不在 runtime 中写 provider 特判。

新增 tool：

- 实现 `BaseTool.execute`。
- 提供准确的 `ToolProfile` 和 JSON schema。
- 高风险能力通过 `AgentPolicy.approval_handler` 请求审批。

新增 prompt 能力：

- 优先通过 `PromptRenderContext` 中已有 profile/view 暴露。
- 新字段必须是稳定抽象，不能泄漏上层 channel/session 对象。

新增外部输入输出：

- 不放进 loop0。
- 在 loop1 中实现 channel/session/storage。
- 把输入映射为 `UserInput + InteractionContext`。
- 把输出映射为 `EventSink` 或消费 `AgentResult.events`。

## 当前优先级

1. 继续稳定 loop0 的 provider/tool/prompt/state/io 抽象。
2. 保持 loop0 API 小而明确，避免重新引入 channel/session/storage。
3. 后续再启动 loop1：定义 `ChannelMessage`、`ChannelOutput`、`SessionState`、`Storage`、`LoopContainer`。
4. loop2 在 loop1 稳定后再承接项目空间、跨用户 task/handoff/shared artifact。
