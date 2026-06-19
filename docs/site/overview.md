# 为什么是协议栈

> 今天几乎每一个 AI 应用都是一根**烟囱**：执行、交互、协同被垂直打包进一个单体。
> 模型按周迭代、渠道按季度增减、治理按年演进，却被揉进同一份代码。换一层就要动另外两层。

## 问题：烟囱式的 AI 应用

当你要换一个模型 provider，却发现改了 runtime 还要碰 channel 代码；要加一个飞书渠道，却发现协作逻辑里藏着 provider 特判——这就是烟囱的代价。功能齐全，但谁都不敢拆。

这不是工程能力问题，是**分层问题**。AI 应用其实同时包含三种节奏完全不同的事物，硬塞进一个项目，就是耦合的根源。

## 主张：三个协议层各管一件事

Loops 把 AI 协作拆成三个正交的协议层，每层只管一件事，层间只通过显式契约对话。

已有协议是各层的"砖"，Loops 是"建筑规范"——规定砖怎么垒、每层用什么砖、哪一层还缺砖。

| 层 | 协议 | 解决什么 | 来源 |
|----|------|---------|------|
| **L2** | [HACP](./specs/hacp) | agent ↔ 人 在项目/组织级协作 | Loops **新建** ★ |
| **L1** | [AAP](./specs/aap) | agent ↔ agent 发现/委派/交接 | 复用 A2A / ACP |
| **L0** | [CAP](./specs/cap) | agent ↔ 工具/能力调用 | 复用 MCP / Skills |

## 核心贡献：填补缺失的 L2

MCP 解决了 agent↔工具，A2A 解决了 agent↔agent，但 **agent↔人 在项目/组织级如何协作，至今是生态空白**。

人如何把一个有边界的工作单元（Task）交给 agent？agent 做到关键决策点如何把球踢回给人？产物如何交付、评审、版本化？组织级的经验如何沉淀？这些都没有协议级的答案。

HACP 就是来补这一格的——它定义了 Task / Checkpoint / Ownership / Review / Artifact / Ledger / Audit 七个一等对象，21 个协议操作。

## 三条不可妥协的纪律

这三层能成立，靠的不是口号，是几条硬纪律：

- **依赖只能向下**：L2 → L1 → L0。低层永远不能 import 或感知高层。执行内核不该知道用户是谁，更不该知道组织。
- **跨层只走显式契约**：CapabilityRef、TaskID 贯穿、Checkpoint→Block、Ownership→Handoff。绝不直接修改对方内部对象。
- **只前进、可回溯**：Task spec、Artifact、Ledger、Review、Audit 全部不可变。要改就新建版本，不就地修改。

详细的层间契约见 [层间契约速查](./specs/contracts)。

## 关键设计决策

| 决策 | 选择 | 一句话理由 |
|------|------|-----------|
| 分几层 | **3 层** | MCP 和 Skills 在协议层无本质差异，合并成 CAP 更干净 |
| L2 主语 | **Task 为一等公民** | 人天然用"一件事一件事"组织工作，不是"一次 agent run" |
| 委派 + 审批 | **双向控制平面** | 下行 task.assign + 上行 checkpoint.raise 共享单一状态机 |
| 组织状态沉淀 | **Ledger（非 Memory）** | 避免被误读为 agent 对话记忆 / RAG；强调组织账本语义 |
| 不可变性 | **全协议只前进** | 无 update/delete，保证可重放、可审计 |

完整的决策推演见[设计稿](https://github.com/)（`docs/plans/2026-06-19-loops-protocol-stack.md`）。

---

下一步：选择你的 [阅读路线 →](./reading-routes)
