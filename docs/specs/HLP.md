# HLP — Human Loop Protocol

| | |
|---|---|
| **规范版本** | 0.1.0-draft |
| **状态** | Draft — 等待参考实现验证 |
| **定位** | HLP-first：本项目核心协议，下层通过既有 agent / capability 生态接入 |
| **层级** | 人机责任闭环层 |
| **设计稿** | [`docs/plans/2026-06-19-loops-protocol-stack.md`](../plans/2026-06-19-loops-protocol-stack.md) |

---

## 1. 摘要

HLP（Human Loop Protocol，人机责任闭环协议）定义**人**与**自主 agent** 如何围绕一个有边界的工作单元（**Task**）进行委派、把关、交付与治理。它是本项目的核心协议，填补了 MCP / Agent Skills（agent↔工具）和 A2A / ACP / AGNTCY（agent↔agent）未覆盖的维度：**agent 与其负责人之间的责任闭环语义**。

HLP 是 transport-agnostic 的语义规范。本规范定义"协议说什么"，不规定"用什么线缆说"。

### 1.1 规范性用语

本规范使用 [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) 关键字：**MUST**、**MUST NOT**、**SHOULD**、**SHOULD NOT**、**MAY**。大写形式表示规范性约束。

### 1.2 适用范围

HLP 管辖：人↔agent 围绕 Task 的协作（委派、审批、交付、评审、状态沉淀、审计）。

HLP **不**管辖：
- agent 内部如何执行（实现自由）
- agent ↔ agent 委派（由既有 L1 agent 协议或 runtime 定义）
- agent ↔ 工具调用（由既有 L0 capability 协议或 runtime 定义）
- UI 渲染与通知送达（HLP 产出事件，channel 由 loop1 实现）
- 组织级 RBAC（HLP 只声明 ownership，权限模型留给实现）

---

## 2. 核心概念

### 2.1 角色（Roles）

| 角色 | 说明 |
|------|------|
| **principal** | 最终负责人，**MUST** 是人。创建 Task，承担最终责任。一个 Task 的 principal **MUST NOT** 在其生命周期内变更。 |
| **assignee** | 当前执行者，**MAY** 是人或 agent。随协议操作流转。 |
| **reviewer** | 对 Artifact 进行 Review 的人，**MUST** 是人。**MAY** 与 principal 不同。 |

### 2.2 一等对象（First-Class Objects）

HLP 定义 7 个一等对象。实现 **MUST** 支持全部 7 个。

| 对象 | 作用域 | 生命周期 |
|------|--------|---------|
| Task | 协作流主语 | 创建到 completed |
| Checkpoint | 挂在 Task 上 | raise 到 resolved/expired |
| Ownership | Task 的凭证 | 随 Task 存在，assignee 可流转 |
| Review | 针对 Artifact | submit 后不可变 |
| Artifact | Task 的交付物 | **独立于 Task**，不可变 + 版本链 |
| Ledger | 组织级状态 | scope-scoped，append-only |
| Audit | 观测平面 | append-only，永不删 |

### 2.3 不可变性与前进性（Immutability & Forward-Only）

HLP 是**只前进协议**（forward-only protocol）：

- Task 的 `spec` 创建后 **MUST NOT** 修改。要改变意图就 `task.cancel` + 新建。
- Artifact 创建后 **MUST NOT** 修改。要改就 commit 新版本。
- Ledger 条目 **MUST NOT** 删除。纠错靠追加新条目。
- Review 提交后 **MUST NOT** 修改。要改意见就追加新 Review。
- Audit 事件 **MUST NEVER** 删除或修改。

此约束保证整个协议**可重放、可审计**。

---

## 3. 对象 Schema

### 3.1 标识符规范

所有对象 ID **MUST** 使用 [ULID](https://github.com/ulid/spec)，带类型前缀：

| 对象 | 前缀 | 示例 |
|------|------|------|
| Task | `task_` | `task_01HXY8KQ...` |
| Checkpoint | `ckpt_` | `ckpt_01HXY9JR...` |
| Review | `rev_` | `rev_01HXYA0S...` |
| Artifact | `art_` | `art_01HXYB1T...` |
| Ledger | `led_` | `led_01HXYC2U...` |
| AuditEvent | `aud_` | `aud_01HXYD3V...` |
| Ownership | 无独立 ID（Task 子对象） | — |

时间戳 **MUST** 使用 RFC 3339 UTC。

### 3.2 Task

```yaml
Task:
  id: task_                    # REQUIRED, ULID
  type: string                 # REQUIRED, 实现可扩展的 Task 类型
  spec: TaskSpec               # REQUIRED, 创建后不可变
  ownership: Ownership         # REQUIRED
  state: TaskState             # REQUIRED
  parent_task: task_ | null    # OPTIONAL, 支持子任务拆分
  created_at: timestamp        # REQUIRED
  deadline: timestamp | null   # OPTIONAL
  checkpoints: [ckpt_]         # 挂载的 Checkpoint ID
  artifacts: [art_]            # 产出的 Artifact ID
  audit_trail: aud_            # 指向 audit 聚合根

TaskSpec:
  goal: string                 # REQUIRED, 自然语言目标
  acceptance_criteria: [string]  # RECOMMENDED
  inputs: [InputRef]           # OPTIONAL
  constraints: Constraints     # OPTIONAL

InputRef:
  kind: "artifact" | "resource"
  id: string                   # kind=artifact 时为 art_
  version: string              # kind=artifact 时 REQUIRED
  uri: string                  # kind=resource 时 REQUIRED

Constraints:
  max_duration: duration       # OPTIONAL
  must_use_capabilities: [cap] # OPTIONAL, CapabilityRef
```

**一致性约束**：
- `spec` 在 `task.create` 后 **MUST NOT** 变更。
- `ownership.principal` **MUST** 在创建时设定，且 **MUST NEVER** 变更。
- `state` 转移 **MUST** 遵守 §4.1 状态机。

### 3.3 TaskState 状态机

```text
                    ┌──────────────────────────────────────┐
                    │                                      ▼
  created ──▶ assigned ──▶ in_progress ──┐         blocked
                │              │         │              │
                │              │         └──────────────┘
                │              ▼              resolve
                │         review_ready ──▶ under_review ──┐
                │              │                    │      │ changes_requested
                │              │                    │      ▼
                │              │                    └─→ in_progress
                │              ▼
                │            accepted
                │                   ▼
                └────────────── completed
```

**状态定义与 ownership 归属**：

| 状态 | assignee | 语义 |
|------|----------|------|
| `created` | principal | 已建未指派 |
| `assigned` | agent | 已委派未开始 |
| `in_progress` | agent | 执行中 |
| `blocked` | principal | checkpoint 待人决策 |
| `review_ready` | principal | 已交付待 review |
| `under_review` | principal | review 中 |
| `accepted` | principal | 验收通过 |
| `completed` | principal | 终态 |

**合法性转移**（未列出者 **MUST NOT** 发生）：

| from | to | 触发操作 |
|------|----|---------| 
| created | assigned | task.assign |
| assigned | in_progress | agent 开始执行 |
| in_progress | blocked | checkpoint.raise |
| blocked | in_progress | checkpoint.resolve (approve/provide) |
| blocked | completed | checkpoint.resolve (reject) |
| in_progress | review_ready | artifact.commit |
| review_ready | under_review | review.submit |
| under_review | in_progress | review (changes_requested) |
| under_review | accepted | review (approved) |
| under_review | rejected | review (rejected) |
| accepted | completed | 自动 |
| created/assigned/in_progress/blocked | completed | task.cancel |

### 3.4 Checkpoint

```yaml
Checkpoint:
  id: ckpt_
  task_id: task_               # REQUIRED
  kind: CheckpointKind         # REQUIRED
  prompt: string               # REQUIRED, 给人的说明
  options: [CheckpointOption]  # kind=choice 时 REQUIRED
  context: [Evidence]          # OPTIONAL, 决策证据
  state: "pending" | "resolved" | "expired"
  raised_at: timestamp
  expires_at: timestamp | null
  resolution: CheckpointResolution | null

CheckpointKind: "approval" | "choice" | "input" | "escalation"

CheckpointOption:
  id: string
  label: string
  risk: "low" | "medium" | "high"

CheckpointResolution:
  by: user_                    # MUST 是人
  action: "approve" | "reject" | "choose" | "provide" | "reassign"
  choice: string               # action=choose 时 REQUIRED
  input: string                # action=provide 时 REQUIRED
  reassign_to: agent_          # action=reassign 时 REQUIRED
  comment: string              # OPTIONAL
  at: timestamp
```

**一致性约束**：
- 一个 Checkpoint 同时只能有一个处于 `pending`（每 Task）**SHOULD**——并发 checkpoint 为开放议题（§7.4）。
- `expires_at` 到达时，实现 **MAY** 自动转 `expired`，并 **MUST** 产生 audit event。默认动作未定（§7.2）。
- `resolution.by` **MUST** 是 principal 或被授权的 reviewer。

### 3.5 Ownership

```yaml
Ownership:
  task_id: task_
  principal: user_             # MUST 是人，永不变
  assignee: user_ | agent_     # 当前执行者
  delegable: boolean           # assignee 是否可向下委派
  chain: [OwnershipTransfer]   # append-only 转移历史

OwnershipTransfer:
  from: user_ | agent_
  to: user_ | agent_
  at: timestamp
  via: "assign" | "checkpoint" | "approve" | "reject" | "handoff"
```

**一致性约束**：
- 每次 assignee 变更 **MUST** append 到 `chain`。
- 每条 transfer.via **MUST** 对应一个合法的协议事件。
- `delegable=false` 的 agent **MUST NOT** 调用 `ownership.delegate`。

### 3.6 Review

```yaml
Review:
  id: rev_
  task_id: task_
  artifact_id: art_            # REQUIRED
  reviewer: user_              # MUST 是人
  verdict: ReviewVerdict       # REQUIRED
  comments: [ReviewComment]    # RECOMMENDED
  requested_changes: [string]  # verdict=changes_requested 时 REQUIRED
  at: timestamp                # 提交后不可变

ReviewVerdict: "approved" | "changes_requested" | "rejected"

ReviewComment:
  anchor: string               # "line:42" / "file:auth.ts" / 实现定义
  severity: "blocker" | "major" | "minor" | "nit"
  body: string
```

**一致性约束**：
- Review 提交后 **MUST NOT** 修改；要改意见就追加新 Review。
- 多人 review 语义未定（§7.5）；本版本假设单 reviewer。

### 3.7 Artifact

```yaml
Artifact:
  id: art_
  type: string                 # "code_patch" | "document" | "report" | ... 实现扩展
  provenance: ArtifactProvenance
  version: string              # REQUIRED, 如 "v3"
  parent_version: string | null  # 版本链
  payload: ArtifactPayload
  references: [ArtifactRef]    # 被哪些 Task 消费

ArtifactProvenance:
  produced_by: task_
  produced_at: timestamp

ArtifactPayload:
  kind: "diff" | "blob" | "ref" | "inline"
  uri: string                  # 内容寻址
  checksum: string             # REQUIRED, sha256:
  size: integer

ArtifactRef:
  task_id: task_
  as: "input" | "output"
```

**一致性约束**：
- Artifact 创建后 **MUST** 不可变。要改就 commit 新 version，`parent_version` 指向旧版。
- `(id, version)` 二元组 **MUST** 全局唯一，引用 Artifact **MUST** 锁定此二元组。
- `checksum` **MUST** 验证 payload 完整性。

### 3.8 Ledger

```yaml
Ledger:
  id: led_
  scope: string                # "project:<name>" | "team:<name>" | "org:<name>"

LedgerEntry:
  key: string                  # 命名空间化的 key, 如 "deploy.key_path"
  value: any                   # JSON-serializable
  written_at: timestamp
  by: task_                    # 写入者 Task
```

**一致性约束**：
- Ledger **MUST** append-only，条目 **MUST NEVER** 删除。
- 同 key 多次写遵循 last-write-wins（§7.4），每次写 **MUST** 产生 audit event。
- 协议只定义 KV 语义；存储后端（KV / 文档 / 向量）由实现选择。

**命名说明**：刻意不用 "Memory"。Ledger 表达"组织级持久、可审计、累积的状态账本"，区别于 agent 对话记忆 / RAG 向量库（那是 loop0/loop1 的关切）。

### 3.9 Audit

```yaml
AuditEvent:
  id: aud_
  seq: integer                 # REQUIRED, scope 内单调递增
  at: timestamp
  actor: user_ | agent_
  action: string               # "<object>.<verb>", 见 §5.2
  subject: { kind, id }        # 操作目标
  task_id: task_ | null        # 始终关联聚合根
  before: object | null
  after: object | null
```

**一致性约束**：
- 每次协议操作（Task 状态转移、Checkpoint 变更、Ownership 转移、Artifact commit、Ledger write、Review submit）**MUST** 产生一条 AuditEvent。
- AuditEvent **MUST NEVER** 删除或修改。
- `seq` **MUST** 在其 scope（project/org）内单调递增，支持全局有序回放。

---

## 4. 协议操作（Operations）

### 4.1 操作总表

所有操作命名 `<object>.<verb>`。实现 **MUST** 支持全部 21 个。

| 对象 | 操作 | 调用方 | 语义 |
|------|------|--------|------|
| **Task** | `task.create` | principal | 创建 Task（state=created） |
| | `task.assign` | principal | 委派给 agent（→assigned，ownership 转移） |
| | `task.cancel` | principal | 中止（→completed） |
| | `task.get` | any | 查询单个 |
| | `task.list` | any | 列表查询 |
| **Checkpoint** | `checkpoint.raise` | agent | 声明决策点（Task→blocked） |
| | `checkpoint.resolve` | 人 | 回应（→resolved，Task 复活） |
| | `checkpoint.expire` | system | 超时失效 |
| **Ownership** | `ownership.transfer` | system | 内部转移 assignee |
| | `ownership.delegate` | agent | 向下委派（需 delegable） |
| **Review** | `review.submit` | reviewer | 提交（含 verdict） |
| | `review.comment` | reviewer | 追加批注 |
| **Artifact** | `artifact.commit` | agent | 产出/版本递进 |
| | `artifact.get` | any | 按 id+version 取 |
| | `artifact.reference` | Task | 引用为输入 |
| **Ledger** | `ledger.read` | any | 读 key |
| | `ledger.write` | task | 写 key（触发 audit） |
| | `ledger.history` | any | 回溯 key 变更 |
| **Audit** | `audit.query` | any | 按 task/actor/action 查 |
| | `audit.replay` | any | 回放 Task 完整历史 |

### 4.2 操作 → audit action 映射

每个操作 **MUST** 产生对应 audit action：

| 操作 | audit action |
|------|--------------|
| task.create | `task.created` |
| task.assign | `task.assigned` |
| task.cancel | `task.cancelled` |
| checkpoint.raise | `task.checkpoint.raised` |
| checkpoint.resolve | `task.checkpoint.resolved` |
| checkpoint.expire | `task.checkpoint.expired` |
| ownership.transfer | `ownership.transferred` |
| ownership.delegate | `ownership.delegated` |
| review.submit | `review.submitted` |
| artifact.commit | `artifact.committed` |
| ledger.write | `ledger.written` |

### 4.3 操作前置条件（Preconditions）

实现 **MUST** 校验以下前置条件，违反时返回 `PRECONDITION_FAILED`（§6.1）：

| 操作 | 前置条件 |
|------|---------|
| `task.assign` | Task.state == created |
| `task.cancel` | Task.state ∈ {created, assigned, in_progress, blocked} |
| `checkpoint.raise` | Task.state == in_progress |
| `checkpoint.resolve` | 存在 pending Checkpoint 且调用方为授权人 |
| `ownership.delegate` | ownership.delegable == true |
| `artifact.commit` | Task.state ∈ {in_progress, under_review-changes} |
| `review.submit` | Task.state ∈ {review_ready, under_review} |

---

## 5. 集成契约（Integration Contracts）

HLP 是本项目定义的核心协议。它向下接入既有 agent runtime 和 capability ecosystem 时，**MUST** 通过以下契约对象通信，**MUST NOT** 直接读写下层内部状态。

### 5.1 HLP → L1 agent route

| HLP 事件 | L1 adapter 动作 | 契约 |
|----------|---------|------|
| `task.assign` | `delegate` | TaskID **MUST** 贯穿到 agent run 作为 correlation id |
| `checkpoint.raise` | `block` | 对应 agent run **MUST** 进入 blocked 状态 |
| `checkpoint.resolve` | `resume` | 对应 agent run **MUST** 恢复执行 |
| `ownership.delegate` | `delegate`（子 agent） | 同 task.assign，但 parent 可追 |

参考实现的公开边界命名为 `AgentAdapter`。HLP 不定义新的 L1 agent-to-agent 协议，也不暴露历史 AAP 兼容别名。

### 5.2 HLP → Channel（→ loop1）

HLP 只产出事件，不负责送达。以下事件 **MAY** 被转译为 channel 通知：

| HLP 事件 | 典型 channel 表现 |
|----------|------------------|
| `checkpoint.raise` | 推送一条审批卡片到 IM |
| `artifact.commit + task→review_ready` | 推送 review 邀请 |
| `task.completed` | 推送完成通知 |

具体 UI/通知实现不属于 HLP 规范范围。

### 5.3 CapabilityRef（跨 HLP / agent route / capability route）

HLP 引用能力时 **MUST** 只用 `(capability_id, version)`，**MUST NOT** 感知底层 transport（MCP stdio/SSE、Agent Skills runtime、local function name 等）。

```yaml
CapabilityRef:
  capability_id: string        # 如 "cap:code-review"
  version: string              # 如 "v2"
```

---

## 6. 错误处理

### 6.1 错误码

| 码 | HTTP 类比 | 语义 |
|----|----------|------|
| `INVALID_SPEC` | 400 | Task spec 不合法 |
| `PRECONDITION_FAILED` | 412 | 操作前置条件不满足（如状态机非法转移） |
| `UNAUTHORIZED` | 401 | 调用方无权执行此操作 |
| `NOT_FOUND` | 404 | 对象不存在 |
| `CONFLICT` | 409 | 并发冲突（如同 key 并发写） |
| `IMMUTABLE_VIOLATION` | 409 | 试图修改不可变对象（spec/artifact/ledger/review/audit） |
| `DEADLINE_EXCEEDED` | 408 | Task 超时 |
| `CHECKPOINT_EXPIRED` | 410 | 操作已过期的 checkpoint |

### 6.2 一致性要求

- 实现记录 audit event 与业务操作 **SHOULD** 是原子的（audit 失败则业务回滚）。
- 实现对 Task 状态转移 **MUST** 是原子的（状态、ownership、audit 三者一致）。
- 当协议操作依赖外部 agent runtime adapter 时，adapter 调用失败 **MUST NOT** 让 HLP 状态、ownership、checkpoint、audit 或 run binding 进入成功状态。生产实现 **SHOULD** 使用事务 outbox 与幂等 key；嵌入式实现 **MAY** 先调用 adapter，成功后再提交本地状态。
- SDK/read API **SHOULD** 返回 read snapshot，避免调用方绕过状态机和 audit 直接修改内部 aggregate。

---

## 7. 开放议题（Open Issues）

以下未在本版本定论，标 `§7.x` 供后续收敛。实现 **MAY** 自行选择策略，**SHOULD** 在文档中声明。

### 7.1 Transport 绑定
HLP 只定义语义。HTTP/gRPC/WebSocket mapping 留给实现，待参考实现后收敛。

### 7.2 Checkpoint 超时默认动作
超时后是 auto-reject / auto-escalate / 纯挂起，未定。本版本建议纯挂起 + 可配置。

### 7.3 Ownership 多级委派深度
agent 能否把 Task 再委派给子 agent（链式）？本版本允许，靠 `delegable` 逐级可关。

### 7.4 Ledger 并发写
两个 Task 同时写同 key：本版本 last-write-wins + audit 记冲突，不保证强一致。

### 7.5 多人 Review
一个 Artifact 多人 review 时的 verdict 合成规则未定。本版本假设单 reviewer。

### 7.6 跨 project Artifact 引用
是否允许、如何授权未定。本版本要求显式跨域授权但未规定机制。

### 7.7 版本兼容
HLP v1 的 Task 能否被 v2 的 agent 执行？语义版本 + 向后兼容的具体规则待演进验证。

---

## 8. 一致性级别（Conformance）

一个实现声称"符合 HLP 0.1.0-draft"，**MUST**：

1. 支持全部 7 个一等对象
2. 实现全部 21 个操作
3. 遵守 §3.3 Task 状态机的合法转移
4. 遵守 §2.3 不可变性约束
5. 为每次协议操作产生符合 §4.2 的 audit event
6. 通过 §4.3 全部前置条件校验
7. 通过 §5 集成契约（若接入既有 agent runtime 或 capability ecosystem）

实现 **MAY**：
- 选择任意 transport（§7.1）
- 自定义 Task `type` 和 Artifact `type` 扩展
- 自行决定开放议题（§7）的策略

---

## 附录 A：完整协作流时序（参考）

以 "Review PR #1234" 场景验证协议完整性：

```text
人 Alice                     HLP 协议层                  agent Devin
  │── task.create ──────────▶│ (→created, audit)
  │── task.assign ──────────▶│ (→assigned, ownership alice→devin, L1 delegate)
  │                          │◀── (agent 执行)
  │                          │◀── checkpoint.raise ────│ (→blocked)
  │◀── checkpoint 通知 ──────│  (经 channel)
  │── checkpoint.resolve ───▶│ (choose opt_b → in_progress, L1 resume)
  │                          │◀── (继续执行)
  │                          │◀── artifact.commit ─────│ (v1, →review_ready)
  │◀── review 邀请 ──────────│
  │── review.submit ────────▶│ (changes_requested → in_progress, L1 resume)
  │                          │◀── (返工)
  │                          │◀── artifact.commit ─────│ (v2, →review_ready)
  │── review.submit ────────▶│ (approved → accepted → completed)
  │                          │── ledger.write ────────▶ (记录"PR#1234 已通过")
  │                          │── audit: 全程已记录
```

验证：21 操作足以表达完整闭环；ownership 流转 4 次全部入 audit；HLP→L1 adapter 衔接点干净。

## 附录 B：变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.1.0-draft | 2026-06-19 | 首个 draft，提炼自设计稿 `docs/plans/2026-06-19-loops-protocol-stack.md` |
