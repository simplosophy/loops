# HLP Industrial Hardening Plan

| | |
|---|---|
| **日期** | 2026-07-04 |
| **状态** | 执行中 |
| **关联** | `docs/specs/HLP.md` 0.2.0-draft reference implementation |

## 背景

2026-07-04 对 HLP 做了四路只读审计：协议规范、核心实现、SDK/adapters、
发布与验证矩阵。结论一致：HLP 的架构边界是对的，但 0.2.0-draft 已公开
声明连续控制和 conformance，参考实现仍大体停在 21 个操作的旧闭环。

本计划按工业协议治理方式推进：先让公开规范可执行，再把可执行行为固化为
conformance，再做生产一致性 profile。避免把 HLP 扩成 agent harness 或服务端
平台。

## 原则

- HLP 仍只 owns human-interaction control plane，不吸收模型、tool、planner、
  memory、channel 或 runtime。
- 0.2.0 新增能力必须 forward-only：转向、预授权、partial approval、人改状态后
  resume 都要进入 append-only 对象和 audit。
- 修复应先落测试，当前参考实现不能只靠文档自称兼容。
- 生产级事务、outbox、hash-chain audit 是后续 profile，不阻塞 0.2.0 reference
  implementation 可执行化。

## Phase 1: 0.2.0 Reference Implementation

目标：参考实现支持 `docs/specs/HLP.md` 0.2.0-draft 的公开承诺。

范围：
- `Task.steering_log` 与 `task.amend`。
- `task.interrupt`，系统 raise `kind="interrupt"` checkpoint 并 block harness run。
- `AgentAdapter.steer`，对应 `task.amend`，不重启 run。
- `PermissionGrant` / `autonomy` 值对象，保持 append-only 数据模型。
- `Checkpoint.proposed_actions` 与 `CheckpointResolution.approved_actions` /
  `denied_actions`。
- `CheckpointResolution.state_patch` / `edited_artifact_ref` 进入 resume payload。
- `Review.kind` 区分 plan 与 deliverable。
- SDK facade 导出上述操作和对象。

同时修复第一批不改变架构边界的安全缺口：
- harness event 投影前校验 run/task correlation。
- process/prompt delegate 缺少 `run_id` 时 fail fast。
- `artifact.get(id, missing_version)` 返回 `NOT_FOUND`，不能回退 latest。
- expired checkpoint resolve 返回 `CHECKPOINT_EXPIRED`。
- sealed Review/Artifact 不能通过 `_sealed=False` 解封。
- task cancel 后 ownership 回 principal。

## Phase 2: Executable Conformance

目标：第三方实现能用机器可跑的 suite 验证 HLP-compatible / HLP-integrated 声明。

范围：
- 新增 `tests/conformance/`，覆盖 23 operations、状态机正负例、不可变性、audit、
  adapter contract 和 golden flow。
- 增加 release verification 命令，默认 offline 可复现；真实 CLI smoke 走 opt-in。
- 统一 `SDK version` 与 `Spec version` 的公开说明。
- 增加 source spec 与 site spec 同步检查，消除 validated/waiting 文案漂移。

状态：已新增离线 conformance suite；release verification 脚本与默认离线命令入口已落地。

## Phase 3: Industrial Profile

目标：定义而非隐式假设生产一致性能力。

范围：
- per-task CAS / idempotency key / durable outbox 设计。
- adapter event peek/ack cursor，避免投影半失败丢事件。
- reducer-ready audit payload 与可选 tamper-evident hash chain。
- permission scope grammar、deny precedence、grant expiry 和授权主体规则。
- object/wire JSON schema、error object、version negotiation。

状态：
- 已完成 reference slice：`HarnessEventDelivery(cursor, event)`、可选
  `peek_events` / `ack_events`、Fake/Codex harness adapter 支持非破坏式读取，
  `HLPClient.project_harness_events` 成功投影后才 ack，失败保留未确认事件。
- 已完成文档边界：`HLP-compatible` / `HLP-integrated` 不等同于
  `HLP-industrial`；工业声明还需要 CAS、idempotency、durable outbox、
  reducer-ready audit、permission grammar、schema 与 version negotiation 证据。
- 已完成 reference slice：`Task.revision`、`expected_task_revision` CAS、
  task-scoped `idempotency_key`、canonical request fingerprint 与 replay 记录。
  当前覆盖所有会推进现有 `Task.revision` 的 Task aggregate mutation：
  `task.assign`、`task.start`、`task.cancel`、`task.amend`、`task.interrupt`、
  `checkpoint.raise`、`checkpoint.resolve`、`checkpoint.expire`、
  `ownership.transfer`、`ownership.delegate`、`artifact.commit` 和
  `review.submit`，并通过 SQLite snapshot 持久化 reference idempotency records。
- 已完成 reference slice：permission scope grammar、normalize/match helper、
  grant expiry、active deny precedence，以及 `ProposedAction.permission_scope`。
- 已完成 reference slice：AuditEvent schema/profile 元数据、reducer-ready
  `subject` / Task snapshot / `change` payload、`prev_hash` / `hash`
  tamper-evident hash chain 与 `AuditLog.verify_hash_chain()`。
- 已完成 reference slice：`HLP_JSON_SCHEMAS`、`schema_for`、`to_wire`、
  `validate_wire_object`、`negotiate_hlp_version`，覆盖一等对象、核心工业
  wire shape、dataclass alias/RFC3339 serialization 和 spec/schema/profile
  fail-fast version negotiation。
- 已完成 reference slice：`AdapterOperationContext` 与 `AdapterOutboxRecord`。
  `task.assign`、`task.cancel`、`task.amend`、`task.interrupt`、
  `checkpoint.raise`、`checkpoint.resolve`、`ownership.transfer` handoff 与
  `ownership.delegate` 在 adapter side effect 前持久化 outbox intent，向
  fake/process/Codex adapter 传入 `operation_context`，本地提交成功后标记 outbox
  `succeeded`。

## 本轮执行边界

本轮已完成 Phase 1 的 0.2.0 reference implementation、Phase 2 的离线
conformance/release verification，以及 Phase 3 的 HLP-industrial reference
slice。工业能力保持在 SDK/protocol reference 边界内：只补 CAS/idempotency、
可靠 harness event delivery、permission grammar、audit/schema/version/outbox
证据，不把服务端化调度、transport binding、模型/tool runtime 或 channel 送达塞进
HLP core。
