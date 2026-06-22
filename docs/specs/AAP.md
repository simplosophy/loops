# AAP — Agent-Agent Protocol

| | |
|---|---|
| **规范版本** | 0.1.0-draft |
| **状态** | Draft |
| **所属栈** | [Loops Protocol Stack](../plans/2026-06-19-loops-protocol-stack.md) |
| **层级** | L1（栈中层） |
| **文档类型** | **一致性剖面（Conformance Profile）** —— 不是新协议规范 |

---

## 0. 本文档是什么，不是什么

**AAP 不是一份重新发明的协议规范。** agent 间通信的事实竞争者（A2A、ACP、AGNTCY）已经存在。

**AAP 是 Loops 栈对 L1 层定义的"最小接口契约"**：要成为 Loops 栈的合格 L1，一个 agent 网格（agent mesh）必须暴露什么接口、承担什么一致性责任。任何满足本剖面的现有实现（A2A runtime、ACP broker）都可以直接接入 Loops 栈，无需改造。

### 与 HLP 的文档形态差异

| | HLP.md | AAP.md（本文档） |
|---|---|---|
| 性质 | 完整协议规范（新建协议） | 一致性剖面（复用已有协议） |
| 定义 | 协议本身 | 层间接口最小契约 |
| schema | 全套自研 | 引用已有协议 schema |

---

## 1. 摘要

AAP（Agent-Agent Protocol）定义 **agent ↔ agent 如何发现彼此、委派工作、交接上下文**。

### 1.1 三个核心原语

| 原语 | 语义 | 类比 |
|------|------|------|
| **discover** | 按能力查找 agent | service registry |
| **delegate** | 把子任务交给另一个 agent | 函数调用（异步） |
| **handoff** | 把整个 ownership 转交给另一个 agent | 转单 / git 仓库转交 |

### 1.2 AAP 不管辖的事

- agent 内部如何执行 —— 那是 runtime 的事
- agent 怎么和人对话 —— 那是 HLP 的事
- agent 怎么调工具 —— 那是 CAP 的事
- agent 的生命周期管理 —— 那是宿主平台的事

### 1.3 规范性用语

使用 [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) 关键字。

---

## 2. 核心概念

### 2.1 Agent（执行单元）

```yaml
Agent:
  agent_id: string            # REQUIRED, 全局唯一
  capabilities: [CapabilityRef]  # REQUIRED, 此 agent 能提供的能力（引用 CAP）
  manifest: AgentManifest
```

### 2.2 AgentCard（发现对象）

agent 在网格中对外暴露的名片。**MUST** 可被 `discover` 查询到。

```yaml
AgentCard:
  agent_id: string
  name: string                # 人类可读名
  description: string
  capabilities: [CapabilityRef]  # 声明能做什么
  endpoint: string            # 如何到达（transport-specific）
  protocol: string            # "a2a" | "acp" | "agntcy" | 实现扩展
```

### 2.3 Run（agent 的一次执行实例）

```yaml
Run:
  run_id: string              # REQUIRED
  agent_id: string            # 执行者
  correlation_id: string      # REQUIRED, 关联到上层的 TaskID（HLP 契约）
  state: RunState
  created_at: timestamp

RunState: "running" | "blocked" | "completed" | "failed"
```

> `correlation_id` 是 AAP↔HLP 的关键契约字段（见 §5.1）。

---

## 3. 最小接口契约

### 3.1 发现（Discovery）

```yaml
agent.discover(query: DiscoveryQuery) -> [AgentCard]

DiscoveryQuery:
  capability: CapabilityRef | null   # 按能力查
  tags: [string] | null              # 按标签查
```

**一致性约束**：
- 合格 L1 **MUST** 支持 `agent.discover`。
- 返回的 AgentCard **MUST** 包含 endpoint。

### 3.2 委派（Delegation）

```yaml
agent.delegate(req: DelegateRequest) -> Run

DelegateRequest:
  to_agent: agent_id           # REQUIRED, 目标 agent
  task_id: string              # REQUIRED, 上层 TaskID（作为 correlation_id）
  capability: CapabilityRef    # REQUIRED, 要调用哪个能力
  input: object                # REQUIRED
  parent_run: run_id | null    # OPTIONAL, 支持链式委派

DelegateRequest -> Run:
  # 同步返回 Run 句柄，执行异步
```

**一致性约束**：
- `delegate` **MUST** 返回 Run 句柄，不阻塞等待完成。
- `task_id` **MUST** 被设为 Run.correlation_id，贯穿到所有子事件。
- 失败时 **MUST** 产生 `run.failed` 事件。

### 3.3 阻塞与恢复（Block & Resume）

这是与 HLP Checkpoint 对接的关键接口。

```yaml
agent.block(run_id, reason: string, checkpoint_id: string) -> void
  # Run 进入 blocked 状态，等待 HLP checkpoint.resolve

agent.resume(run_id, resolution: object) -> void
  # Run 恢复执行，resolution 来自 HLP checkpoint.resolve
```

**一致性约束**：
- `block` **MUST** 带 checkpoint_id，关联到 HLP 的 Checkpoint。
- blocked 期间 agent **MUST NOT** 自行恢复，**MUST** 等待 `resume`。

### 3.4 交接（Handoff）

```yaml
agent.handoff(run_id, to_agent: agent_id, context: object) -> Run
  # 新 agent 接手，旧 Run 失效，新 Run 产出，correlation_id 保持
```

**一致性约束**：
- handoff **MUST** 保留原 correlation_id（同一 Task 不变）。
- handoff 是 ownership 转移在 AAP 层的体现，HLP 的 `ownership.transfer` 与之联动。

### 3.5 事件流（Event Stream）

合格 L1 **MUST** 产出以下事件，供 HLP 订阅：

```yaml
AgentEvent:
  run_id: string
  correlation_id: string       # = TaskID
  type: AgentEventType
  payload: object
  at: timestamp

AgentEventType:
  "run.started" | "run.progress" | "run.blocked" |
  "run.completed" | "run.failed"
```

### 3.6 错误码

| 码 | 语义 |
|----|------|
| `AGENT_NOT_FOUND` | 目标 agent 不存在或离线 |
| `CAPABILITY_NOT_SUPPORTED` | agent 不声明所需 capability |
| `DELEGATION_REFUSED` | agent 拒绝委派 |
| `RUN_NOT_FOUND` | run_id 无效 |
| `INVALID_TRANSITION` | 非法状态转移（如 completed→blocked） |

---

## 4. 参考实现映射

### 4.1 A2A → AAP

| AAP 契约 | A2A 实现 |
|----------|---------|
| `agent.discover` | Agent Card + discovery |
| `agent.delegate` | tasks/send (async) |
| Run 句柄 | A2A task 对象 |
| AgentEvent | task status updates |
| correlation_id | A2A task metadata |

**结论**：A2A 是 AAP 的首选参考实现。

### 4.2 ACP → AAP

ACP 提供类似的 agent 间消息语义，可映射到 AAP 的 delegate/handoff。ACP 的 session 模型比 AAP 更重（AAP 是无状态委派），实现需裁剪。

### 4.3 AGNTCY → AAP

AGNTCY 的 agent 网格概念直接匹配 AAP 的 discover 契约。

---

## 5. 层间契约

### 5.1 AAP ↔ HLP（L1 ↔ L2）—— 关键契约

这是 Loops 栈最关键的层间缝合点。HLP 的 Task 生命周期依赖 AAP 的 Run：

| HLP 操作 | AAP 联动 | correlation 约束 |
|----------|---------|-----------------|
| `task.assign` | `agent.delegate` | TaskID **MUST** = Run.correlation_id |
| `checkpoint.raise` | `agent.block` | CheckpointID **MUST** 传入 |
| `checkpoint.resolve` | `agent.resume` | resolution **MUST** 透传 |
| `ownership.delegate` | `agent.delegate`（子 agent） | parent_run 可追 |
| `ownership.transfer` (handoff) | `agent.handoff` | correlation_id 保持 |

**铁律**：TaskID **MUST** 全栈贯穿到最底层 Run。任何丢失 correlation 的实现都不符合 AAP。

### 5.2 AAP → CAP（L1 → L0）

agent 通过 CapabilityRef 调用能力（见 CAP.md §5.1）。AAP 层 **MUST NOT** 感知 CAP 的 transport 细节。

---

## 6. 一致性级别

声称"符合 AAP 0.1.0-draft"的实现 **MUST**：

1. 支持 `agent.discover` / `delegate` / `block` / `resume` / `handoff` 五个接口
2. 维护 Run 状态机（running/blocked/completed/failed）
3. 所有 Run 带 correlation_id 且全栈贯穿
4. 产出 §3.5 定义的事件流
5. 通过 §3.6 的错误码语义

实现 **MAY**：
- 选择底层协议（A2A / ACP / AGNTCY / 自研）
- 选择 transport
- 扩展 AgentCard 的自定义字段

---

## 7. 开放议题

| # | 议题 | 倾向 |
|---|------|------|
| 1 | agent 网格的拓扑（去中心化 vs broker） | 不规定，两种都符合 |
| 2 | delegate 的超时与重试 | 建议可配置，默认不重试 |
| 3 | 并发委派限流 | 留给实现 |
| 4 | agent 间信任与认证 | 留给宿主平台 |
| 5 | handoff 后旧 Run 的可见性 | 建议保留为只读历史 |
| 6 | 多 agent 协作（>2）的协议 | 当前只定义双边，多方未定 |

---

## 附录：变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.1.0-draft | 2026-06-19 | 首个 draft，定义 L1 最小接口剖面，映射 A2A/ACP/AGNTCY 参考实现 |
