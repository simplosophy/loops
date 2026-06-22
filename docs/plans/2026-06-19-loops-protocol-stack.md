# Loops Protocol Stack 设计稿

> 日期：2026-06-19
> 状态：已确认（设计稿），待参考实现
> 范围：将 loops 从"软件实现"重新定位为"协议栈规范"，并填补生态缺失的人机责任闭环协议

---

## 0. 背景与动机

loops 最初被设计为一套三层软件（loop0 执行内核 / loop1 交互容器 / loop2 协同编排）。
随着 AI 协作协议生态的成熟（MCP、Skills、A2A、ACP、AGNTCY），我们意识到：

**loops 不应该再做一个软件，而应该成为 AI 协作的协议栈规范——AI 协作的 OSI 模型。**

已有协议各自优秀，但它们是孤立的"砖"，缺一个"建筑规范"来规定：
- 每块砖属于哪一层
- 层与层之间怎么咬合
- 哪一层还缺砖

现有协议的归位情况：

| loop | 协议 | 解决什么 | 成熟度 |
|------|------|---------|--------|
| L0 能力 | MCP、Skills | agent ↔ 工具/能力 | ✅ 事实标准 |
| L1 agent 间 | A2A、ACP、AGNTCY | agent ↔ agent 发现/委派 | 🟡 群雄并起 |
| L2 人机责任闭环 | ❓ | agent ↔ 人 在项目/组织级协作 | ⛔ **生态空白** |

loops 的核心贡献：**把已有协议分层归位，定义层间契约，并填补 L2 的生态空白。**

---

## 1. 命名与定位

### 1.1 栈名与各层协议命名

**全栈名：Loops Protocol Stack（loops 协议栈）**

| 层 | 协议名 | 全称 | 定位 |
|----|--------|------|------|
| **L2** | **HLP** | Human Loop Protocol | loops 新建 — 人机责任闭环 |
| **L1** | **AAP** | Agent–Agent Protocol | 复用 A2A / ACP |
| **L0** | **CAP** | Capability Protocol | 复用 MCP + Skills |

### 1.2 一句话定位

> loops 协议栈是 AI 协作的 OSI 模型——三层协议、每层只解一个维度、层间靠显式契约咬合。
> 已有协议（MCP/Skills/A2A）是各层的"参考实现"，loops 定义的是**层规范和层间接口**，不是又一个新协议。

### 1.3 关键叙事

loops 不和 MCP/A2A 竞争，而是给它们一张坐标系。对外叙事：
**"我们把已有协议分层归位，并补上了缺失的人机责任闭环层"**——这是真正没人做、也最该做的事。

---

## 2. 栈拓扑与层边界

### 2.1 栈拓扑图

```text
┌──────────────────────────────────────────────────────────────┐
│                     人 (principal)                            │
│            团队成员 · 审批者 · 委派者 · 评审者                 │
└──────────────────────────┬───────────────────────────────────┘
                           │ HLP  (L2 · 人机责任闭环)
                           │ Task / Checkpoint / Ownership / Review
                           │ Artifact / Ledger / Audit
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                     agent (worker)                            │
│           自主执行单元 · 可委派子 agent · 可调用能力            │
└──────────────────────────┬───────────────────────────────────┘
                           │ AAP  (L1 · agent 间)
                           │ delegate / handoff / discovery
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                     能力 (capability)                         │
│            工具 · 资源 · 打包技能（prompt+资源+权限）           │
└──────────────────────────────────────────────────────────────┘
                            ▲
                            │ CAP  (L0 · 能力)
                            │ tool.call / resource.read / skill.invoke
                            │
                     (agent runtime 内部)
```

### 2.2 每层的"做什么 / 不做什么"

**L0 — CAP（能力协议）**
- **做**：定义 agent 如何调用一个外部能力。能力分两种粒度——`Tool`（单函数，等价 MCP tool）和 `Skill`（打包的复合能力，带 prompt 模板 + 资源 + 权限声明，等价 Skills 协议）。
- **不做**：不知道谁是 caller（不区分人/agent）、不管会话状态、不管组织。
- **归位**：MCP 是 CAP 的参考实现（transport + tool schema）；Skills 协议是 CAP 的 `Skill` 粒度参考实现。loops 不重写它们，只定义"一个能力必须暴露的最小契约"。

**L1 — AAP（agent 间协议）**
- **做**：定义 agent ↔ agent 如何发现彼此、委派工作、交接上下文。核心原语：`delegate`（把子任务交给另一个 agent）、`handoff`（把整个 ownership 转交）、`discover`（按能力查找 agent）。
- **不做**：不定义 agent 内部怎么跑（那是 runtime 的事）、不定义 agent 怎么和人对话（那是 HLP）、不定义 agent 怎么调工具（那是 CAP）。
- **归位**：A2A 是 AAP 的参考实现（agent card + task delegation）；ACP 同类。loops 定义的是"agent 间必须支持的最小交互面"。

**L2 — HLP（人机责任闭环协议）**
- **做**：定义人 ↔ agent 如何围绕一个 **Task** 协作。核心原语：`Task`（一等公民，下行委派）、`Checkpoint`（上行把关，挂在 Task 生命周期上）、`Ownership`（谁负责这个 Task）、`Review`（人对产物的结构化反馈）、`Artifact`（结构化交付物）、`Ledger`（组织级状态沉淀）、`Audit`（不可变操作日志）。
- **不做**：不定义 agent 内部执行、不定义 agent 间委派（那是 AAP）、不管 UI 渲染（HLP 是协议，不是前端规范）。
- **新建**：这是 loops 的核心贡献，目前生态空白。

### 2.3 层间契约（loops 真正的资产）

层与层之间不是自由组合，而是靠**显式契约**咬合。每个契约是一个跨层对象的"出生证 + 移交规则"：

| 契约 | 跨层对象 | 出生层 | 移交方向 | 契约内容 |
|------|---------|--------|---------|---------|
| **Task→Run 映射** | Task | L2 (HLP) | L2→L1 | Task 在 L1 触发一个 agent delegate；TaskID 必须贯穿到 AAP 的 delegate 调用 |
| **Checkpoint→Block 映射** | Checkpoint | L2 (HLP) | L2↔L1 | Checkpoint 挂起 Task 时，AAP 层对应的 agent delegate 必须进入 blocked 状态等待 |
| **Capability 引用** | CapabilityRef | L0 (CAP) | L0→L1→L2 | 上层只引用 capability ID + version，不感知底层 transport（MCP/SSE/stdio） |

### 2.4 关键纪律（对应 AGENTS.md 设计原则）

- **依赖只能向下**：HLP 可调 AAP，AAP 可调 CAP；反向禁止。人永远不直接调 CAP，agent 永不被 HLP 反向控制以外的途径 push。
- **跨层只走契约对象**：Task、Checkpoint、CapabilityRef 是仅有的合法跨层载体。任何层不得直接读写邻层内部状态。
- **状态归属清晰**：Task 状态归 HLP，Run/agent 状态归 AAP，能力实例归 CAP。

---

## 3. HLP 七个一等契约对象

### 3.1 对象全景

```text
        ┌─────────────────────────────────────────────────────┐
        │                    HLP (L2)                         │
        │                                                      │
        │   Task ──── Ownership ──── Review                    │  ← 协作流
        │     │                                  ▲             │
        │     │生出                                │作用于       │
        │     ▼                                    │             │
        │   Checkpoint ──── 交付 ─────▶ Artifact ──┘             │  ← 产物
        │                                                      │
        │   Ledger   (横切：组织级状态沉淀)                      │  ← 组织沉淀
        │   Audit    (横切：所有操作的不可变日志)                │  ← 观测
        │                                                      │
        └─────────────────────────────────────────────────────┘
```

### 3.2 对象职责表

| 对象 | 一句话定义 | 类比 | 谁产生它 | 谁消费它 |
|------|-----------|------|---------|---------|
| **Task** | 人交给 agent 的一个有边界的工作单元 | JIRA ticket / Devin task | 人（principal） | agent 执行；人 review |
| **Checkpoint** | Task 执行中的决策点，暂停等待人介入 | GitHub PR review、CI gate | agent 声明 | 人回应 |
| **Ownership** | Task 此刻归谁负责的凭证，可转移 | git blame / 工单 assignee | 创建时归人；委派时转 agent；回退时转人 | 所有层可查 |
| **Artifact** | Task 的结构化交付物 | PR diff、设计稿、报告 | agent 产出 | 人 review；下游 Task 消费 |
| **Review** | 人对 Artifact 的结构化反馈 | PR review comment | 人 | agent 据此修改 |
| **Ledger** | 组织级持久状态沉淀（append-only） | 会计总账、Terraform state | 所有对象的状态变更 | 后续 Task 读取 |
| **Audit** | 所有协议操作的不可变日志 | SOC2 audit log | 协议层自动记录 | 审计/合规/回溯 |

### 3.3 关系语义（非显然但重要的设计决定）

**① Artifact 与 Task 是"交付关系"，不是父子关系**
Artifact 是 Task 的产出，但**生命周期独立于 Task**——Task 结束后 Artifact 继续存在，还能被下游 Task 引用为输入。这避免了"重跑一个旧 Task 就把别人的依赖删了"。类比：PR merge 后 commit 永存，新 PR 可基于它。

**② Ownership 是可转移凭证，不是固定属性**
同一个 Task 的 ownership 会流动：人创建（own=人）→ 委派给 agent（own=agent）→ checkpoint 触发回退（own=人）→ 人 approve 后再转回（own=agent）。这条"ownership 流"本身就是 Task 状态机的核心。

**③ Ledger 横切所有对象，归属组织/project space**
Ledger 是 project space 级的沉淀——任何 Task 都可读、任何对象的状态变更都可写。命名刻意避开 "Memory"（AI 语境下易被误解为 agent 对话记忆/RAG 向量库），强调"持久 + 可审计 + 累积"的组织账本语义。

**④ Audit 不参与业务流，只观测**
Audit 是只写不改的 append-only 日志，记录每一次协议操作。它永远不阻塞业务流，但保证可回溯。前 6 个对象是控制平面，Audit 是观测平面。

### 3.4 为什么是这 7 个，不多不少

刻意拒绝提升为一等对象的：

- ❌ **Session/Conversation**：会话是 loop1（交互层）的事，HLP 只关心 Task 级协作。一个 Task 可以跨多个 session，一个 session 也可以包含多个 Task。
- ❌ **Permission/Role**：权限模型太组织相关，HLP 只声明 ownership，具体 RBAC 留给实现。
- ❌ **Notification**：通知是 channel（loop1）的事，HLP 只定义 Checkpoint 事件，怎么送达是 UI 的事。

---

## 4. HLP 核心 Schema

### 4.1 Task —— 协议的主语

```yaml
Task:
  id: "task_01HXY..."            # ULID，全局唯一
  type: "code-review"            # Task 类型，可扩展

  # ── 意图层：人告诉 agent "做什么" ──
  spec:
    goal: "Review PR #1234 for security issues"   # 自然语言目标
    acceptance_criteria:                          # 结构化验收标准
      - "All reviewer comments resolved"
      - "CI passes"
    inputs:                                       # 输入引用
      - { kind: "artifact", id: "art_...", version: "v3" }
      - { kind: "resource", uri: "github://.../pr/1234" }
    constraints:                                  # 边界
      max_duration: "2h"
      must_use_capabilities: ["cap:code-review:v2"]

  # ── 治理层：谁负责 ──
  ownership:
    principal: "user_alice"      # 最终负责人（人）
    assignee: "agent_devin"      # 当前执行者（可流转）
    delegations: []              # 委派链历史

  # ── 生命周期 ──
  state: "in_progress"           # 见状态机
  parent_task: null              # 父 Task（支持子任务拆分）
  created_at: ...
  deadline: ...

  # ── 协议层挂载点（引用，非内嵌）──
  checkpoints: []                # Checkpoint ID 列表
  artifacts: []                  # 产出 Artifact ID 列表
  audit_trail: "audit_..."       # 指向 audit 分支
```

### 4.2 Task 状态机

```text
                    ┌──────────────────────────────────────┐
                    │                                      ▼
  created ──▶ assigned ──▶ in_progress ──┐         blocked (等待人)
                │              │         │              │
                │              │         └──────────────┘
                │              │              人 approve/reject
                │              ▼
                │         review_ready ──▶ under_review ──┐
                │              │                    │      │
                │              │              人 review   │ changes_requested
                │              │                    │      ▼
                │              │                    └─→ in_progress (返工)
                │              ▼
                │            accepted ───────────────┐
                │                                   ▼
                └────────────────────────────── completed
```

**状态语义（每个状态对应 ownership 归属）**：

| 状态 | ownership.assignee | 含义 |
|------|-------------------|------|
| `created` | principal | 人刚建，还没指派 |
| `assigned` | agent | 已委派给 agent，未开始 |
| `in_progress` | agent | agent 执行中 |
| `blocked` | **principal** | checkpoint 触发，**球在人这边** |
| `review_ready` | principal | agent 交付，等人 review |
| `under_review` | principal | 人正在 review |
| `accepted` | principal | 验收通过，准备收尾 |
| `completed` | principal | 终态 |

**关键洞察**：这个状态机把 A（审批）和 B（委派）缝在了一起——`in_progress → blocked` 是上行 checkpoint（A），`review_ready → under_review` 是下行交付的 review 关卡（B 的尾部）。它们用同一套状态流转，不需要两套并行机制。

### 4.3 Checkpoint —— 上行把关

```yaml
Checkpoint:
  id: "ckpt_..."
  task_id: "task_01HXY..."          # 归属 Task

  kind: "approval"                  # approval | choice | input | escalation
  # approval: 要人 yes/no（如：这个变更可以部署吗）
  # choice: 要人选一个（如：用方案 A 还是 B）
  # input: 要人提供信息（如：生产环境密码）
  # escalation: agent 撞到权限墙，上交给人

  prompt: "我准备删除 3 条旧索引，确认执行吗？"   # 给人的说明
  options:                          # kind=choice 时
    - { id: "opt_a", label: "删索引 A、B", risk: "medium" }
    - { id: "opt_b", label: "保留，只删 C", risk: "low" }
  context:                          # 支撑决策的证据
    - { kind: "artifact", id: "art_..." }
    - { kind: "text", content: "这三条索引 7 天无访问..." }

  state: "pending"                  # pending | resolved | expired
  raised_at: ...
  expires_at: ...                   # 超时策略
  resolution: null                  # 见下
```

```yaml
CheckpointResolution:
  by: "user_alice"
  action: "choose"                  # approve | reject | choose | provide | reassign
  choice: "opt_b"                   # action=choose 时
  comment: "保险起见保留 A、B"
  at: ...
```

**Checkpoint 触发 Task 状态联动**：Checkpoint 进 `pending` → Task 进 `blocked`；Checkpoint 进 `resolved` → Task 回 `in_progress`（或按 action 进别的终态）。

### 4.4 Ownership —— 可转移凭证

```yaml
Ownership:
  task_id: "task_..."

  principal: "user_alice"           # 永不变（最终负责人）
  assignee: "agent_devin"           # 当前执行者
  delegable: true                   # agent 是否可再向下委派

  # 委派链（append-only）
  chain:
    - { from: "user_alice",  to: "agent_devin",  at: t1, via: "assign" }
    - { from: "agent_devin", to: "user_alice",   at: t2, via: "checkpoint" }
    - { from: "user_alice",  to: "agent_devin",  at: t3, via: "approve" }
```

**规则**：每次 ownership 变更必须 append 到 `chain`，且必须对应一个合法的协议事件（assign/checkpoint/approve/reject/handoff）。Audit 会独立记录这条链。

### 4.5 Review —— 人对产物的结构化反馈

```yaml
Review:
  id: "rev_..."
  task_id: "task_..."
  artifact_id: "art_..."            # 针对哪个交付物
  reviewer: "user_bob"

  verdict: "changes_requested"      # approved | changes_requested | rejected

  comments:                         # 结构化批注
    - { anchor: "line:42", severity: "blocker", body: "这里没处理 null" }
    - { anchor: "file:auth.ts", severity: "major", body: "建议抽成 util" }

  requested_changes:                # 要求的具体改动（驱动 agent 返工）
    - "修复 auth.ts:42 的 null 检查"
    - "抽取 null-check 为 util 函数"

  at: ...
```

**与 Task 状态机的联动**：`verdict=approved` → Task 进 `accepted`；`verdict=changes_requested` → Task 回 `in_progress`，agent 据 `requested_changes` 返工。

### 4.6 Artifact —— 独立生命周期的产物

```yaml
Artifact:
  id: "art_..."
  type: "code_patch"                # code_patch | document | report | dataset | ...

  provenance:
    produced_by: "task_..."         # 产出它的 Task
    produced_at: ...

  version: "v3"                     # 独立版本号（Task 结束后仍可演进）
  parent_version: "v2"              # 前一版（支持版本链）

  payload:
    kind: "diff"                    # diff | blob | ref | inline
    uri: "artifact-store://art_.../v3"
    checksum: "sha256:..."
    size: 12345

  references:                       # 被谁消费
    - { task_id: "task_...", as: "input" }
```

**关键约束**：Artifact 一经创建**不可变**（immutable），要改就产新版本。这让审计和回溯变得简单——任何 Task 引用 Artifact 时锁定 `id+version`。

### 4.7 Ledger —— 组织级状态沉淀

```yaml
Ledger:
  id: "led_..."
  scope: "project:web-revamp"       # project | team | org

  entries:                          # append-only，每条都是组织的一笔"账"
    - { key: "deploy.key_path", value: "/etc/...", written_at: t1, by: "task_..." }
    - { key: "conventions.naming", value: "...", written_at: t2, by: "task_..." }

  # 读 API（协议只定义接口，存储留给实现）
  # read(scope, key) -> value | null
  # write(scope, key, value, writer_task_id) -> 产生 audit event
  # history(scope, key) -> [entries]   # 支持回溯
```

**命名说明**：刻意避开 "Memory"（AI 语境下易被误解为 agent 对话记忆 / RAG 向量库）。Ledger 强调"持久 + 可审计 + 累积"的组织账本语义，和 Audit 形成"状态累积 + 操作日志"的语义闭环。

### 4.8 Audit —— 只观测、不参与流

```yaml
AuditEvent:
  id: "aud_..."
  seq: 1042                         # 单调递增序号
  at: ...
  actor: "agent_devin"              # user_* | agent_*

  action: "task.checkpoint.raised"  # <object>.<verb> 命名规范
  subject: { kind: "checkpoint", id: "ckpt_..." }
  task_id: "task_..."               # 始终关联到 Task（聚合根）

  before: { ... }                   # 变更前状态（可选）
  after: { ... }                    # 变更后状态（可选）
```

**规则**：每次协议操作（Task 状态转移、Checkpoint 变更、Ownership 转移、Artifact 版本、Ledger 写入）都必须产生一条 AuditEvent。Audit 只写不改，不阻塞业务，但支持回放和合规导出。

---

## 5. 协议操作清单（API 面）

### 5.1 操作总表

HLP 的 API 面很小——这是刻意的。每个对象只有最小必要操作，遵循 loops 的极简原则。所有操作命名遵循 `<object>.<verb>`。

```text
┌─────────────── Task（协作流主语）────────────────┐
│ task.create          人创建一个 Task              │
│ task.assign          人把 Task 委派给 agent       │
│ task.cancel          人中止 Task                  │
│ task.get / list      查询                         │
└─────────────────────────────────────────────────┘

┌──────────── Checkpoint（上行把关）──────────────┐
│ checkpoint.raise     agent 声明一个决策点         │
│ checkpoint.resolve   人回应（approve/reject/...） │
│ checkpoint.expire    超时自动失效                 │
└─────────────────────────────────────────────────┘

┌──────────── Ownership（可转移凭证）─────────────┐
│ ownership.transfer   转移 assignee（内部调用）    │
│ ownership.delegate   agent 向下委派（需 delegable）│
└─────────────────────────────────────────────────┘

┌──────────── Review（人对产物的反馈）────────────┐
│ review.submit        人提交 review（含 verdict）   │
│ review.comment       追加批注                     │
└─────────────────────────────────────────────────┘

┌──────────── Artifact（产物）────────────────────┐
│ artifact.commit      agent 产出/版本递进          │
│ artifact.get         按 id+version 取             │
│ artifact.reference   被 Task 引用为输入           │
└─────────────────────────────────────────────────┘

┌──────────── Ledger（组织状态沉淀）──────────────┐
│ ledger.read          读 key                      │
│ ledger.write         写 key（触发 audit）         │
│ ledger.history       回溯 key 的变更              │
└─────────────────────────────────────────────────┘

┌──────────── Audit（只观测）─────────────────────┐
│ audit.query          按 task/actor/action 查      │
│ audit.replay         回放某 Task 的完整历史       │
│ （无写操作 — 由协议层自动产生）                    │
└─────────────────────────────────────────────────┘
```

**设计选择**：没有 update/delete。Task 不能改 spec（要改就 cancel 重建）；Artifact 不能改（要改就新版本）；Ledger 不能删（append-only）。这保证整个协议**只前进、可回溯**。

**操作总数：21 个**。对比 MCP（~15）、A2A（~10），HLP 略多但完全合理——因为它要治理的对象也更多（7 个一等对象）。

### 5.2 完整协作流时序验证

用 "Review PR #1234" 场景把 21 个操作串起来，验证协议完整性：

```text
人 Alice                     HLP 协议层                  agent Devin
  │
  │── task.create ──────────▶│
  │                          │── audit: task.created ──▶ (Audit)
  │── task.assign ──────────▶│
  │                          │── ownership: alice→devin
  │                          │── audit: task.assigned ─▶
  │                          │── AAP delegate ─────────▶│ (进 L1)
  │                                                     │
  │                                                     │ (执行，发现风险)
  │                          │◀── checkpoint.raise ────│
  │                          │── task: in_progress→blocked
  │◀── checkpoint 通知 ──────│  (通过 loop1 channel 送达)
  │                                                     │
  │── checkpoint.resolve ───▶│  (choose opt_b)
  │                          │── ownership: 暂留 alice
  │                          │── task: blocked→in_progress
  │                          │── AAP resume ──────────▶│
  │                                                     │
  │                                                     │ (完成)
  │                          │◀── artifact.commit ─────│ (产出 review 报告 v1)
  │                          │◀── task: in_progress→review_ready
  │◀── review 邀请 ──────────│
  │                                                     │
  │── review.submit ────────▶│  (changes_requested + 2 条批注)
  │                          │── task: review_ready→under_review→in_progress
  │                          │── AAP resume ──────────▶│ (返工)
  │                                                     │
  │                                                     │ (修复)
  │                          │◀── artifact.commit ─────│ (报告 v2)
  │                          │◀── task: →review_ready
  │── review.submit ────────▶│  (approved)
  │                          │── task: →accepted→completed
  │                          │── ledger.write ────────▶ (记录"PR#1234 已通过"到项目 ledger)
  │                          │── audit: 全程已记录
```

**验证结论**：
1. 21 个操作足以表达一个完整的"委派→把关→交付→返工→验收"闭环。
2. ownership 在 alice↔devin 之间流转了 4 次，全部走协议、全部进 audit。
3. HLP 和 AAP（L1）的衔接点是 `delegate/resume`，和 loop1 channel 的衔接点是"通知送达"——层间契约干净。

---

## 6. 与已有协议的最终关系图

```text
                    loops 协议栈（AI 协作的 OSI 模型）

  ┌───────────────────────────────────────────────────────────┐
  │  L2  HLP    Human Loop Protocol                         │  loops 新建 ★
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

---

## 7. 开放议题

设计到这个深度已经可以定稿，但以下几个议题**故意没在设计稿里拍板**，因为它们要么是实现相关、要么需要先有参考实现才能验证：

| # | 议题 | 倾向 | 为什么留开放 |
|---|------|------|------------|
| 1 | **Transport 绑定**：HLP 是只定义语义、还是也绑定 HTTP/gRPC/WebSocket？ | 只定义语义，transport 留给实现（同 MCP 哲学） | 协议应 transport-agnostic，先有语义参考实现再收敛 |
| 2 | **Checkpoint 超时后的默认动作**：auto-reject？auto-escalate？还是纯挂起？ | 纯挂起 + 可配置策略 | 不同组织风险偏好差异大，协议不该强加 |
| 3 | **Ownership 多级委派深度**：agent 能否把 Task 再委派给子 agent（链式）？ | 允许，但 `delegable` 标志位逐级可关 | 需要参考实现验证滥用风险 |
| 4 | **Ledger 的并发写**：两个 Task 同时写同一个 key 怎么办？ | last-write-wins + audit 记录冲突 | 强一致会拖垮协议，先简单 |
| 5 | **Review 的多人协作**：一个 Artifact 能否被多人 review？ | 支持，verdict 取最严（任一 reject 则 reject） | 需要验证是否会拖慢流程 |
| 6 | **Artifact 跨 project 引用**：A 项目的 Task 能否引用 B 项目的 Artifact？ | 允许，但需显式跨域授权 | 涉及权限模型，HLP 刻意不定义 RBAC |
| 7 | **版本兼容**：HLP v1 的 Task 能否被 v2 的 agent 执行？ | 语义版本 + 向后兼容保证 | 需要至少一次真实演进才能定规则 |

---

## 8. 与 loops 仓库既有架构的关系

本设计稿改变了 loops 项目的定位，但不否定既有工作：

- **既有 `loop0/loop1/loop2` 软件分层**：仍然有效，它现在被理解为**协议栈各层的参考实现**。loop0 实现 CAP+AAP 的 host，loop1 实现 HLP 的 channel 适配，loop2 实现 HLP 的协议核心。
- **`docs/architecture/LOOPS_STACK.md`**：需要更新，把定位从"三层软件架构"调整为"三层协议栈规范"。
- **既有协议相关代码**（provider adapter、shell tool 等）：归位为 CAP 的参考实现，无需重写。
- **后续路线**：loops 的开发重心从"写 loop0/loop1/loop2 软件"转向"定义 HLP 规范 + 提供参考实现"。

---

## 9. 后续工作

1. **更新 `docs/architecture/LOOPS_STACK.md`** — 重新定位为协议栈规范（本次同步完成）
2. **HLP 参考实现** — 用最小代码实现 21 个操作，验证协议可落地
3. **HLP spec 文档** — 从本设计稿提炼出独立的、对外发布的协议规范（类似 MCP spec）
4. **与 A2A/MCP 的互操作验证** — 证明层间契约可工作
5. **开放议题逐一收敛** — 每个议题在参考实现后定结论
