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
  config: Loop0RunConfig
  provider: ProviderClient
  state: AgentState
  tools: ToolRegistry
  components: Vec<Component>

AgentRuntime
  config
  provider
  state
  tools
  components

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

`AgentSpec` 是 Agent runtime 的不可变定义。`AgentState` 是长生命周期状态。`Run` 是单次执行态，只在一次 `AgentRuntime::run_input()` 内存在。

## Public API

```rust
let result = runtime
    .run_input(UserInput::new("inspect the workspace", interaction), &mut sink)
    .await?;
```

`AgentRuntime::run_input()` 的核心参数：

- `input`: `UserInput`，一次运行的用户输入。
- `event_sink`: 事件输出端，实现 `EventSink`。
- `thread_id`: 由 `InteractionContext.thread_id`、`session_id` 或 config 默认值解析。
- `stream`: 由 `Loop0RunConfig.run.stream` 请求 provider streaming，并向 `event_sink` 发送 `provider_delta`。

CLI 是一个 one-shot embedding host：它把命令行/JSON 配置归一化成 `Loop0RunConfig`，再调用 Rust runtime。

## UserInput 与 InteractionContext

`UserInput` 只描述输入内容和输入附带的元信息：

```rust
UserInput::new(
    "hello",
    InteractionContext {
        source: "console".to_string(),
        session_id: Some("s1".to_string()),
        ..InteractionContext::default()
    },
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

Prompt 使用 MiniJinja 渲染，模板可以访问稳定的结构化上下文：

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

```rust
pub trait EventSink {
    fn send(&mut self, event: &AgentEvent) -> anyhow::Result<()>;
}
```

内置实现：

- `NullEventSink`: 默认 sink，丢弃事件。
- `InMemoryEventSink`: 收集事件，适合测试和 embedding。
runtime 对所有事件执行同一条路径：

```text
emit AgentEvent
  -> append run.events
  -> EventSink.send
  -> Component.handle_event
```

`EventSink` 不做 channel 协议、ack、retry、message id 映射或 UI 格式化。这些都属于 loop1。

## Provider

`Provider` 是模型后端接口：

```rust
#[async_trait]
pub trait ProviderClient {
    async fn complete(&self, request: ProviderRequest) -> anyhow::Result<ProviderOutput>;
}
```

`ProviderRequest` 包含：

- `messages`
- `tools`
- `stream`
- `parallel_tool_calls`

`ProviderResponse` 包含：

- `content`
- `tool_calls`
- `stop_reason`
- `raw`

OpenAI-compatible API 由 `OpenAiCompatibleProvider` 实现，支持非流式、streaming text/reasoning delta 和 streaming tool call delta folding。

## Tool

`Tool` 是模型可调用能力。每个 tool 必须提供 `ToolProfile`：

- `name`
- `description`
- `input_schema`

runtime 只通过 `ToolRegistry` 找到 tool 并调用：

```rust
#[async_trait]
pub trait ToolExecutor {
    fn profile(&self) -> ToolProfile;
    async fn execute(&self, ctx: &mut ToolContext<'_>, args: &Value) -> anyhow::Result<ToolResult>;
}
```

`ToolContext` 提供 run_id、workspace、policy、metadata 和 emitted_events。tool 可以发出自定义 `AgentEvent`，但不能直接依赖 channel、session 或 loop1 storage。

## Component

`Component` 是 loop0 的组合扩展点：

- `setup()`
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
- `parallel_tool_calls`
- `max_parallel_tool_calls`
- `auto_approve`
- `shell_timeout_seconds`
- `shell_max_output_chars`
- `shell_require_approval_for_background`
- `shell_external_path_policy`

当前 Rust CLI 是非交互 host：`auto_approve` 表示 CLI 对需要审批的 shell 操作直接允许。更细的交互式审批接口后续由 loop1 host 提供。

## State

`AgentState` 维护单 Agent 的状态模型：

- threads/history
- memories
- artifacts
- component_state
- checkpoints

runtime 只在 run 成功结束后提交 pending messages。持久化 backend 不在 loop0 内硬编码；loop1 后续可以通过 state adapter 或 agent factory 注入持久化状态。

## Streaming

Streaming 由 `Loop0RunConfig.run.stream` 显式请求，而不是由 channel profile 隐式决定。

```text
stream=True
  -> ProviderRequest.stream=True
  -> provider.complete(...)
  -> provider_delta events
  -> EventSink.send(...)
```

如果 `stream=False`，provider 不产生 `provider_delta`。上层如果需要把 token 流变成 IM 消息聚合、WebSocket 推送或 TUI 输出，应在 loop1 的 channel adapter 中处理。

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
ChannelMessage -> Session -> AgentRuntime::run_input(..., event_sink)
AgentEvent -> ChannelOutput
```

## 目录结构

当前 Rust loop0 目录：

```text
src/loop0/
  cli.rs
  component.rs
  config.rs
  dotenv.rs
  events.rs
  io.rs
  provider.rs
  runtime.rs
  shell.rs
  state.rs
  tool.rs
  types.rs
src/loop1/
  mod.rs
src/loop2/
  mod.rs
```

各文件职责：

- `cli.rs`: one-shot loop0 runner，把 CLI/config 归一化成 `Loop0RunConfig`。
- `component.rs`: component 协议、contribution 和 run context。
- `config.rs`: JSON/TOML config model、相对路径规则。
- `dotenv.rs`: `.env` 加载。
- `events.rs`: `AgentEvent` 构造。
- `io.rs`: `EventSink`、`NullEventSink`、`InMemoryEventSink`。
- `provider.rs`: provider 协议和 OpenAI-compatible provider。
- `runtime.rs`: provider/tool 主循环和 run 生命周期。
- `shell.rs`: 内置 shell tool 执行和 background session。
- `state.rs`: 单 Agent 状态。
- `tool.rs`: tool 协议、registry、context 和 result。
- `types.rs`: provider-neutral message、tool call、user input。
- `src/loop1/mod.rs`: 用户 runtime/container 的 channel message、session、container 状态边界。
- `src/loop2/mod.rs`: 组织/project organizer 的 org、project、runtime、task、handoff、event 状态边界。

## 扩展规则

新增 provider：

- 实现 `ProviderClient::complete`。
- 不在 runtime 中写 provider 特判。

新增 tool：

- 实现 `ToolExecutor::profile`。
- 实现 `ToolExecutor::execute`。
- 提供准确的 `ToolProfile` 和 JSON schema。
- 高风险能力通过 policy 与上层 host 审批接口处理。

新增 prompt 能力：

- 优先通过 `PromptRenderContext` 中已有 profile/view 暴露。
- 新字段必须是稳定抽象，不能泄漏上层 channel/session 对象。

新增外部输入输出：

- 不放进 loop0。
- 在 loop1 中实现 channel/session/storage。
- 把输入映射为 `UserInput + InteractionContext`。
- 把输出映射为 `EventSink` 或消费 `AgentResult.events`。

新增 CLI/config runner：

- 只能作为 one-shot loop0 host，不能引入 session/channel 状态。
- CLI 参数和配置文件必须归一化到同一个 config model。
- prompt 等大文本应支持从文件读取，文件路径相对 config 文件目录解析。
- provider、policy、agent metadata、run、interaction、output 参数都应能由命令行覆盖。

## 当前优先级

1. 继续稳定 loop0 的 provider/tool/prompt/state/io 抽象。
2. 保持 loop0 API 小而明确，避免重新引入 channel/session/storage。
3. 后续再启动 loop1：定义 `ChannelMessage`、`ChannelOutput`、`SessionState`、`Storage`、`LoopContainer`。
4. loop2 在 loop1 稳定后再承接项目空间、跨用户 task/handoff/shared artifact。
