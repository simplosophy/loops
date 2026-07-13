# HLP Realtime Control Plane（草案）

| | |
|---|---|
| **日期** | 2026-07-13 |
| **状态** | 讨论稿 / 规范草案（无改参考实现 core） |
| **关联** | `docs/specs/HLP.md` 附录 C；`docs/architecture/OVERVIEW.md` |
| **动机** | 在保持 modality-agnostic 责任闭环的同时，兼容准实时双工对话、多模态与未来 BCI 意图输入 |

## 1. 问题

HLP 0.2.0 已有连续控制（`task.amend` / `task.interrupt` / grants），但语义仍以**离散**
checkpoint 与**离散** amendment 为主。未来交互会变成：

- 人与 AI **几乎同时**说话（voice duplex / OpenAI Realtime 类）
- 高频软纠偏（“嗯”“往左一点”）
- 传感器化意图（BCI 等）——置信度不完美，不能直接当 principal

若把帧/音频/脑电写进一等对象，HLP 会变成媒体协议，失去责任闭环定位。

## 2. 原则

1. **三层时间尺度**  
   - Channel/Sensor：高频、可丢  
   - HLP responsibility：低频、append-only、可重放  
   - Harness execution：模型/工具/loop  

2. **晋级（promotion）**  
   Channel 上的现象只有满足规则才变成 HLP 责任事件。

3. **Soft vs Hard control**  
   - Soft：不必然 block Task；可合并为 steering  
   - Hard：必须 checkpoint / interrupt  

4. **Principal 是人，通道是传感器**  
   BCI/语音只是意图输入装置；必须能绑定到 `user_*`。

5. **Profile 化**  
   `HLP-batch` / `HLP-continuous`（≈0.2.0）/ `HLP-realtime`（草案）——不强迫所有实现支持实时。

## 3. Soft / Hard Control

| | Hard | Soft |
|---|------|------|
| 状态机 | 通常 → `blocked` | 可保持 `in_progress` |
| 例子 | 推生产、删库、转账 | 语气、局部纠偏、口头偏好 |
| 现有映射 | Checkpoint / `task.interrupt` | `task.amend` / `steering_log` |
| 缺口 | 过重 | 合并、过期、置信度、与 grant 关系 |

### 3.1 值对象草案：`ControlSignal`（非一等对象）

```yaml
ControlSignal:
  strength: "soft" | "hard"
  intent: "redirect" | "clarify" | "constrain" | "halt" | "resume" | "affirm" | "deny"
  confidence: number            # 0..1；文本 UI 可恒为 1.0
  source_kind: "speech" | "text" | "ui" | "bci" | "other"
  source_ref: string | null     # opaque channel/frame id；HLP 不解析
  principal_binding: user_      # MUST 绑定到人
  effective_at: timestamp       # 意图生效时间（可早于 recorded_at）
  recorded_at: timestamp
  effective_window: [timestamp, timestamp] | null
  promotion: "none" | "steering" | "checkpoint" | "grant_check"
  run_id: string | null         # 因果绑定到 harness run
```

### 3.2 规则（草案 MUST/SHOULD）

1. Soft **MUST NOT** 仅因 `confidence < θ` 触发 hard 效果（θ 由 realtime profile 声明）。  
2. Soft 默认 **MUST NOT** 改变 `Task.state`；**MAY** 聚合成一条 `SteeringAmendment`。  
3. Hard **MUST** 走 `checkpoint.raise` / `task.interrupt` 或等价 hard resolve。  
4. 与 `PermissionGrant` 冲突时 **deny 优先**（与 0.2.0 一致）。  
5. Audit **MUST** 记录 promotion 路径（signal → steering/checkpoint/resolve）。  
6. 高风险 hard resolve：realtime profile **SHOULD** 允许要求双通道确认
   （例如 BCI + 显式口令）；默认 **BCI 不得单独** 关闭高风险 checkpoint。

## 4. 晋级（Promotion）示例

| Channel 现象 | 晋级？ | HLP 结果 |
|--------------|--------|----------|
| “嗯嗯” | 否 | — |
| “停，别推代码” | 是 | interrupt / hard checkpoint |
| 3 秒内多次“再往左” | 合并后是 | **一条** `task.amend` |
| BCI “同意” 0.62 | 否 | 等待二次确认 |
| BCI “同意” 0.95 + grant 匹配 + profile 允许 | 可 | soft affirm 或 grant_check 跳过低风险动作 |
| Token / 音频帧流 | 否 | channel/harness only；里程碑才 `artifact.commit` |

## 5. InteractionRef（opaque）

**不** 引入 Session 一等对象。Audit / Amendment / Checkpoint **MAY** 携带：

```yaml
InteractionRef:
  channel: string       # "voice" | "tui" | "bci" | ...
  session_id: string    # opaque
  episode_id: string | null
```

Host 用它对齐实时时间线；HLP 主语仍是 Task。

## 6. 并发合流（收口 §7.4 的 checkpoint 部分）

Realtime profile 实现 **MUST** 声明其一：

1. **Serialize**：同一 Task 同时至多一个 hard pending checkpoint  
2. **Scope-partition**：不同 `permission_scope` 可并行 hard pending  
3. **Priority stack**：hard > soft；新 soft 可 supersede 旧 soft 的*生效视图*（底层仍 append-only）

## 7. Artifact：ephemeral vs sealed

- Channel/harness **MAY** 持有 ephemeral working copy（HLP 不存帧）。  
- HLP Artifact 仍不可变 + 版本链；仅里程碑 `artifact.commit`。  
- Review **MUST** 针对 sealed 版本。

## 8. Profiles

| Profile | 含义 |
|---------|------|
| `HLP-batch` | 强 checkpoint 审批台 |
| `HLP-continuous` | 0.2.0 连续控制（amend/interrupt/grants） |
| `HLP-industrial` | 已有 CAS/outbox/schema 等 |
| `HLP-realtime` | Soft/Hard + promotion + 合流策略 + intent provenance（草案） |

`HLP-realtime` **≠** 媒体实时保证；只保证责任语义在高频交互下仍可审计。

## 9. 非目标

- AudioFrame / EEGSample / TokenDelta 一等对象  
- SFU / 编解码 / 厂商 Realtime API 绑定  
- 可编辑历史消息（破坏 forward-only）  
- Soft 直接等于 Review.approve  
- 0.3 引入“观察者/教练”新角色（先用 audit 订阅）

## 10. 映射：Realtime 双工

```text
User audio + Agent audio → channel session (not HLP)
        → promotion
        → soft → (merge) → task.amend → AgentAdapter.steer
        → hard → interrupt/checkpoint → block/resume
        → deliverable → artifact.commit → review
```

## 11. 开放问题（待拍板）

1. Soft 是否进入状态机？**建议否。**  
2. 合并窗口：HLP 只收合并结果 vs 规范时间窗？**建议 HLP 收结果，策略在 profile。**  
3. BCI 单独 hard resolve？**建议默认 never。**  
4. 多 agent 实时是否引入责任图？**建议否；子 Task + ownership。**

## 12. 落地顺序

| 阶段 | 动作 |
|------|------|
| 本提交 | 本计划 + `HLP.md` 附录 C + OVERVIEW 指针 |
| 0.3-discussion | 收敛开放问题；conformance 表增加 realtime 可选声明 |
| 0.3-reference | 可选 `ControlSignal` 值对象 + audit provenance；**不**强制改状态机 |
| 实验 | optional channel adapter（mock BCI / voice）只做 promotion 演示 |

## 13. 不做什么

本阶段 **不** 修改 `loops/hlp/operations.py` 状态机，**不** 上线 voice/BCI 实现。
