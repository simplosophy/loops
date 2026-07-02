# L1 Agent Protocol Routes

> 本文不是新的 Agent-Agent 协议规范。它是 HLP 接入既有 agent 协议和 harness 的路由说明。

## 1. 定位

HLP 只定义人机责任闭环。agent 间如何发现、委派、调度、执行，应该继续交给已有 L1 生态和 harness：

- A2A 风格 runtime / harness
- ACP 风格 broker
- AGNTCY 风格 mesh / registry
- 平台已有 agent harness

本文只说明：一个 HLP 实现接入这些 harness 时，边界上必须保留哪些语义。

---

## 2. HLP 对 L1 的最小期望

| HLP 需求 | L1 harness / adapter 需要做到 |
|----------|------------------------------|
| `task.assign` | 启动一个异步 agent run，并立刻返回 run handle。 |
| TaskID 贯穿 | HLP `Task.id` 必须成为 run correlation id，并出现在所有 run event 中。 |
| `checkpoint.raise` | 阻塞对应 run，等待人或授权系统 resolve。 |
| `checkpoint.resolve` | 把 resolution payload 传回 run 并恢复执行。 |
| `ownership.transfer` | 如果执行权转移到另一个 agent，harness handoff 必须保留原 TaskID。 |
| 审计回放 | run event 必须能被 HLP audit 用 TaskID 串起来。 |
| human event 投影 | approval / choice / input / artifact 事件必须能投影为 HLP 对象。 |

这些是 adapter 契约，不是新的 wire protocol。

---

## 3. 既有协议路由

| 路由 | 适用场景 | HLP adapter 重点 |
|------|----------|------------------|
| A2A 风格 runtime / harness | agent card / task / status update 已存在 | 把 HLP `Task.id` 放入 task metadata 或 extension field。 |
| ACP 风格 broker | agent 通过 broker 或 session channel 通信 | TaskID correlation 必须独立于 session-local id。 |
| AGNTCY 风格 mesh | agent 通过 mesh / registry 发现和路由 | mesh 负责发现与路由，HLP 只保留 ownership 和 correlation。 |
| 既有 harness | 平台自己调度 agent | 暴露 delegate / block / resume / steer / handoff / observe 这几个 adapter 能力即可（steer 对应 task.amend 方向修正）。 |

---

## 4. 推荐 Adapter 形状

```text
delegate(task_id, assignee, payload) -> run_id
block(task_id, checkpoint_id) -> void
resume(task_id, checkpoint_id, resolution) -> void
handoff(task_id, from_assignee, to_assignee, context) -> run_id
observe(run_id) -> human-facing harness events
```

参考实现的公开边界是 `AgentAdapter`。HLP 不定义新的独立 L1 协议，也不保留历史 AAP 兼容 API。

---

## 5. 不归 HLP 管

- agent card schema
- broker topology
- agent authentication
- placement / scheduling policy
- multi-agent planning strategy
- agent 内部 run state
- prompt、memory、tool trace、planner state 等 harness 内部细节

这些属于既有 L1 生态或宿主平台。
