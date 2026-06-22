# Loops Protocol Stack — Specifications

> AI 协作的 OSI 模型：三层协议、每层只解一个维度、层间靠显式契约咬合。

本目录包含 Loops Protocol Stack 三层协议的完整规范。Loops 不是又一个 AI 框架——它是一套**协议栈规范**，把已有的、各自优秀的协议（MCP、Skills、A2A、ACP）分层归位，定义它们之间的边界契约，并填补生态中缺失的人机责任闭环层。

---

## 1. 为什么是协议栈

今天几乎每一个 AI 应用都是一根**烟囱**：执行、交互、协同被垂直打包进一个单体，模型按周迭代、渠道按季度增减、治理按年演进，却被揉进同一份代码。换一层就要动另外两层。

Loops 的主张：**把 AI 协作拆成三个正交的协议层**，每层只管一件事，层间只通过显式契约对话。已有协议是各层的"砖"，Loops 是"建筑规范"——规定砖怎么垒、每层用什么砖、哪一层还缺砖。

核心贡献是**填补了缺失的 L2**：MCP 解决了 agent↔工具，A2A 解决了 agent↔agent，但 agent↔人 在项目/组织级如何协作，至今是生态空白。HLP 就是来补这一格的。

---

## 2. 栈全景

```text
┌──────────────────────────────────────────────────────────────┐
│                     人 (principal)                            │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           │  HLP  (L2 · 人机责任闭环) ★ Loops 新建
                           │  Task / Checkpoint / Ownership / Review
                           │  Artifact / Ledger / Audit
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                     agent (worker)                            │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           │  AAP  (L1 · agent 间)
                           │  delegate / handoff / discovery
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                     能力 (capability)                         │
└──────────────────────────────────────────────────────────────┘
                           ▲
                           │  CAP  (L0 · 能力)
                           │  tool.call / skill.invoke
```

| 层 | 协议 | 全称 | 性质 | 规范 |
|----|------|------|------|------|
| **L2** | **HLP** | Human Loop Protocol | Loops **新建** | [HLP.md](./HLP.md) |
| **L1** | **AAP** | Agent-Agent Protocol | 复用 A2A/ACP | [AAP.md](./AAP.md) |
| **L0** | **CAP** | Capability Protocol | 复用 MCP/Skills | [CAP.md](./CAP.md) |

---

## 3. 三种文档形态（重要）

本目录的三份 spec **形态不同**——读之前必须分清，否则会误读 Loops 的设计意图：

| spec | 文档类型 | 含义 |
|------|---------|------|
| **HLP.md** | **完整协议规范** | Loops 新建的协议。全套自研：schema、状态机、错误码、一致性。实现者照着写代码即可。 |
| **AAP.md** | **一致性剖面（Conformance Profile）** | Loops 复用 A2A/ACP。本文档定义"L1 层必须暴露的最小接口契约"，任何满足它的现有实现都能接入，**不重新发明协议**。 |
| **CAP.md** | **一致性剖面（Conformance Profile）** | Loops 复用 MCP/Skills。同上。 |

**为什么这样区分？** 因为 Loops 的核心哲学是**"只定义层规范，不重造协议"**。MCP/Skills/A2A 已经是优秀的砖，Loops 给它们一张坐标系和接缝规范，而不是重新烧一遍砖。如果把 AAP/CAP 也写成全套协议规范，就违背了这个哲学。

---

## 4. 实现者阅读路线

按角色选入口：

### 我想实现一个 HLP 服务（Human Loop 平台）
→ 读 [HLP.md](./HLP.md) 全文。这是新建协议，需要完整实现 21 个操作和 7 个一等对象。重点看 §3（schema）、§4（操作）、§5（层间契约）。

### 我有一个 MCP server / Skills，想接入 Loops 栈
→ 读 [CAP.md](./CAP.md)。重点看 §4（参考实现映射）——你会发现自己的实现大概率已经满足 CAP 剖面，几乎零改造。

### 我有一个 A2A runtime，想接入 Loops 栈
→ 读 [AAP.md](./AAP.md)。重点看 §4（A2A→AAP 映射）和 §5.1（HLP↔AAP 联动）——关键是给 Run 加上 `correlation_id` 字段以贯穿 TaskID。

### 我想搭一个完整的 Loops 栈
→ 三份都读，按 **CAP → AAP → HLP** 的依赖顺序（自底向上）。三份的层间契约是缝合点：
- CAP.md §5 定义 CapabilityRef（唯一跨 L0→L1→L2 的能力引用）
- AAP.md §5.1 定义 TaskID 贯穿（HLP↔AAP 的铁律）
- HLP.md §5 定义 Task→AAP delegate / Checkpoint→AAP block

---

## 5. 层间契约速查

这是整个栈的缝合点，实现者最容易出错的地方。三份 spec 在这些契约上必须保持一致：

| 契约 | 跨层对象 | 定义位置 | 铁律 |
|------|---------|---------|------|
| **CapabilityRef** | 能力引用 | CAP §2.2 / HLP §5.3 | 上层只用 `(id, version)`，禁止感知 transport |
| **TaskID 贯穿** | Task↔Run | AAP §5.1 | HLP TaskID **必须** = AAP Run.correlation_id，全栈到底 |
| **Checkpoint→Block** | 决策点→阻塞 | HLP §5.1 / AAP §3.3 | checkpoint.raise **必须**触发 agent.block，resolve **必须**触发 resume |
| **Ownership→Handoff** | 所有权→交接 | HLP §3.5 / AAP §3.4 | ownership.transfer **必须**联动 agent.handoff，correlation 保持 |

---

## 6. 关键设计决策（为什么是这些选择）

以下决策都在设计稿 [`docs/plans/2026-06-19-loops-protocol-stack.md`](../plans/2026-06-19-loops-protocol-stack.md) 里有完整推演。这里只列结论：

| 决策 | 选择 | 一句话理由 |
|------|------|-----------|
| 分几层 | **3 层** | MCP 和 Skills 在协议层无本质差异，合并成 CAP 更干净 |
| L2 主语 | **Task 为一等公民** | 人天然用"一件事一件事"组织工作，不是"一次 agent run" |
| A+B 合并 | **双向控制平面** | 下行 task.assign + 上行 checkpoint.raise 共享单一状态机 |
| 状态沉淀 | **Ledger（非 Memory）** | 避免被误读为 agent 对话记忆/RAG；强调组织账本语义 |
| 不可变性 | **全协议只前进** | 无 update/delete，Task spec / Artifact / Ledger / Review / Audit 都不可变 |

---

## 7. 一致性与版本

- 三份 spec 当前均为 **0.1.0-draft**，等待参考实现验证。
- 每份 spec 的最后一节（§8 或 §6）定义了"声称符合该版本"必须满足的硬指标。
- 开放议题（每份 spec 的 §7）在参考实现后逐一收敛。
- 版本兼容规则见 HLP §7.7——目前承诺语义版本 + 向后兼容。

---

## 8. 相关文档

| 文档 | 作用 |
|------|------|
| [`docs/plans/2026-06-19-loops-protocol-stack.md`](../plans/2026-06-19-loops-protocol-stack.md) | 设计稿——完整决策推演（为什么是这些选择） |
| [`docs/architecture/LOOPS_STACK.md`](../architecture/LOOPS_STACK.md) | 架构定位——loops 从软件到协议栈的演进 |
| [`docs/intro.html`](../intro.html) | 对外宣传页——面向生态的图文介绍 |

**关系**：设计稿讲来龙去脉，本目录的 spec 是实现契约，架构文档给坐标，宣传页给叙事。
