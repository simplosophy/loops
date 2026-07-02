# HLP 连续控制扩展（Continuous-Control Extension）

| | |
|---|---|
| **日期** | 2026-07-02 |
| **状态** | 已确认方向，spec 已修订 |
| **关联** | `docs/specs/HLP.md` 0.1.0-draft → 0.2.0-draft |
| **动机** | 2026-07-02 对四类 agent harness（编码 CLI / 多 agent 框架 / 云端自主 agent / 既有协议标准）的调研 |

## 背景

调研结论：HLP 的「责任闭环」定位被证据验证——MCP / A2A / OpenAI Responses /
AWS Step Functions / AutoGen / ISO·IEEE·EU AI Act 没有一个把
「delegation → checkpoint → review → ownership transfer → audit」整成一个 typed
wire contract。HLP 想占的缝隙是真的空的。

但当前 spec 只覆盖了「agent 发起阻塞 → 人决策 → agent 恢复」这一半交互。真实工具
里占主导的是「人持续在场：随时打断、随时改方向、预授权、中途接管、中途改状态」的
连续控制模型。这些原语要么 spec 没有，要么被 §2.3 不可变性直接禁止。adapter 会正好
撞在 spec 的墙上。

## 设计原则（不可破）

- **守住 forward-only / 可审计**：所有新增对象（steering_log、PermissionGrant）
  都是 append-only / 不可变，强化而非弱化可审计性。
- **不 inflate 一等对象**：PermissionGrant 作为 `Constraints` 的值对象，不升格为
  第 8 个一等对象。保持「7 个一等对象」。
- **不放弃 HLP 边界**：tool trace / prompt / memory / planner state 仍由 harness
  拥有；HLP 只加 human-facing 语义原语。

## 变更清单（spec §级）

### 1. `task.interrupt` —— 人发起的打断
- 新操作。调用方 principal。`in_progress → blocked`。
- 系统代为 raise 一个 `Checkpoint(kind="interrupt")`。
- 解决缺口：CLI 的 Esc/Ctrl+C、云端 Stop button、take-over 入口目前无协议原语。
- §4.1 / §4.2 / §4.3 / §3.3 / §5.1（→ adapter `block`）。

### 2. `task.amend` + `steering_log` —— 转向不重启
- 新操作。调用方 principal。向 append-only `steering_log` 追加 `SteeringAmendment`。
- **不改 `spec`**，不改 state。agent 通过 adapter `steer` 收到 amendment。
- §2.3 旧建议「cancel + 新建」改为「amend；需彻底重启才 cancel+new」。
- 解决缺口：Codex `/goal`、Gemini model steering、Claude Esc+重提、Devin steering
  都不要求重启，原 spec 与全行业习惯对抗。
- §2.3 / §3.2（Task 字段 + SteeringAmendment）/ §4 / §5.1（→ adapter `steer`）。

### 3. `PermissionGrant` + `autonomy` + 批量审批 —— 预授权与粒度
- `Constraints` 扩展：`autonomy: AutonomyTier`、`grants: [PermissionGrant]`。
- `AutonomyTier`: `autonomous | plan_then_implement | confirm_each_action | read_only`。
- `PermissionGrant`: scope / decision(allow|deny) / until / granted_by。append-only，
  last-write-wins by scope。
- `Checkpoint.proposed_actions: [ProposedAction]`（批量提议动作）。
- `CheckpointResolution.approved_actions/denied_actions`（部分批准）。
- 解决缺口：现场审批是 per-tool/per-hunk + 档位 + allow-always + sandbox；HLP 现在是
  task 级单 pending。本变更把「预授权边界」和「批量+部分批准」引进协议层。
- §3.2 / §3.4 / §3.4 consistency。

### 4. `Review.kind` —— 中间态评审 vs 终态评审
- `Review.kind: "plan" | "deliverable"`（默认 deliverable，向后兼容）。
- 状态机加 `under_review → in_progress`（plan approved）。
- `under_review → accepted` 仅 deliverable approved。
- 解决缺口：plan 评审是中间产物，审完继续写代码；原 spec 审 artifact 即推向终态，
  无法表达「审中间产物，通过后继续」。
- §3.3 / §3.6。

### 5. `CheckpointResolution.state_patch` / `edited_artifact_ref` —— resume 带改过的状态
- resolution 加可选 `state_patch: object | null`、
  `edited_artifact_ref: {id, version} | null`。
- 解决缺口：LangGraph `update_state(as_node=)`、Devin/Factory take-over 是人直接改
  agent 中间态再继续；原 resolve 只带「回答」，不带「状态补丁」。
- §3.4。

### 6. take-over 注释
- §3.3 注：`in_progress` 的 assignee MAY 在 take-over 期间是 human（经
  `ownership.transfer`）。

## 不做

- 不加 transport 绑定（§7.1 仍 open）。
- 不加多 reviewer 合成规则（§7.5 仍 open）。
- 不改 Python 参考实现（本计划只修 spec + 架构文档；代码同步另立计划）。

## 验证

- spec 内部一致：操作数 21 → 23；状态机新增转移合法；audit action 表覆盖新操作。
- 架构文档 `hlp.md` / `OVERVIEW.md` 同步操作数、状态机图、adapter 表（+ `steer`）。
- §2.3 不可变性扩充后仍 forward-only。
