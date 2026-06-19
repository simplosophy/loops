# loops Stack Architecture

> **2026-06-19 重新定位**：loops 已从"三层软件架构"升级为"三层协议栈规范"。
> 既有 `loop0/loop1/loop2` 软件分层仍然有效，现在被理解为**协议栈各层的参考实现**。
> 完整协议栈设计见 [`docs/plans/2026-06-19-loops-protocol-stack.md`](../plans/2026-06-19-loops-protocol-stack.md)。

## loops 协议栈（AI 协作的 OSI 模型）

loops 的核心贡献是把已有 AI 协作协议（MCP、Skills、A2A）分层归位，定义层间契约，并填补生态缺失的人机协作协议：

```text
  ┌───────────────────────────────────────────────────────────┐
  │  L2  HACP   Human-Agent Collaboration Protocol            │  loops 新建 ★
  │      Task · Checkpoint · Ownership · Review               │  填补生态空白
  │      Artifact · Ledger · Audit                            │
  ├───────────────────────────────────────────────────────────┤
  │  层间契约：Task→AAP delegate / Checkpoint→AAP block        │
  ├───────────────────────────────────────────────────────────┤
  │  L1  AAP    Agent-Agent Protocol                          │  复用 A2A ★
  │      delegate · handoff · discovery                       │  /ACP/AGNTCY
  ├───────────────────────────────────────────────────────────┤
  │  层间契约：CapabilityRef (id+version, 不感知 transport)    │
  ├───────────────────────────────────────────────────────────┤
  │  L0  CAP    Capability Protocol                           │  复用 MCP ★
  │      Tool (单函数) · Skill (打包能力)                      │  + Skills 协议
  └───────────────────────────────────────────────────────────┘

  横切：依赖只能向下 L2→L1→L0；跨层只走契约对象；状态归属分层所有
```

## 既有软件分层（现为协议栈的参考实现）

本文定义 `loops/loop0/loop1/loop2` 三层架构的目标边界、状态所有权和扩展点。当前代码已经将单 Agent runtime 收敛到 `loops/loop0/`；`loop1` 和 `loop2` 仍是后续演进目标。

## 总体分层

```text
loops/
  loop0/    单个 Agent 运行时内核
  loop1/    单用户 Agent Container
  loop2/    多用户 / 组织级 Runtime Organizer
```

三层的职责可以压缩成三句话：

- `loop0` owns execution：负责一次 Agent run 如何被执行。
- `loop1` owns interaction：负责一个用户如何通过 channel、session 和 storage 使用多个 Agent。
- `loop2` owns coordination：负责多个用户、多个 loop1 如何在项目空间内协同运行。

对应的核心单位：

```text
loop0: Run / Agent
loop1: Session / UserRuntime
loop2: ProjectSpace / OrgRuntime
```

## 分层原则

- 依赖方向只能向下：`loop2 -> loop1 -> loop0`。低层不能 import 或感知高层。
- 跨层通信必须通过显式协议：event、message、storage record、control command，不能直接修改下层内部对象。
- 状态归属必须清晰：谁创建、谁持久化、谁负责一致性，必须由所属层定义。
- 扩展点应靠近其状态所有者：tool/provider/prompt 属于 loop0，channel/session/storage 属于 loop1，project/policy/scheduler 属于 loop2。
- 下层只暴露能力，不承载上层业务语义。loop0 不知道用户、项目、组织；loop1 不知道跨用户项目治理；loop2 不直接执行 Agent turn。

## loop0: Agent Runtime Kernel

### 边界

`loop0` 是单个 Agent 的最小运行时内核。它只关心一次输入如何经过 prompt、provider、tool 和 state commit 形成输出。

输入输出边界：

```text
UserInput + AgentSpec + AgentState
  -> AgentRuntime
  -> AgentEvent stream + AgentResult
```

`loop0` 可以被 CLI、测试、loop1 container 或其他 embedding host 调用，但它不负责这些 host 的 channel 协议。

当前代码已移除 loop0 内的 `Channel` protocol。TUI、WebUI、IM、Scheduler 等业务 channel 上移到 loop1；loop0 只保留 `InteractionContext`、显式 `stream` 参数和最小 `EventSink`，避免 runtime 内核依赖具体交互渠道。

### 负责

- 渲染 prompt。
- 调用 provider。
- 暴露和执行 tools。
- 应用 AgentPolicy。
- 维护单 Agent 的 thread/history/memory/artifact/checkpoint 状态模型。
- 产生结构化 AgentEvent。
- 提供单 Agent attach/fork/close 等生命周期操作。

### 不负责

- 用户身份、组织身份、权限系统。
- 多 Agent 路由、调度和协作。
- TUI、WebUI、IM、Webhook 等外部 channel 协议。
- 持久化存储选型，例如 SQLite、Postgres、S3。
- 项目空间、任务管理、跨用户协作。
- 云端部署、租户、计费、审计控制面。

### 状态

`loop0` 状态分为三类：

- 定义态：`AgentSpec`，包含 prompt、provider、tools、components、policy、metadata。
- 长生命周期态：`AgentState`，包含 threads、memories、artifacts、component_state、checkpoints。
- 单次运行态：`Run`，包含 run_id、thread_id、input、messages、tool_registry、contributions、pending_state_messages、events。

`loop0` 可以提供内存态默认实现，但持久化 backend 应由 loop1 注入或适配。

### 扩展点

- `Provider`: 模型后端适配。
- `Tool`: 模型可调用能力。
- `PromptTemplate` / `PromptRenderer`: prompt 构造。
- `AgentPolicy`: 轮数、并发、审批、安全策略。
- `Component`: 为单次 run 贡献 prompt block、tools 或事件处理逻辑。
- `EventLogger`: 观测、调试和 trace 输出。
- `StateAdapter`: 后续可引入，用于把 loop0 的状态读写委托给 loop1 storage。

## loop1: User Agent Container

### 边界

`loop1` 是单个用户的 Agent container。它可以持有多个 loop0 Agent，并负责把外部 channel 输入映射成 session 和 Agent run。

输入输出边界：

```text
ChannelMessage
  -> UserRuntime / Session / Router
  -> loop0 AgentRuntime
  -> ChannelOutput
```

`loop1` 面向一个用户或一个 user runtime，不处理组织级跨用户治理。跨用户协作必须由 loop2 通过明确的 project/session/task 协议协调。

### 负责

- 管理多个 loop0 Agent 的注册、创建、fork、关闭。
- 管理 session，把 channel conversation 映射到 agent thread 或多个 agent thread。
- 接入 channel：TUI、WebUI、IM、HTTP API、Webhook、Scheduler 等。
- 提供用户级 storage：history、memory、artifact、event trace、session record。
- 处理用户级 routing：选择目标 agent、agent group 或 handoff 策略。
- 维护 channel 连接状态、消息确认、外部 message id 映射。
- 管理用户级 credential、tool approval、interrupt、resource limit。
- 把 loop0 AgentEvent 转换成 channel 可消费的输出。

### 不负责

- 组织、团队、项目空间的全局权限模型。
- 多用户任务分配和跨用户协调。
- 云端 runtime placement、租户隔离、计费。
- 绕过 loop0 直接实现 provider/tool 主循环。
- 绕过 loop2 访问其他用户的 loop1 私有状态。

### 状态

`loop1` 状态围绕 UserRuntime 和 Session 展开：

- `UserRuntimeState`: 用户 runtime 配置、默认 agents、资源配额、credential references。
- `AgentRegistryState`: 当前用户可用 agents、agent profile、agent lifecycle、agent-to-storage binding。
- `SessionState`: session_id、user_id、channel_id、conversation_id、active_agent_id、thread mapping、pending approvals、interrupts。
- `ChannelState`: channel 类型、连接信息、外部消息游标、ack offset、delivery state。
- `StorageState`: threads、memories、artifacts、event traces、session records 的持久化索引。
- `RoutingState`: channel/session 到 agent 的路由策略、最近 handoff、fallback agent。

`loop1` 拥有持久化一致性：它决定何时从 storage 载入 loop0 状态，以及何时提交 run 后状态和 event trace。

### 扩展点

- `Channel`: TUI、WebUI、IM、Webhook、Scheduler、API channel。
- `SessionManager`: session 创建、恢复、过期、thread 映射。
- `Router`: 输入到 agent/agent group 的路由。
- `Storage`: 内存、文件、SQLite、Postgres、对象存储等 backend。
- `AgentFactory`: 根据 profile/template 创建 loop0 Agent。
- `CredentialProvider`: 用户级密钥、token 和外部系统授权。
- `ApprovalHandler`: 用户级审批、interrupt 和补充输入。
- `EventBus` / `Hook`: 订阅 loop0 events，驱动 UI、trace、notification、automation。
- `MemoryProvider`: 用户级 memory 检索、压缩和注入。

## loop2: Org Runtime Organizer

### 边界

`loop2` 是组织级和云端运行时的 organizer。它不执行单次 Agent run，而是管理多个用户的 loop1，并提供项目空间、跨用户协调和云端控制面。

输入输出边界：

```text
Org API / Project Event / Scheduler Command
  -> OrgRuntime / ProjectSpace / RuntimeScheduler
  -> UserRuntime command
  -> ProjectEvent / AuditEvent / SharedArtifact
```

`loop2` 可以创建、唤醒、调度或停止某个用户的 loop1，但具体 channel/session/agent run 仍由该 loop1 负责。

### 负责

- 管理 org、tenant、user、team、role。
- 创建和管理 project space。
- 管理多个 user loop1 的 runtime inventory、health、placement、lease。
- 协调跨用户、跨 agent 的项目任务、handoff、review、artifact 流转。
- 提供共享项目 storage：project artifacts、task graph、audit logs、shared memory index。
- 执行组织级 policy：权限、配额、审计、数据边界、secret reference。
- 提供云端 scheduler：定时任务、长任务、后台任务、project workflow。
- 对外暴露控制面 API 和项目管理 API。

### 不负责

- 直接执行 loop0 AgentRuntime。
- 直接修改 loop0 AgentState 内部结构。
- 直接读取其他用户 loop1 私有 storage，除非通过明确授权的 project/shared storage 协议。
- 绑定具体 IM/Web/TUI channel 协议细节。
- 在组织层硬编码某个 provider、tool 或 prompt。

### 状态

`loop2` 状态围绕组织、项目和 runtime 编排展开：

- `OrgState`: tenant、users、teams、memberships、roles。
- `ProjectSpaceState`: project_id、workspace、participants、roles、project settings。
- `RuntimeInventoryState`: user runtime 实例、runtime status、placement、lease、heartbeat。
- `CollaborationState`: project tasks、assignments、dependencies、handoff、review records。
- `SharedArtifactState`: 项目级文件、产物、引用、版本、权限。
- `SharedMemoryState`: 项目级知识、索引、摘要、可见性范围。
- `PolicyState`: RBAC/ABAC、quota、audit requirement、secret references、data boundary。
- `AuditState`: org/project/user/runtime 关键事件的不可变记录。

### 扩展点

- `RuntimeScheduler`: loop1 实例调度、唤醒、回收、健康检查。
- `ProjectWorkflow`: 项目任务流、阶段、依赖、审批。
- `PermissionPolicy`: 组织级访问控制和数据边界。
- `SharedStorage`: 项目 artifact、shared memory、audit log backend。
- `NotificationBridge`: 把 project event 投递到用户 loop1/channel。
- `BillingQuotaProvider`: 配额、成本、计费统计。
- `ControlPlaneAPI`: 云端 API、admin UI、project management integration。
- `OrgConnector`: 组织通讯录、IM、工单、代码平台、文档系统集成。

## 跨层事件和控制协议

三层都应使用事件驱动的接口，但事件语义不同：

```text
loop0: AgentEvent
  run_started, provider_delta, tool_started, tool_finished, run_finished

loop1: SessionEvent / ChannelEvent
  session_started, message_received, route_selected, output_delivered

loop2: ProjectEvent / RuntimeEvent / AuditEvent
  task_assigned, runtime_started, handoff_requested, artifact_published
```

推荐的调用链：

```text
ChannelMessage
  -> loop1 SessionManager
  -> loop1 Router
  -> loop0 Agent.run
  -> loop0 AgentEvent stream
  -> loop1 EventBus
  -> ChannelOutput
  -> loop2 ProjectEvent/AuditEvent when project-scoped
```

跨用户协作不共享裸 AgentState。loop2 应通过 `ProjectTask`、`HandoffRequest`、`SharedArtifact`、`ProjectEvent` 等显式对象协调不同用户的 loop1。

## 目标目录布局

目标代码布局倾向如下：

```text
loops/
  loop0/
    agent.py
    runtime.py
    io.py
    prompt.py
    policy.py
    state.py
    events.py
    providers/
    tools/
    components/

  loop1/
    container.py
    session.py
    channel.py
    router.py
    storage.py
    event_bus.py
    approvals.py
    credentials.py
    channels/
    storage_backends/

  loop2/
    org.py
    project.py
    scheduler.py
    collaboration.py
    policy.py
    audit.py
    shared_storage.py
    control_plane.py
```

顶层 `loops/__init__.py` 可以继续 re-export 稳定公共 API，以便包内部迁移不破坏用户导入路径。

## 演进顺序

建议按以下顺序落地：

1. 已完成：将当前单 Agent runtime 收敛为 `loops/loop0/`。
2. 已完成：移除 loop0 channel 层，改为 `InteractionContext` + `EventSink`。
3. 引入 loop1 的协议对象：`ChannelMessage`、`ChannelOutput`、`SessionState`、`Storage`、`LoopContainer`。
4. 用内存 storage 和 TUI channel 实现最小 loop1，支持单用户多 Agent。
5. 增加 WebUI/IM channel 和持久化 storage adapter。
6. 引入 loop2 的 project/runtime 协议，但先只做控制面和 project state，不直接做复杂调度。
7. 在 loop2 上增加跨用户 task/handoff/shared artifact 协作。

## 待确认问题

- loop1 的 multi-agent 第一版是只做 router，还是要包含 planner/task graph。
- `AgentState` 持久化 adapter 是放在 loop0 interface 还是完全由 loop1 storage 包装。
- loop2 的 project shared memory 是否允许被 loop1 自动注入 prompt，还是必须由用户/策略显式授权。
- 跨用户 handoff 的最小协议字段和审批流程。
