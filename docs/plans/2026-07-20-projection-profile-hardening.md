# 做扎实：Reference Profile 加固 + 四家 CLI 投影加固

Date: 2026-07-20
Status: done (see docs/notes/2026-07-20.md)

## 背景

落地路径共识：先把 reference profile 与四家 CLI 投影做扎实，等 harness 长出正式
run-control API 再换真连续性。当前两大薄弱点（直播 E2E 实证）：

1. **投影契约的最弱一环是靠 prompt 约束 LLM 回显 JSON**——claude 曾回
   `status:"acknowledged"`、pi steer 不回显 correlation_id。
2. **reference profile 的恢复语义只有半成品**——outbox 崩溃后停留 `pending`
   但无对外查询/恢复面；`checkpoint.expire` 只有手动 op，无 §7.2 参考扫描策略。

## W1 — 四家 CLI 投影加固

### 1. 原生结构化输出（治本，替代纯 prompt 约束）

探测已确认两家有原生 structured-output 能力，protocol 模式强制信封 schema：

- **Claude Code**：`--json-schema <inline JSON>`（约束最终 result）
- **Codex**：`--output-schema <FILE>`（约束最终 message）
- **Kimi / Pi**：无原生开关 → 维持 prompt 契约（docstring 注明），由解析层健壮性兜底

实现：

- 新增信封 schema 常量（`loops/hlp/adapters/` 内，如 `_parsing.py`：
  `HLP_RESULT_SCHEMA = {"type":"object","properties":{"run_id","correlation_id",
  "status":enum[ok,error],"summary","error","hlp":object},"required":["correlation_id","status"]}`）。
  `hlp` 保留为可选嵌套对象，给 human-loop 事件留通道。
- `ClaudeCodeHarnessAdapter` / `ClaudeCodeCLIAdapter`：`prompt_mode="protocol"`（默认）时
  命令追加 `--json-schema <json.dumps(schema)>`；`chat` 模式不加（自由回复 + JSON 尾）。
- `CodexHarnessAdapter` / `CodexCLIAdapter`：protocol 模式时把 schema 写入系统临时文件
  （懒创建、进程内缓存、`atexit` 清理），命令追加 `--output-schema <path>`。
- 构造参数保持可覆盖（调用方传自定义 command 时不动）。

### 2. 直播采样 → 固化 fixtures

- 对 claude / codex 各跑 2-3 次 protocol delegate（带 schema），**抓真实 wire 形状**
  （result 字段是 JSON 文本还是嵌套对象、schema 被拒时的报错形状），固化为离线
  fixtures；kimi / pi 同样补一组真实形状 fixtures（ fences、前后散文、CRLF、
  unicode、重复事件、缺失 correlation、畸形行）。
- 新增 `tests/test_hlp_projection_robustness.py`：按 CLI 参数化上述 fixtures，
  断言 payload 提取、correlation 校验、去重、畸形 fail-fast。

### 3. 测试与文档

- 离线断言：protocol 模式命令包含 schema 开关；chat 模式不含。
- `tests/conformance/README.md` 指引到四家 CLI 的离线契约套件与健壮性套件。
- README Adapter Depth 段补一句 structured-output 说明；CHANGELOG。

## W2 — Reference Profile 加固

### 1. Outbox 恢复面（失败语义补齐）

现状：intent 先持久化、成功后 `mark_adapter_outbox_succeeded`；崩溃停留 `pending`，
重试同 op（幂等路径）会复用记录的 checkpoint_id/amendment 重放 side effect
（conformance 已覆盖）。缺口是**可观测、可驱动的恢复面**：

- `HumanLoopOperations.pending_adapter_outbox() -> tuple[AdapterOutboxRecord, ...]`
  （过滤 `state=="pending"`，快照返回）——运维/host 可发现待恢复项。
- docstring/文档明确恢复循环：调用方按 pending 记录以原 `idempotency_key` 重试
  对应 op（幂等保证不重复副作用）。`HLPClient` facade 透传。
- 测试：崩溃注入（adapter 在 outbox 持久化后抛错）→ pending 可查 → 重试同 op →
  succeeded，且未重复副作用（ conformance 已有近似用例，补端到端断言）。

### 2. Checkpoint 超时扫描（§7.2 参考策略）

- `HumanLoopOperations.expire_due_checkpoints(now: datetime | None = None)
  -> tuple[Checkpoint, ...]`：扫描 `state=="pending" 且 expires_at <= now` 的
  checkpoint，逐个走现有 `checkpoint_expire`（自带前置校验 + audit + CAS/幂等）；
  Task 依参考策略保持 blocked（纯挂起，与现状一致）。
- 测试：到期被 expire + audit 有 `task.checkpoint.expired`；未到期不动；已
  resolved/expired 不动；幂等（重复扫描不产生重复事件/不报错）。

### 3. 文档

- README「Industrial Profile (Reference)」段补 outbox 恢复循环与 expire 扫描说明；
  CHANGELOG；notes；按 AGENTS.md 分两次提交（W1 / W2）。

## 非目标

- 会话恢复连续性（`kimi -r` 等）——仍是后续大功能，不在本次。
- 不改协议 spec、不改 AgentAdapter/HarnessAdapter 契约、不动状态机。
- 不追求 coverage 数字目标（健壮性测试会自然提升 adapters 覆盖率）。

## 验证

- `pytest tests/` 全绿（含新增 fixtures 套件与 W2 用例）；`mypy loops` strict 绿；
  `ruff check` / `ruff format --check` 绿。
- 直播抽查（少量调用）：claude/codex protocol delegate 带 schema 成功回显信封；
  记录结果进 notes。若某 CLI 版本拒绝 schema 开关，offline fixtures 记录并在
  adapter docstring 注明版本要求。
