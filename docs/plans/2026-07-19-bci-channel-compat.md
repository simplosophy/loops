# 脑电波（BCI/EEG）人机交互与 HLP 的兼容性：结论与参考接入计划

Date: 2026-07-19
Status: done (P1+P2; P3 real-hardware decoder interface is a follow-up)

## 结论

**可以兼容，且是设计内（by design）兼容。** 不需要改协议核心、不需要新增一等对象或操作。
脑电波交互在 HLP 架构中就是一个新的 **channel / sensor plane** 输入，与 TUI 键盘、IM 按钮、
语音同级。规范在 0.3 草案（附录 C）中已**显式收敛了 BCI 语义**，参考实现已有对应 helper。

### 规范与代码证据

| 关切 | 规范位置 | 现状 |
|---|---|---|
| BCI 归属哪一层 | 附录 C.1/C.2：BCI 属于 channel/sensor plane（高频、可丢、不可单独作法律责任依据），HLP 只通过 **promotion（晋级）** 接收降采样后的责任事件 | 三层时间尺度已定义 |
| 脑电信号的对象表示 | C.3：`ControlSignal` 值对象含 `source_kind`（`speech`/`text`/`ui`/`bci`/…）、`confidence`、`principal_binding`；**不是**一等对象 | `loops/hlp/objects.py` `ControlSignal` 已实现 |
| 连续/噪声脑电 → HLP | C.3 D1/D2：soft 不进状态机；host 合并后晋级为 `task.amend` / `SteeringAmendment` | `loops/hlp/realtime.py::merge_soft_control_signals`（置信过滤 + 合并 + provenance） |
| 离散脑电意图（"批准/拒绝"） | C.3 MUST 3：hard 必须走 `checkpoint.raise/resolve` / `task.interrupt` | 现有操作即可，channel 侧映射 |
| 安全红线 | C.0 D3 / C.3 MUST 7：**高风险 hard checkpoint 不得仅凭 BCI 关闭**，可要求第二因子；fail-closed | `realtime.py::require_hard_resolve_allowed` / `may_resolve_hard_checkpoint_with_signal`（已实现 `source_kind=="bci"` 特判） |
| 置信门槛 | C.3 MUST 1：低于声明阈值的 soft 不得单独触发 hard 效果 | `DEFAULT_SOFT_CONFIDENCE_THRESHOLD`（profile 可覆盖） |
| 身份绑定 | C.3 MUST 6：Principal 永远是人；BCI 只是意图传感器 | `principal_binding` 字段 + 合并时校验同 principal |
| 审计 | C.3 MUST 5：每次晋级须在 audit 可追溯（principal、时间、晋级类型） | `promotion_audit_payload`（含 source_kind/confidence/InteractionRef） |
| 会话元数据 | C.6 `InteractionRef{channel, session_id, episode_id}`（opaque） | 已实现，audit/amendment 可携带 |
| 防越界 | C.10：MUST NOT 引入 EEGSample 等 media 一等对象、MUST NOT 绑定厂商 BCI schema | 计划中遵守 |

### 脑电交互模式 → HLP 原语映射

- **离散想象意图**（如运动想象"确认/取消"）→ channel 解码为 hard `ControlSignal(intent=affirm/deny)` →
  调现有 `checkpoint.resolve`（低风险，confidence 达标）或被 D3 拦截（高风险需第二因子）。
- **连续/概率性调制**（注意力水平、渐进偏好）→ soft `ControlSignal` 流 → host 窗口合并
  （`merge_soft_control_signals`）→ 一条 `task.amend`（steering）。
- **紧急停止**（高置信 "halt"）→ `task.interrupt`。
- **低置信"同意"** → 不晋级，等待显式确认（C.4 晋级表已规定）。
- **Review  verdict**（想象选择 approve/changes_requested）→ `review.submit`，同样受 D3 风险策略约束。

## 缺口（要新建的，全部在 channel/host 侧）

协议侧**零改动**。缺的是一个证明兼容性的参考切片：

1. 没有 BCI channel 的参考实现（现有参考 channel 只有 TUI）。
2. D3 的 `high_risk` 判定目前由调用方传入，参考 channel 需要一个从 checkpoint
   kind/options risk 推导 risk 的示例策略。
3. 文档没有一句" BCI 兼容性"的显式说明（规范附录 C 有，README/architecture 没有索引）。

## 实施步骤（离线优先，无需真实硬件）

### P1 — 参考 BCI channel demo + 测试

- 新增 `examples/hlp_bci_channel_demo.py`（对照 `examples/hlp_realtime_promotion_demo.py` 风格）：
  - `SyntheticBCIDecoder`：确定性假解码器，把脚本化"脑电片段"翻译成
    `ControlSignal(source_kind="bci", confidence=…, principal_binding="user_alice",
    interaction=InteractionRef(channel="bci", session_id=…))`。
  - 演示四条路径：
    1. 高置信 soft 流 → 合并晋级为一条 `task.amend`（断言 D1：Task.state 不变；
       audit 含 promotion provenance 且 `source_kind="bci"`）。
    2. 高置信 hard affirm + **低风险** checkpoint → `checkpoint.resolve` 成功。
    3. 高置信 hard affirm + **高风险** checkpoint、无第二因子 →
       `require_hard_resolve_allowed` 抛 `UNAUTHORIZED`（D3 fail-closed）。
    4. 同上 + `second_factor_present=True`（模拟显式 UI 确认）→ resolve 成功。
  - risk 推导示例策略：checkpoint option 的 `risk` 字段含 `"high"` 或 kind
    属于策略表（如 `approval` 且 prompt 命中高风险关键词）→ `high_risk=True`。
- 新增测试（并入 `tests/test_hlp_realtime.py` 或新文件）覆盖上述四条路径 +
  不同 principal 混合合并被拒（现有语义）+ `InteractionRef(channel="bci")` 进 audit。
- demo 注册进 `pyproject.toml [project.scripts]`（如 `loops-hlp-bci-demo`），README demo 列表加一行。

### P2 — 文档与记录

- README（Adapter Depth 或 realtime 段）加 3-5 行"BCI / 脑机接口兼容性"小节：
  指向附录 C 与 demo；明确"协议零改动，BCI 是 channel"。
- `docs/architecture/hlp.md` 的 channel 段补一句 BCI channel 参考切片说明。
- `CHANGELOG.md` [Unreleased] Added 记录。
- 按 AGENTS.md：本计划存档于 `docs/plans/`，完成后写 `docs/notes/` 当日记录并提交。

### P3 —（后续可选，不在本次）

- 真实 BCI SDK（OpenBCI/ Muse 等）的 host 侧解码器接口定义；仍是 channel 代码，不进 `loops/` 核心。
- TUI/host 的 `/bci` 软缓冲视图（复用现有 soft buffer UI）。

## 非目标

- 不在 HLP core 定义 EEG 采样、解码、厂商 schema（C.10 红线）。
- 不改 0.2.0 操作集与状态机；不加第 8 个一等对象。
- 不做实时 SLA 或硬件驱动。

## 验证

- 新增离线测试全绿：`pytest tests/ -q`；demo 离线可运行：`uv run loops-hlp-bci-demo`。
- `ruff check` / `ruff format --check` / `mypy loops` 全清。
- 无需任何真实 BCI 硬件或网络。
