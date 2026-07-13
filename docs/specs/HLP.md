# HLP — Human Loop Protocol

| | |
|---|---|
| **规范版本** | 0.2.0-draft（核心）+ **0.3.0-draft**（附录 C / HLP-realtime，可选 profile） |
| **状态** | Draft — 0.2.0 核心语义已由参考实现和离线 conformance suite 覆盖；0.3 realtime 为附录草案 + reference helpers |
| **定位** | HLP-first：本项目核心协议和 SDK，下层通过既有 agent harness / capability 生态接入 |
| **层级** | 人机责任闭环层 |
| **设计稿** | [`docs/plans/2026-06-19-loops-protocol-stack.md`](../plans/2026-06-19-loops-protocol-stack.md) |

---

## 1. 摘要

HLP（Human Loop Protocol，人机责任闭环协议）定义**人**与**自主 agent
harness** 如何围绕一个有边界的工作单元（**Task**）进行委派、把关、交付与
治理。它是本项目的核心协议和 SDK 边界，填补了 MCP / Agent Skills
（agent↔工具）和 A2A / ACP / AGNTCY（agent↔agent）未覆盖的维度：
**agent 与其负责人之间的责任闭环语义**。

HLP 是 transport-agnostic、harness-agnostic 的语义规范。本规范定义
"协议说什么"，不规定"用什么线缆说"，也不规定 agent harness 如何执行。

### 1.1 规范性用语

本规范使用 [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) 关键字：**MUST**、**MUST NOT**、**SHOULD**、**SHOULD NOT**、**MAY**。大写形式表示规范性约束。

### 1.2 适用范围

HLP 管辖：人↔agent harness 围绕 Task 的协作（委派、审批、交付、评审、
状态沉淀、审计）。

HLP **不**管辖：
- agent harness 内部如何执行（实现自由）
- agent ↔ agent 委派（由既有 L1 agent 协议或 runtime 定义）
- agent ↔ 工具调用（由既有 L0 capability 协议或 runtime 定义）
- UI 渲染与通知送达（HLP 产出事件和 human inbox，channel 由 host 实现）
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

下列结构是 Task 的**值对象**（非一等对象），承载连续控制语义：

| 值对象 | 宿主 | 作用 |
|------|------|------|
| `SteeringAmendment` | `Task.steering_log` | append-only 方向修正，不改 `spec` |
| `PermissionGrant` | `Task.spec.constraints.grants` | append-only 预授权能力边界 |
| `ProposedAction` | `Checkpoint.proposed_actions` | 批量审批中单条提议动作 |

### 2.3 不可变性与前进性（Immutability & Forward-Only）

HLP 是**只前进协议**（forward-only protocol）：

- Task 的 `spec` 创建后 **MUST NOT** 修改。要改变方向 **MUST** 用 `task.amend`
  向 `steering_log` 追加 amendment（不改 `spec`）；需要彻底重启时才
  `task.cancel` + 新建。
- `steering_log` **MUST** append-only，amendment **MUST NEVER** 删除或修改。
- `PermissionGrant` **MUST** append-only；撤销靠追加 active matching
  `decision="deny"` 条目，授权判断中 deny 优先于 allow。
- Artifact 创建后 **MUST NOT** 修改。要改就 commit 新版本。
- Ledger 条目 **MUST NOT** 删除。纠错靠追加新条目。
- Review 提交后 **MUST NOT** 修改。要改意见就追加新 Review。
- Audit 事件 **MUST NEVER** 删除或修改。

此约束保证整个协议**可重放、可审计**。连续控制（打断、转向、预授权、接管）通过
append-only 结构纳入，不弱化前进性。

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
  revision: integer            # REQUIRED, per-task CAS token, 初始 0
  deadline: timestamp | null   # OPTIONAL
  checkpoints: [ckpt_]         # 挂载的 Checkpoint ID
  artifacts: [art_]            # 产出的 Artifact ID
  steering_log: [SteeringAmendment]  # append-only 方向修正，不改 spec
  audit_trail: aud_            # 指向 audit 聚合根

TaskSpec:
  goal: string                 # REQUIRED, 自然语言目标
  acceptance_criteria: [string]  # RECOMMENDED
  inputs: [InputRef]           # OPTIONAL
  constraints: Constraints     # OPTIONAL

SteeringAmendment:
  text: string                 # REQUIRED, 自然语言方向修正
  intent: "redirect" | "clarify" | "constrain" | "abort_hint"
  by: user_                    # MUST 是人 (principal 或授权者)
  at: timestamp

InputRef:
  kind: "artifact" | "resource"
  id: string                   # kind=artifact 时为 art_
  version: string              # kind=artifact 时 REQUIRED
  uri: string                  # kind=resource 时 REQUIRED

Constraints:
  max_duration: duration       # OPTIONAL
  external_refs: [ExternalRef] # OPTIONAL, opaque evidence refs
  autonomy: AutonomyTier       # OPTIONAL, 自主权档位，默认 autonomous
  grants: [PermissionGrant]    # OPTIONAL, append-only 预授权能力边界

AutonomyTier: "autonomous" | "plan_then_implement" | "confirm_each_action" | "read_only"

PermissionGrant:
  scope: string                # REQUIRED, 能力范围, 如 "bash:*" / "fs:/repo:write" / "tool:mcp:github" / "net:*"
  decision: "allow" | "deny"
  until: "session" | "task" | timestamp  # 生效区间
  granted_by: user_
  granted_at: timestamp

Permission scope grammar:
  scope: "*" | namespace ":" target ["*"]
  namespace: [a-z][a-z0-9_-]*
  target: non-empty string without whitespace

`scope` 保存前 **MUST** trim/normalize。`*` 只能作为全局 scope 或后缀通配符；
`fs:/repo:*` 这类后缀通配 **MAY** 匹配 `fs:/repo/file.py`。授权判断时，过期
grant **MUST** 被忽略；active matching deny **MUST** 优先于 active matching allow；
没有 active allow 时视为未预授权。

ExternalRef:
  kind: string                 # 如 "capability", "dataset", "policy"
  namespace: string            # 如 "mcp", "skill", "host"
  id: string                   # 外部系统内稳定 ID
  version: string | null       # OPTIONAL
  label: string | null         # OPTIONAL, 给人看的名称
```

**一致性约束**：
- `spec` 在 `task.create` 后 **MUST NOT** 变更。方向修正 **MUST** 走 `task.amend`
  追加到 `steering_log`，**MUST NOT** 改写 `spec.goal`。
- `steering_log` **MUST** append-only；`task.amend` 可在 `in_progress`/`blocked`
  状态下调用，**MUST NOT** 在终态调用。
- `autonomy` 设定基线自主权档位；`grants` 在基线上细化（allow-always / deny）。
  同 scope 生效决策取 last-write-wins。harness **MUST** 在执行 proposed action 前
  检查 `grants`：被 allow 覆盖的动作 **MAY** 跳过 checkpoint，被 deny 覆盖的
  **MUST NOT** 执行。
- `external_refs` **MAY** 记录人类决策和审计需要的外部证据引用；HLP **MUST NOT**
  解析、鉴权或调用这些外部系统。
- `ownership.principal` **MUST** 在创建时设定，且 **MUST NEVER** 变更。
- `state` 转移 **MUST** 遵守 §4.1 状态机。

### 3.3 TaskState 状态机

```text
                    ┌──────────────────────────────────────┐
                    │                                      ▼
  created ──▶ assigned ──▶ in_progress ──┐         blocked
                │              │ │       │              │
                │              │ │       └──────────────┘
                │              │ │             resolve
                │              │ │ task.interrupt (人发起)
                │              │ └──────────────▶│
                │              ▼                 │
                │         review_ready ──▶ under_review ──┐
                │              │                    │      │ changes_requested
                │              │                    │      │ / plan approved
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
| `in_progress` | agent（take-over 期间 MAY 是 human） | 执行中 |
| `blocked` | principal | checkpoint 待人决策（含人发起的 interrupt） |
| `review_ready` | principal | 已交付待 review |
| `under_review` | principal | review 中 |
| `accepted` | principal | 验收通过 |
| `completed` | principal | 终态 |

**合法性转移**（未列出者 **MUST NOT** 发生）：

| from | to | 触发操作 |
|------|----|---------| 
| created | assigned | task.assign |
| assigned | in_progress | agent 开始执行 |
| in_progress | blocked | checkpoint.raise（agent 发起）\| task.interrupt（人发起，系统 raise `kind=interrupt` checkpoint） |
| blocked | in_progress | checkpoint.resolve (approve/provide/amend) |
| blocked | completed | checkpoint.resolve (reject) |
| in_progress | review_ready | artifact.commit |
| review_ready | under_review | review.submit |
| under_review | in_progress | review (changes_requested) \| review (kind=plan, approved) |
| under_review | accepted | review (kind=deliverable, approved) |
| under_review | rejected | review (kind=deliverable, rejected) |
| accepted | completed | 自动 |
| created/assigned/in_progress/blocked | completed | task.cancel |

**非状态变更操作**（不转移 state，但 **MUST** 产生 audit event）：

| 操作 | 前置状态 | 语义 |
|------|---------|------|
| `task.amend` | in_progress \| blocked | 向 `steering_log` 追加 amendment，不改 state |
| `ownership.transfer` | 非终态 | take-over：assignee 可临时转给 human，再转回 agent |

### 3.4 Checkpoint

```yaml
Checkpoint:
  id: ckpt_
  task_id: task_               # REQUIRED
  kind: CheckpointKind         # REQUIRED
  prompt: string               # REQUIRED, 给人的说明
  options: [CheckpointOption]  # kind=choice 时 REQUIRED
  proposed_actions: [ProposedAction]  # OPTIONAL, 批量审批提议动作
  context: [Evidence]          # OPTIONAL, 决策证据
  state: "pending" | "resolved" | "expired"
  raised_at: timestamp
  raised_by: "agent" | "human" | "system"  # human = 人发起的 task.interrupt
  expires_at: timestamp | null
  resolution: CheckpointResolution | null

CheckpointKind: "approval" | "choice" | "input" | "escalation" | "interrupt"

CheckpointOption:
  id: string
  label: string
  risk: "low" | "medium" | "high"

ProposedAction:
  id: string                   # REQUIRED
  kind: string                 # "shell" | "file_write" | "tool_call" | "plan_step" | ...
  summary: string              # REQUIRED, 给人看的一句话
  permission_scope: string | null  # 用于和 PermissionGrant 确定性匹配
  detail: object | null        # 实现定义详情 (命令、diff 预览等)
  risk: "low" | "medium" | "high"

CheckpointResolution:
  by: user_                    # MUST 是人
  action: "approve" | "reject" | "choose" | "provide" | "reassign"
  choice: string               # action=choose 时 REQUIRED
  input: string                # action=provide 时 REQUIRED
  reassign_to: agent_          # action=reassign 时 REQUIRED
  approved_actions: [string]   # 对 proposed_actions 的部分批准 (id 子集)
  denied_actions: [string]     # 对 proposed_actions 的部分拒绝 (id 子集)
  state_patch: object | null   # 人注入/修改的中间状态 (take-over / mid-edit resume)
  edited_artifact_ref: { id: art_, version: string } | null  # 人编辑过的 artifact 版本
  comment: string              # OPTIONAL
  at: timestamp
```

**一致性约束**：
- 一个 Checkpoint 同时只能有一个处于 `pending`（每 Task）**SHOULD**——并发 checkpoint 为开放议题（§7.4）。
  需要一次问多件事时，**SHOULD** 用单个 Checkpoint 的 `proposed_actions` 批量提议，
  而非 raise 多个并发 checkpoint。
- `kind=interrupt` 的 checkpoint **MUST** 由 `task.interrupt` 触发（`raised_by="human"`），
  不得由 agent 直接 raise。
- `expires_at` 到达时，实现 **MAY** 自动转 `expired`，并 **MUST** 产生 audit event。
  `kind=interrupt` 的默认动作为纯挂起（§7.2）。
- `resolution.by` **MUST** 是 principal 或被授权的 reviewer。
- `approved_actions` / `denied_actions` **MUST** 引用本 Checkpoint 的 `proposed_actions`
  id；未列出的动作由实现定义默认（**SHOULD** 视为 denied）。
- `state_patch` / `edited_artifact_ref` 携带人修改的中间态；harness **MUST** 在 resume
  时以该状态为起点继续，而非从原中断点原样恢复。

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
  kind: ReviewKind             # "plan" | "deliverable"，默认 deliverable
  verdict: ReviewVerdict       # REQUIRED
  comments: [ReviewComment]    # RECOMMENDED
  requested_changes: [string]  # verdict=changes_requested 时 REQUIRED
  at: timestamp                # 提交后不可变

ReviewKind: "plan" | "deliverable"
ReviewVerdict: "approved" | "changes_requested" | "rejected"

ReviewComment:
  anchor: string               # "line:42" / "file:auth.ts" / 实现定义
  severity: "blocker" | "major" | "minor" | "nit"
  body: string
```

**一致性约束**：
- Review 提交后 **MUST NOT** 修改；要改意见就追加新 Review。
- `kind="plan"` 的 Review 针对中间产物（如 plan artifact）：`approved` 使 Task 回到
  `in_progress` 继续；`changes_requested` 同样回 `in_progress` 等待返工。
- `kind="deliverable"` 的 Review 针对终态交付物：`approved` 推向 `accepted`；
  `rejected` 推向 `rejected` 终态。
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

**命名说明**：刻意不用 "Memory"。Ledger 表达"组织级持久、可审计、累积的状态账本"，区别于 agent 对话记忆 / RAG 向量库（那是外部 harness 或 host 的关切）。

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
  reducer: object | null       # canonical subject/task/change payload
  schema_version: string
  profile: string
  prev_hash: string            # 空字符串表示链首
  hash: string                 # sha256:<canonical event hash>
```

**一致性约束**：
- 每次协议操作（Task 状态转移、Checkpoint 变更、Ownership 转移、Artifact commit、Ledger write、Review submit）**MUST** 产生一条 AuditEvent。
- AuditEvent **MUST NEVER** 删除或修改。
- `seq` **MUST** 在其 scope（project/org）内单调递增，支持全局有序回放。
- `HLP-industrial` 实现 **SHOULD** 提供 reducer-ready payload，至少包含
  canonical `subject`、当前 Task reducer snapshot（state / ownership / revision /
  checkpoint/artifact ids / steering count）和本事件 `change`。
- `HLP-industrial` 实现 **SHOULD** 让 AuditEvent 形成 tamper-evident hash
  chain：`prev_hash` 指向上一事件 hash，`hash` 基于不含 `hash` 字段的 canonical
  JSON 事件计算。

---

## 4. 协议操作（Operations）

### 4.1 操作总表

所有操作命名 `<object>.<verb>`。实现 **MUST** 支持全部 23 个。

| 对象 | 操作 | 调用方 | 语义 |
|------|------|--------|------|
| **Task** | `task.create` | principal | 创建 Task（state=created） |
| | `task.assign` | principal | 委派给 agent（→assigned，ownership 转移） |
| | `task.start` | agent / adapter | 记录关联 harness run 已开始（→in_progress） |
| | `task.cancel` | principal | 中止（→completed） |
| | `task.interrupt` | principal | 人发起暂停（→blocked，系统 raise kind=interrupt checkpoint） |
| | `task.amend` | principal | 向 steering_log 追加方向修正（不改 state/spec） |
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

工业 profile 中，修改 Task aggregate 的操作 **SHOULD** 接受：

```yaml
expected_task_revision: integer | null  # 可选 CAS token
idempotency_key: string | null          # 可选，task-scoped
```

若提供 `expected_task_revision`，实现 **MUST** 在调用外部 adapter 或写入状态前比较
当前 `Task.revision`；不一致时 **MUST** 返回 `CONFLICT`。成功的 Task aggregate
修改 **MUST** 让 `revision` 只前进一次。

若提供 `idempotency_key`，同一 task 内同一 key + 同一 canonical request
fingerprint **MUST** 返回首次操作结果，且 **MUST NOT** 再次执行前置条件、adapter
调用、audit append 或 SDK event publish。同一 key + 不同 fingerprint **MUST**
返回 `CONFLICT`。参考实现当前覆盖所有会推进现有 `Task.revision` 的 Task
aggregate mutation：`task.assign`、`task.start`、`task.cancel`、`task.amend`、
`task.interrupt`、`checkpoint.raise`、`checkpoint.resolve`、
`checkpoint.expire`、`ownership.transfer`、`ownership.delegate`、
`artifact.commit` 与 `review.submit`。`task.create` 创建新 aggregate；`ledger.write`、
`review.comment` 与 `artifact.reference` 不推进 Task aggregate revision。adapter outbox
context 覆盖 `task.assign`、`task.cancel`、`task.amend`、`task.interrupt`、
`checkpoint.raise`、`checkpoint.resolve`、`ownership.transfer` handoff 与
`ownership.delegate` 的外部 side effect 边界。

### 4.2 操作 → audit action 映射

每个操作 **MUST** 产生对应 audit action：

| 操作 | audit action |
|------|--------------|
| task.create | `task.created` |
| task.assign | `task.assigned` |
| task.start | `task.started` |
| task.cancel | `task.cancelled` |
| task.interrupt | `task.interrupted` + `task.checkpoint.raised`（系统代 raise） |
| task.amend | `task.amended` |
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
| `task.start` | Task.state == assigned |
| `task.cancel` | Task.state ∈ {created, assigned, in_progress, blocked} |
| `task.interrupt` | Task.state == in_progress；调用方为 principal |
| `task.amend` | Task.state ∈ {in_progress, blocked}；调用方为 principal |
| `checkpoint.raise` | Task.state == in_progress |
| `checkpoint.resolve` | 存在 pending Checkpoint 且调用方为授权人 |
| `ownership.delegate` | ownership.delegable == true |
| `artifact.commit` | Task.state ∈ {in_progress, under_review-changes} |
| `review.submit` | Task.state ∈ {review_ready, under_review}；`kind=deliverable` 的 approved 仅当 Task.state == under_review 时推向 accepted |

---

## 5. 集成契约（Integration Contracts）

HLP 是本项目定义的核心协议。它向下接入既有 agent harness 和 capability
ecosystem 时，**MUST** 通过以下契约对象通信，**MUST NOT** 直接读写下层内部状态。

### 5.1 HLP → agent harness

| HLP 事件 | Adapter 动作 | 契约 |
|----------|---------|------|
| `task.assign` | `delegate` | TaskID **MUST** 贯穿到 agent run 作为 correlation id |
| `checkpoint.raise` | `block` | 对应 agent run **MUST** 进入 blocked 状态 |
| `checkpoint.resolve` | `resume` | 对应 agent run **MUST** 恢复执行；若 resolution 携带 `state_patch`/`edited_artifact_ref`，harness **MUST** 以该状态为起点恢复 |
| `task.interrupt` | `block` | 人发起的中断；harness **MUST** 停止当前 turn 并进入 blocked 状态 |
| `task.amend` | `steer` | 方向修正 **MUST** 注入到正在运行的 agent run 上下文；**MUST NOT** 重启 run |
| `ownership.delegate` | `delegate`（子 agent） | 同 task.assign，但 parent 可追 |

参考实现的下行公开边界命名为 `AgentAdapter`。HLP 不定义新的 L1
agent-to-agent 协议，也不暴露历史 AAP 兼容别名。

### 5.2 agent harness → HLP

既有 harness 如果已经拥有自己的 run loop，只需要把 human-facing 事件投影给
HLP。参考实现的上行公开边界命名为 `HarnessAdapter`。

| Harness event | HLP 投影 | 契约 |
| --- | --- | --- |
| `needs_approval` | `Checkpoint(kind="approval")` | TaskID / RunID / AgentID **MUST** 保留 |
| `needs_choice` | `Checkpoint(kind="choice")` | options **MUST** 可被人理解和审计 |
| `needs_input` | `Checkpoint(kind="input")` | prompt/context **SHOULD** 足够人决策 |
| `artifact` | `Artifact` | artifact payload **MUST** 有稳定 uri/checksum |

HLP **MUST NOT** 要求 harness 暴露 prompt、memory、tool trace、planner state
等内部执行细节。HLP 只接收足以形成人类决策、验收和审计的语义事件。

#### 5.2.1 可靠事件投递

当 harness adapter 以事件流方式投影 human-facing 事件时，实现 **SHOULD** 支持
非破坏式读取和显式确认：

```yaml
HarnessEventDelivery:
  cursor: string              # run 内稳定、单调前进的确认游标
  event: HarnessEvent         # needs_approval / needs_choice / needs_input / artifact
```

可选可靠投递扩展：

| 方法 | 语义 |
| --- | --- |
| `peek_events(run_id, cursor?, limit?)` | 返回未确认的 `HarnessEventDelivery`，**MUST NOT** 消费事件 |
| `ack_events(run_id, through)` | 确认同一 run 内直到 `through` 的前缀事件 |

`HLP-integrated` 实现如果声明 event-streaming 能力，投影失败（correlation 冲突、
前置条件失败、adapter/block/commit 失败等）**MUST NOT** ack 对应事件。成功投影
后的事件 **SHOULD** 立即 ack；批量投影时 **MAY** ack 已成功的前缀，并保留失败事件
及其后续事件。旧的 `observe(run_id)` 仍可作为嵌入式或测试用破坏式读取接口，但
不能作为工业可靠投递的唯一证据。

### 5.3 HLP → Channel / UI

HLP 只产出事件，不负责送达。以下事件 **MAY** 被转译为 channel 通知：

| HLP 事件 | 典型 channel 表现 |
|----------|------------------|
| `checkpoint.raise` | 推送一条审批卡片到 IM |
| `artifact.commit + task→review_ready` | 推送 review 邀请 |
| `task.completed` | 推送完成通知 |

具体 UI/通知实现不属于 HLP 规范范围。

### 5.4 外部能力证据（跨 HLP / agent route / capability route）

HLP core 不定义 capability schema，也不要求 Task 必须携带能力约束。需要在人类
决策或审计中说明能力来源时，HLP **MAY** 保存 opaque `ExternalRef`。下层
capability ecosystem 可以把 `kind="capability"` 的 `ExternalRef` 解释为自己的
能力证据 profile，但解释、鉴权、schema 解析和调用都不属于 HLP。

```yaml
ExternalRef:
  kind: "capability"
  namespace: string            # 如 "mcp" / "skill" / "host"
  id: string                   # 如 "cap:code-review"
  version: string              # 如 "v2"
  label: string | null
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
| `VERSION_UNSUPPORTED` | 409 | spec/schema/profile 无共同支持版本 |

### 6.2 错误对象

实现通过 transport 暴露错误时 **MUST** 使用稳定错误对象。参考实现的
`ProtocolError.to_dict()` 使用该 wire shape：

```yaml
ProtocolError:
  code: ErrorCode
  message: string
  details: object
  retryable: boolean
  operation_id: string | null
  correlation_id: task_ | string | null
  spec_version: "0.2.0-draft"
  schema_version: "0.2"
  profile: "HLP-industrial"
```

`CONFLICT` / `DEADLINE_EXCEEDED` 默认 **MAY** retry；前置条件、权限、不可变性和
对象不存在错误默认不可 retry。实现 **MAY** 根据具体 transport 或 adapter failure
覆盖 `retryable`，但必须在错误对象中显式给出。

### 6.3 一致性要求

- 实现记录 audit event 与业务操作 **SHOULD** 是原子的（audit 失败则业务回滚）。
- 实现对 Task 状态转移 **MUST** 是原子的（状态、ownership、audit 三者一致）。
- 当协议操作依赖外部 agent harness adapter 时，adapter 调用失败 **MUST NOT** 让 HLP 状态、ownership、checkpoint、audit 或 run binding 进入成功状态。生产实现 **SHOULD** 在外部 side effect 前持久化 adapter outbox intent，并向 adapter 传入稳定 `operation_context` / `AdapterOperationContext`（`operation_id`、`correlation_id`、`idempotency_key`、request fingerprint、Task revision），使外部 harness 能够对 retry 去重；本地 HLP mutation 成功提交后 **SHOULD** 将 outbox record 标记为 `succeeded`。
- 当 harness event 通过可靠投递扩展投影到 HLP 时，实现 **MUST** 在投影成功后才
  ack；投影失败时事件 **MUST** 保留为未确认状态。
- SDK/read API **SHOULD** 返回 read snapshot，避免调用方绕过状态机和 audit 直接修改内部 aggregate。

### 6.4 JSON Schema 与版本协商

`HLP-industrial` 实现 **SHOULD** 暴露 object/wire JSON Schema registry。参考实现
提供 `HLP_JSON_SCHEMAS`、`schema_for(name)`、`to_wire(value)` 与
`validate_wire_object(name, value)`，当前覆盖：

- `Task`
- `Checkpoint`
- `Ownership`
- `Review`
- `Artifact`
- `Ledger`
- `ProtocolError`
- `AuditEvent`
- `HarnessEvent`
- `HarnessEventDelivery`
- `PermissionGrant`
- `ProposedAction`
- `AdapterOperationContext`
- `AdapterOutboxRecord`
- `VersionNegotiation`

`to_wire()` **MUST** 把 dataclass 转为 JSON-compatible object：时间戳使用 RFC3339
字符串，tuple 转 array，Python 内部字段别名如 `from_` / `as_` 转为 `from` / `as`，
并补齐 `schema_version` 与 `profile`。

每个 transport wire envelope **MUST** 携带：

```yaml
spec_version: "0.2.0-draft"
schema_version: "0.2"
profile: "HLP-industrial"
```

版本协商 **MUST** fail fast：双方没有共同 `spec_version`、`schema_version` 或
`profile` 时返回 `VERSION_UNSUPPORTED`，不能降级为语义不明的兼容行为。

---

## 7. 开放议题（Open Issues）

以下未在本版本定论，标 `§7.x` 供后续收敛。实现 **MAY** 自行选择策略，**SHOULD** 在文档中声明。

### 7.1 Transport 绑定
HLP 只定义语义。HTTP/gRPC/WebSocket mapping 留给实现，待参考实现后收敛。

### 7.2 Checkpoint 超时默认动作
超时后是 auto-reject / auto-escalate / 纯挂起，未定。本版本建议纯挂起 + 可配置。
`kind=interrupt`（人发起的中断）的 checkpoint 超时 **SHOULD** 保持纯挂起——因为人
发起的中断语义即「等人」，不存在自动 reject 的合理解。

### 7.3 Ownership 多级委派深度
agent 能否把 Task 再委派给子 agent（链式）？本版本允许，靠 `delegable` 逐级可关。

### 7.4 Ledger 并发写
两个 Task 同时写同 key：本版本 last-write-wins + audit 记冲突，不保证强一致。
Checkpoint 的并发 pending 仍 **SHOULD** 单一（§3.4）；一次需问多件事时用单个
Checkpoint 的 `proposed_actions` 批量提议。

### 7.5 多人 Review
一个 Artifact 多人 review 时的 verdict 合成规则未定。本版本假设单 reviewer。

### 7.6 跨 project Artifact 引用
是否允许、如何授权未定。本版本要求显式跨域授权但未规定机制。

### 7.7 版本兼容
HLP v1 的 Task 能否被 v2 的 agent 执行？语义版本 + 向后兼容的具体规则待演进验证。

### 7.8 Soft control 与准实时晋级
**已收敛**（2026-07-13）：见附录 C（0.3 规范草案）。要点：
Soft **MUST NOT** 进入 Task 状态机；channel 侧合并后 HLP **只收** steering/checkpoint
结果；BCI 等传感器 **MUST NOT** 单独关闭高风险 hard checkpoint（默认）。  
本 0.2.0-draft 正文仍 **不** 要求实现 `ControlSignal` 值对象；连续控制操作集以
§2.3 / §3.2 / §4 为准。声明 `HLP-realtime` 时 **MUST** 遵守附录 C。

### 7.9 并发 hard checkpoint
§3.4 仍 **SHOULD** 每 Task 单一 pending hard checkpoint。声明 `HLP-realtime` 时
**MUST** 在 Serialize / Scope-partition / Priority stack 中选择并文档化其一
（附录 C §C.5）。

---

## 8. 一致性级别（Conformance）

一个实现声称"符合 HLP 0.2.0-draft"，**MUST**：

1. 支持全部 7 个一等对象
2. 实现全部 23 个操作
3. 遵守 §3.3 Task 状态机的合法转移
4. 遵守 §2.3 不可变性约束（含 `steering_log` / `PermissionGrant` 的 append-only）
5. 为每次协议操作产生符合 §4.2 的 audit event
6. 通过 §4.3 全部前置条件校验
7. 通过 §5 集成契约（若接入既有 agent harness 或 capability ecosystem）
8. 支持 `task.interrupt`（人发起打断）与 `task.amend`（转向不重启）的完整语义，
   包括 `steer` adapter 动作与 `state_patch`/`edited_artifact_ref` resume 语义
9. 若声明 event-streaming integration，必须支持 §5.2.1 的非破坏式
   `HarnessEventDelivery` 投递与成功后 ack 语义

实现 **MAY**：
- 选择任意 transport（§7.1）
- 自定义 Task `type` 和 Artifact `type` 扩展
- 自行决定开放议题（§7）的策略
- 声明可选 profile：`HLP-industrial`（§6.4）、`HLP-realtime`（附录 C）

`HLP-compatible` / `HLP-integrated` 不等同于 `HLP-industrial`。工业级声明需要
额外证明 per-task CAS、idempotency key、durable outbox、reducer-ready audit
payload、permission scope grammar、object/wire JSON schema 与 version negotiation。

`HLP-realtime` 声明 **MUST** 满足附录 C 的 Soft/Hard、晋级、principal 绑定与
BCI/传感器限制；**不等于** 媒体实时 SLA，也 **不等于** `HLP-industrial`。

---

## 附录 A：完整协作流时序（参考）

以 "Review PR #1234" 场景验证协议完整性（含连续控制：打断与转向）：

```text
人 Alice                     HLP 协议层                  agent Devin
  │── task.create ──────────▶│ (→created, audit)
  │── task.assign ──────────▶│ (→assigned, ownership alice→devin, harness delegate)
  │                          │◀── (harness 执行)
  │── task.amend ───────────▶│ (steering_log += "focus on auth", harness steer, 不改 state)
  │                          │◀── (按修正方向继续)
  │── task.interrupt ────────▶│ (→blocked, 系统 raise kind=interrupt checkpoint, harness block)
  │── checkpoint.resolve ───▶│ (approve + state_patch → in_progress, harness resume from patch)
  │                          │◀── needs_approval ──────│ (投影为 checkpoint, →blocked)
  │◀── checkpoint 通知 ──────│  (经 host channel)
  │── checkpoint.resolve ───▶│ (choose opt_b → in_progress, harness resume)
  │                          │◀── (继续执行)
  │                          │◀── artifact(plan) event ──│ (投影为 artifact v1 plan, →review_ready)
  │── review.submit ────────▶│ (kind=plan, approved → in_progress, 继续实现)
  │                          │◀── (实现)
  │                          │◀── artifact event ──────│ (投影为 artifact v2 deliverable, →review_ready)
  │── review.submit ────────▶│ (kind=deliverable, changes_requested → in_progress)
  │                          │◀── (返工)
  │                          │◀── artifact.commit ─────│ (v3, →review_ready)
  │── review.submit ────────▶│ (kind=deliverable, approved → accepted → completed)
  │                          │── ledger.write ────────▶ (记录"PR#1234 已通过")
  │                          │── audit: 全程已记录（含 amend/interrupt）
```

验证：23 操作足以表达完整闭环，含人发起的连续控制（amend 转向、interrupt 打断、
state_patch resume）；ownership 流转全部入 audit；HLP→harness adapter 衔接点干净。

## 附录 B：变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.1.0-draft | 2026-06-19 | 首个 draft，提炼自设计稿 `docs/plans/2026-06-19-loops-protocol-stack.md` |
| 0.2.0-draft | 2026-07-02 | 连续控制扩展：加 `task.interrupt`/`task.amend` + `steering_log`；`PermissionGrant`/`autonomy` 预授权；`Checkpoint.proposed_actions` 批量审批 + 部分批准；`CheckpointResolution.state_patch`/`edited_artifact_ref` resume-with-state；`Review.kind` 区分 plan/deliverable 评审；状态机加 interrupt 边与 plan-approved 回 in_progress。详见 `docs/plans/2026-07-02-hlp-continuous-control-extension.md` |
| 0.2.0-draft | 2026-07-13 | 附录 C：Soft/Hard control、Channel→HLP 晋级（promotion）、InteractionRef、`HLP-realtime` profile 草案。**不** 新增一等对象或 media 绑定。设计全文见 `docs/plans/2026-07-13-hlp-realtime-control-plane.md` |
| 0.2.0-draft | 2026-07-13 | 附录 C **决策收敛**：Soft 不进状态机；合并在 host/profile、HLP 只收结果；BCI 默认不得单独 hard-resolve 高风险 checkpoint。作为 0.3 规范草案收口，仍不改 0.2.0 操作集。 |
| 0.3.0-draft | 2026-07-13 | **可选 profile 版本标签**（不替换 0.2.0 核心版本号）：`HLP_REALTIME_SPEC_VERSION` / 附录 C；reference：`ControlSignal`、`merge_soft_control_signals`、TUI `/promote`、`loops-hlp-realtime-demo`。Package 版本仍为 0.2.0。 |

## 附录 C：Soft / Hard Control 与准实时晋级（0.3 规范草案）

> **状态**：0.3 规范草案（已收敛决策）。  
> **对 0.2.0-draft**：不增加第 8 个一等对象，不增加第 24 个操作；未声明
> `HLP-realtime` 的实现 **不必** 实现本附录。  
> **设计**：[realtime control plane 计划](../plans/2026-07-13-hlp-realtime-control-plane.md)

### C.0 已收敛决策（2026-07-13）

| # | 决策 | 规范效力 |
|---|------|----------|
| D1 | Soft control **不** 进入 Task 状态机 | 声明 `HLP-realtime` 时 **MUST** |
| D2 | Soft 流合并在 **host / channel / realtime profile**；HLP 协议边界 **只收** 已合并的 `task.amend` / hard 事件 | **MUST** |
| D3 | BCI 等传感器意图 **默认不得** 单独 `checkpoint.resolve` 关闭**高风险** hard checkpoint | **MUST**（除非 profile 显式声明更严/更宽策略且仍 fail-closed） |
| D4 | 多 agent **不** 引入实时责任图；沿用单 Task 单 principal + 子 Task / ownership | **SHOULD**（0.3 默认） |

### C.1 问题边界

HLP **MUST** 继续只定义责任闭环语义，**MUST NOT** 拥有：

- 音频/视频编解码、Realtime 房间、SFU  
- Token/音频帧/脑电采样等媒体一等对象  
- 具体厂商 Realtime API 或 BCI 设备 schema  

准实时交互（语音双工、多模态、BCI）发生在 **channel / sensor plane**。HLP 通过
**晋级（promotion）** 接收已降采样的责任事件。

### C.2 三层时间尺度

```text
Channel / Sensor plane   高频、可丢、不可单独作法律责任依据
        │ promotion（降采样 / 合并 / 置信过滤）
        ▼
HLP responsibility plane 低频、append-only、可重放
        │ adapter
        ▼
Harness execution plane  模型 / 工具 / planning loop
```

### C.3 Soft control vs Hard control

| | Hard control | Soft control |
|---|--------------|--------------|
| 语义 | 责任未闭合则不得继续关键动作 | 方向/偏好信号，不阻塞 Task.state |
| Task.state | 通常进入 `blocked` | **MUST NOT** 仅因 soft 而改变 state（D1） |
| 0.2.0 映射 | `checkpoint.*` / `task.interrupt` | `task.amend` / `steering_log` |
| 例子 | 推生产、暴露密钥、资金操作 | “语气软一点”“再往左一点” |

实现 **MAY** 在 channel/host 内部使用值对象 `ControlSignal`（见计划文档）描述
意图来源、`confidence`、`source_kind`（`speech`/`text`/`ui`/`bci`/…）与
`principal_binding`。`ControlSignal` **不是** 一等对象；**MUST NOT** 替代
Task/Checkpoint；**MUST NOT** 作为未晋级的 wire 必选字段进入 0.2.0 core。

声明 `HLP-realtime` 的实现 **MUST**：

1. Soft **MUST NOT** 改变 `Task.state`（D1）。Soft **MUST NOT** 在 `confidence`
   低于该实现声明的阈值时单独触发 hard 效果。  
2. Soft 晋级到 HLP **MUST** 表现为已存在的责任操作（通常是一条
   `SteeringAmendment` / `task.amend`），**MUST NOT** 要求 HLP core 消费原始
   帧流或未合并的微信号（D2）。合并窗口、去抖、语义聚合 **MUST** 在 host 或
   realtime profile 文档中说明。  
3. Hard **MUST** 走 `checkpoint.raise` / `task.interrupt` 或对已 raise 的
   checkpoint 的人侧 resolve（`checkpoint.resolve`）。  
4. Soft 与 active `PermissionGrant` 冲突时 **deny 优先**。  
5. 每次成功晋级 **MUST** 在 audit 中可追溯（intent provenance：至少 principal、
   时间、晋级类型 soft→steering 或 hard→checkpoint/interrupt）。  
6. **Principal 永远是人**；BCI/语音等只是意图传感器。  
7. **高风险** hard checkpoint 的 resolve：**MUST NOT** 仅凭 BCI（或同等单通道
   生物信号）完成（D3）。实现 **MAY** 要求第二因子（显式 UI/口令/硬件键等）。
   Profile **MAY** 收紧（例如一切 hard 皆需双因子），**MUST NOT** 默认放宽到
   “BCI 单独关闭高风险动作”。  
8. 文本/按钮等显式 UI 在 principal 已认证时可视为 `confidence = 1.0` 的 hard/soft
   输入，仍遵守 grant 与状态机。

### C.4 晋级表示例

| Channel 现象 | 晋级到 HLP？ | 结果 |
|--------------|--------------|------|
| 填充词 / 含糊反馈 | 否 | host 可丢弃 |
| 明确“停止推送” | 是 | hard：interrupt 或 checkpoint |
| 短时连续微调指令 | **channel 合并后** 是 | **一条** `task.amend` |
| 低置信 BCI “同意” | 否 | 等待确认 / 第二因子 |
| 高置信 BCI + 低风险 + grant | 可（策略内） | soft affirm 或跳过低风险动作；**不可** 单独关高风险 hard |
| Agent token/音频流 | 否 | channel/harness；里程碑才 `artifact.commit` |

### C.5 并发 hard checkpoint（profile 选择）

在声明 `HLP-realtime` 时，实现 **MUST** 选择并文档化：

1. **Serialize**：同一 Task 同时至多一个 hard pending checkpoint（强化 §3.4 SHOULD）  
2. **Scope-partition**：不同 `permission_scope` 可并行 hard pending  
3. **Priority stack**：hard > soft；较新 soft 可 supersede 旧 soft 的生效视图（存储仍
   append-only）

未声明 realtime profile 的实现 **SHOULD** 继续遵循 §3.4 单一 pending。

### C.6 InteractionRef

实现 **MAY** 在 audit / amendment / checkpoint 元数据中携带 opaque：

```yaml
InteractionRef:
  channel: string
  session_id: string
  episode_id: string | null
```

**MUST NOT** 将 IM/Realtime Session 提升为 HLP 一等对象。

### C.7 Artifact：ephemeral vs sealed

- Harness/channel **MAY** 维护 ephemeral working copy（HLP 不存帧）。  
- HLP Artifact 仍遵守 §2.3 / §3.7 不可变版本链。  
- Review **MUST** 针对 sealed 版本。

### C.8 Profile 关系

| Profile | 含义 |
|---------|------|
| HLP-batch | 强 checkpoint 审批 |
| HLP-continuous | 0.2.0 连续控制（本规范正文） |
| HLP-industrial | CAS / outbox / schema 等（§6.4） |
| HLP-realtime | Soft/Hard + promotion + 合流 + intent provenance（本附录） |

声明 `HLP-realtime` **不等于** 提供媒体实时 SLA，只表示责任语义支持高频交互下的
晋级与审计。

### C.9 多 agent

Realtime 场景 **SHOULD NOT** 引入独立的“责任图”协议对象（D4）。多人/多 agent
协作继续用：单 Task 单一 `principal`、子 Task、`ownership.transfer` /
`ownership.delegate`。

### C.10 非目标

实现 **MUST NOT** 为支持本附录而：

- 引入 AudioFrame / EEGSample / TokenDelta 等 media 一等对象  
- 在 HLP core 绑定厂商 Realtime/BCI schema  
- 破坏 forward-only（例如可编辑已提交 audit/steering 历史）  
- 将 soft 信号直接等同于 `review.submit(approved)`  

完整非目标列表见计划文档。
