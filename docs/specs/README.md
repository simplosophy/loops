# Human Loop Protocol — Specifications

> HLP 是本项目的核心协议和 SDK；L1 / L0 只作为接入既有 agent harness 与 capability 生态的路由说明。

本目录包含 HLP 的完整规范，以及 HLP 如何向下接入已有协议栈的说明文档。

---

## 1. 项目定位

Loops 当前聚焦 **Human Loop Protocol (HLP)**：定义人和自主 agent harness 围绕一个有边界的 Task 如何完成委派、把关、评审、交付、状态沉淀和审计。

已有生态已经覆盖两类能力：

- agent ↔ agent：A2A、ACP、AGNTCY 风格 mesh、各类已有 agent harness
- agent ↔ 工具/能力：MCP、Agent Skills、local tools、function calling registry

因此本项目不再把 L1/L0 作为自定义协议重点推进。它们在本文档中只承担**路由说明**职责：告诉 HLP 实现者应该如何把 TaskID、Checkpoint、Ownership、CapabilityRef 映射到既有协议。

---

## 2. 文档类型

| 文档 | 类型 | 作用 |
|------|------|------|
| [HLP.md](./HLP.md) | **完整协议规范** | 本项目定义的核心协议。包含对象、状态机、操作、错误码、一致性要求。 |
| [AAP.md](./AAP.md) | **L1 路由说明** | 说明 HLP 如何接入 A2A、ACP、AGNTCY 风格 mesh 或已有 agent harness。不是新协议规范。 |
| [CAP.md](./CAP.md) | **L0 路由说明** | 说明 HLP 如何通过 CapabilityRef 引用 MCP、Agent Skills、local tools 或 function calling registry。不是新协议规范。 |

---

## 3. 推荐阅读路线

### 我要实现 Human Loop 平台

读 [HLP.md](./HLP.md) 全文。这是唯一需要完整实现的协议面。重点看：

- §2 核心概念
- §3 对象 Schema
- §4 操作语义
- §5 集成契约
- §8 一致性要求

### 我要把现有 agent harness 接到 HLP

读 [AAP.md](./AAP.md)。重点确认：

- HLP `Task.id` 如何进入 run correlation
- checkpoint 如何阻塞 / 恢复 run
- ownership transfer 如何映射到 harness handoff
- harness 事件如何投影为 HLP checkpoint / artifact 并保留审计所需的 task correlation

### 我要把工具、MCP server 或 Skill 接到 HLP

读 [CAP.md](./CAP.md)。重点确认：

- capability 如何获得稳定 `(capability_id, version)`
- HLP Task 里如何只保存 CapabilityRef，不暴露 transport
- artifact provenance / audit 如何记录 capability 使用证据

---

## 4. 集成契约速查

| 契约 | 跨边界对象 | 铁律 |
|------|------------|------|
| **TaskID 贯穿** | Task ↔ Run | HLP `Task.id` 必须贯穿到 agent run correlation，全程不丢。 |
| **Checkpoint→Block** | Checkpoint ↔ Run | `checkpoint.raise` 必须阻塞对应 run，`checkpoint.resolve` 才能恢复。 |
| **HarnessEvent→HLP** | Harness event ↔ HLP object | 人工审批、输入、选择和 artifact 事件必须可投影为 HLP 对象。 |
| **Ownership→Handoff** | Ownership ↔ Run | ownership 转移到新 agent 时，harness handoff 必须保持原 TaskID。 |
| **CapabilityRef** | Capability 引用 | HLP 只引用 `(capability_id, version)`，不得感知 stdio/SSE/HTTP/function name。 |

---

## 5. 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 项目核心 | **HLP** | 生态缺的是人机责任闭环，不是又一个 agent/tool 协议。 |
| L1/L0 处理方式 | **路由到已有协议** | A2A/MCP/Skills 等已经存在，应复用而不是重造。 |
| HLP 主语 | **Task** | 人天然用“一件事”组织工作，而不是直接管理一次 agent run。 |
| 状态沉淀 | **Ledger** | 强调组织账本语义，避免被误读为 agent memory。 |
| 不可变性 | **全协议只前进** | Task spec / Artifact / Ledger / Review / Audit 都可重放、可审计。 |

---

## 6. 相关文档

| 文档 | 作用 |
|------|------|
| [`docs/architecture/LOOPS_STACK.md`](../architecture/LOOPS_STACK.md) | 架构定位：HLP 为核心，L1/L0 为集成路由 |
| [`docs/architecture/loop2.md`](../architecture/loop2.md) | HLP 参考实现架构 |
| [`docs/plans/2026-06-22-hlp-first-site-positioning.md`](../plans/2026-06-22-hlp-first-site-positioning.md) | 本次 HLP-first 定位调整计划 |
