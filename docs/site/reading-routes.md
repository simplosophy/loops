# 实现者阅读路线

> 按你的角色选入口。三份 spec 形态不同，读之前必须分清——否则会误读 Loops 的设计意图。

## 三种文档形态（重要）

本站的三份 spec **形态不同**：

| spec | 文档类型 | 含义 |
|------|---------|------|
| [HACP](./specs/hacp) | **完整协议规范** | Loops 新建的协议。全套自研：schema、状态机、错误码、一致性。实现者照着写代码即可。 |
| [AAP](./specs/aap) | **一致性剖面** | Loops 复用 A2A/ACP。本文档定义"L1 层必须暴露的最小接口契约"，任何满足它的现有实现都能接入，**不重新发明协议**。 |
| [CAP](./specs/cap) | **一致性剖面** | Loops 复用 MCP/Skills。同上。 |

**为什么这样区分？** 因为 Loops 的核心哲学是**"只定义层规范，不重造协议"**。MCP/Skills/A2A 已经是优秀的砖，Loops 给它们一张坐标系和接缝规范，而不是重新烧一遍砖。如果把 AAP/CAP 也写成全套协议规范，就违背了这个哲学。

---

## 路线一：我想实现一个 HACP 服务（人机协作平台）

→ 读 [HACP](./specs/hacp) 全文。这是新建协议，需要完整实现 21 个操作和 7 个一等对象。

**重点章节**：
- §3 对象 Schema —— 7 个一等对象的字段定义
- §3.3 TaskState 状态机 —— 合法转移表
- §4 协议操作 —— 21 个操作的语义和前置条件
- §5 层间契约 —— 与 AAP 的衔接点

**预期工作量**：大。这是一个完整协议，需要实现状态机、持久化、审计。

---

## 路线二：我有一个 MCP server / Skills，想接入 Loops 栈

→ 读 [CAP](./specs/cap)。

**重点章节**：
- §4 参考实现映射 —— 你会发现大概率已经满足 CAP 剖面
- §2.2 CapabilityRef —— 上层引用你的能力的唯一方式
- §3 最小接口契约 —— list / describe / invoke 三个接口

**预期工作量**：极小。任何 MCP server 直接满足 CAP 的 Tool 粒度剖面，几乎零改造。

---

## 路线三：我有一个 A2A runtime，想接入 Loops 栈

→ 读 [AAP](./specs/aap)。

**重点章节**：
- §4 A2A → AAP 映射 —— 对应关系
- §5.1 AAP ↔ HACP —— 关键契约层（务必读）
- §3.3 阻塞与恢复 —— 为对接 HACP Checkpoint 设计

**预期工作量**：小。关键是给 Run 加上 `correlation_id` 字段以贯穿 TaskID，并实现 block/resume 接口。

---

## 路线四：我想搭一个完整的 Loops 栈

→ 三份都读，按 **CAP → AAP → HACP** 的依赖顺序（自底向上）。

三份的层间契约是缝合点：

| 缝合点 | 定义位置 | 铁律 |
|--------|---------|------|
| CapabilityRef | [CAP §2.2](./specs/cap#_2-2-capabilityref-跨层引用对象) | 上层只用 `(id, version)`，禁止感知 transport |
| TaskID 贯穿 | [AAP §5.1](./specs/aap#_5-1-aap-hacp-l1-l2-关键契约) | HACP TaskID **必须** = AAP Run.correlation_id，全栈到底 |
| Checkpoint→Block | HACP §5.1 / AAP §3.3 | checkpoint.raise **必须**触发 agent.block |
| Ownership→Handoff | HACP §3.5 / AAP §3.4 | ownership.transfer **必须**联动 agent.handoff |

速查版见 [层间契约速查](./specs/contracts)。

**预期工作量**：最大。但可以选择：L0 直接用现成 MCP server，L1 直接用 A2A runtime，只需自研 HACP——这恰恰是 Loops 分层的价值。

---

## 一致性验证

实现后，对照各 spec 的"一致性级别"章节自检：

- [CAP §6](./specs/cap#_6-一致性级别) —— 5 条硬指标
- [AAP §6](./specs/aap#_6-一致性级别) —— 5 条硬指标
- [HACP §8](./specs/hacp#_8-一致性级别-conformance) —— 7 条硬指标

所有 spec 当前为 **0.1.0-draft**，开放议题见各 spec §7，待参考实现后收敛。
