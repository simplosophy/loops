# 层间契约速查

> 这是整个栈的缝合点——实现者最容易出错的地方。
> 三份 spec 在这些契约上必须保持一致。

## 四个跨层契约

| 契约 | 跨层对象 | 定义位置 | 铁律 |
|------|---------|---------|------|
| **CapabilityRef** | 能力引用 | [CAP §2.2](./cap#_2-2-capabilityref-跨层引用对象) / [HACP §5.3] | 上层只用 `(id, version)`，**禁止**感知 transport（stdio/SSE/HTTP） |
| **TaskID 贯穿** | Task↔Run | [AAP §5.1](./aap#_5-1-aap-hacp-l1-l2-关键契约) | HACP TaskID **必须** = AAP Run.correlation_id，全栈到底 |
| **Checkpoint→Block** | 决策点→阻塞 | [HACP §5.1] / [AAP §3.3](./aap#_3-3-阻塞与恢复-block-resume) | checkpoint.raise **必须**触发 agent.block，resolve **必须**触发 resume |
| **Ownership→Handoff** | 所有权→交接 | [HACP §3.5] / [AAP §3.4](./aap#_3-4-交接-handoff) | ownership.transfer **必须**联动 agent.handoff，correlation 保持 |

## 契约一：CapabilityRef

上层（AAP / HACP）引用能力时，**只**用 CapabilityRef，**绝不**感知底层 transport（MCP stdio/SSE、Skills runtime）。

```yaml
CapabilityRef:
  capability_id: string        # 如 "cap:web-search"
  version: string              # 如 "v2"
```

- L0 (CAP) 是 CapabilityRef 的出生层
- L1 (AAP) 通过它调用能力，转发给底层
- L2 (HACP) 通过 `Constraints.must_use_capabilities` 引用，**不直接调 CAP**

## 契约二：TaskID 贯穿（关键）

这是 Loops 栈最关键的层间缝合点。HACP 的 Task 生命周期依赖 AAP 的 Run：

| HACP 操作 | AAP 联动 | correlation 约束 |
|----------|---------|-----------------|
| `task.assign` | `agent.delegate` | TaskID **必须** = Run.correlation_id |
| `checkpoint.raise` | `agent.block` | CheckpointID **必须** 传入 |
| `checkpoint.resolve` | `agent.resume` | resolution **必须** 透传 |
| `ownership.delegate` | `agent.delegate`（子 agent） | parent_run 可追 |
| `ownership.transfer` (handoff) | `agent.handoff` | correlation_id 保持 |

**铁律**：TaskID **必须**全栈贯穿到最底层 Run。任何丢失 correlation 的实现都不符合 AAP。

## 契约三：Checkpoint → Block

HACP 的上行把关机制，通过 AAP 的 block/resume 接口落地：

```text
agent 执行中 → 发现关键决策点
  → HACP: checkpoint.raise  (Task → blocked)
  → AAP:  agent.block        (Run → blocked)
  ↓
人决策 (approve/reject/choose/...)
  → HACP: checkpoint.resolve (Task → in_progress)
  → AAP:  agent.resume       (Run → running)
```

- `block` **必须**带 checkpoint_id，关联到 HACP 的 Checkpoint
- blocked 期间 agent **必须不**自行恢复，**必须**等待 `resume`

## 契约四：Ownership → Handoff

HACP 的所有权转移在 AAP 层的体现：

- HACP `ownership.transfer`（assignee 换人/换 agent）
- 联动 AAP `agent.handoff`
- handoff **必须**保留原 correlation_id（同一 Task 不变）
- 旧 Run 失效，新 Run 产出，correlation 全程贯穿

---

## 跨层通信规则

所有层间通信 **必须** 通过上述契约对象，**禁止**直接读写邻层内部状态。

- **L2 → L1**：通过 TaskID（贯穿）、Checkpoint 事件
- **L1 → L0**：通过 CapabilityRef
- **L2 → channel (loop1)**：HACP 只产出事件，channel 负责送达（IM 推送、Web 更新等）——通知机制不在 HACP 范围

## 依赖方向

```text
L2 (HACP) ──→ L1 (AAP) ──→ L0 (CAP)
   可调下层        可调下层
   不可被下层感知   不可被下层感知
```

**反向禁止**：L0 永远不知道 L1/L2 存在；L1 永远不知道 L2 存在。这是"换一层不动另外两层"的物理保证。
