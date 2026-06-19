# CAP — Capability Protocol

| | |
|---|---|
| **规范版本** | 0.1.0-draft |
| **状态** | Draft |
| **所属栈** | [Loops Protocol Stack](../plans/2026-06-19-loops-protocol-stack.md) |
| **层级** | L0（栈底层） |
| **文档类型** | **一致性剖面（Conformance Profile）** —— 不是新协议规范 |

---

## 0. 本文档是什么，不是什么

**CAP 不是一份重新发明的协议规范。** 工具/能力调用的事实标准（MCP、Skills 协议）已经成熟。

**CAP 是 Loops 栈对 L0 层定义的"最小接口契约"**：要成为 Loops 栈的合格 L0，一个能力源（capability source）必须暴露什么接口、承担什么一致性责任。任何满足本剖面的现有实现（MCP server、Skills runtime）都可以直接接入 Loops 栈，无需改造。

### 与 HACP 的文档形态差异

| | HACP.md | CAP.md（本文档） |
|---|---|---|
| 性质 | 完整协议规范（新建协议） | 一致性剖面（复用已有协议） |
| 定义 | 协议本身 | 层间接口最小契约 |
| schema | 全套自研 | 引用已有协议 schema |

---

## 1. 摘要

CAP（Capability Protocol）定义 **agent 如何调用一个外部能力**。能力分两种粒度：

| 粒度 | 定义 | 参考实现 |
|------|------|---------|
| **Tool** | 单函数，输入→输出 | MCP tool |
| **Skill** | 打包的复合能力，含 prompt 模板 + 资源 + 权限声明 | Skills 协议 |

### 1.1 CAP 不管辖的事

- 谁是 caller（不区分人/agent）—— 那是 HACP 的事
- 会话与状态 —— 那是 loop1 的事
- 组织与权限模型 —— 那是 loop2 的事
- agent 内部如何编排多个 tool —— 那是 runtime 的事

### 1.2 规范性用语

使用 [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119) 关键字。

---

## 2. 核心概念

### 2.1 Capability（能力）

一个能力是 agent 可调用的最小工作单元。**MUST** 有全局唯一、版本化的标识。

```yaml
Capability:
  capability_id: string       # REQUIRED, 如 "cap:web-search"
  version: string             # REQUIRED, 如 "v2", semver
  kind: "tool" | "skill"      # REQUIRED
  manifest: CapabilityManifest
```

### 2.2 CapabilityRef（跨层引用对象）

这是 CAP 暴露给上层（AAP/HACP）的**唯一合法引用形式**。上层 **MUST** 只通过 CapabilityRef 引用能力，**MUST NOT** 感知底层 transport。

```yaml
CapabilityRef:
  capability_id: string       # 如 "cap:web-search"
  version: string             # 如 "v2"
```

> 此对象在 HACP.md §5.3 和设计稿层间契约中作为唯一的跨层载体。

### 2.3 两种粒度的边界

| 维度 | Tool | Skill |
|------|------|-------|
| 粒度 | 单函数 | 复合（多步骤/多资源） |
| 自带 prompt | 否 | **是**（prompt 模板 + 变量） |
| 自带资源 | 否 | **是**（附件、知识、子 tool） |
| 自带权限声明 | 否 | **是** |
| 调用语义 | `call(input) → output` | `invoke(vars) → result + side-effects` |
| MCP 映射 | MCP tool | 无直接映射（Skills 协议补充） |

**关键约束**：Skill **MUST** 可被降级视为"一组 Tool 的打包 + 一段 prompt 模板"。这保证 CAP 内部两种粒度不产生协议分裂。

---

## 3. 最小接口契约

### 3.1 能力发现（Discovery）

一个合格 L0 **MUST** 提供：

```yaml
capability.list() -> [CapabilityManifest]
capability.describe(capability_id, version) -> CapabilityManifest | NOT_FOUND
```

**CapabilityManifest** 至少包含：

```yaml
CapabilityManifest:
  capability_id: string
  version: string
  kind: "tool" | "skill"
  name: string                 # 人类可读名
  description: string
  input_schema: JSONSchema     # REQUIRED, 输入参数 schema
  output_schema: JSONSchema    # RECOMMENDED
  # kind=skill 时额外：
  prompt_template: string | null      # Skill 的 prompt 模板
  resources: [Resource] | null        # Skill 自带资源
  required_permissions: [string] | null
```

### 3.2 能力调用（Invocation）

```yaml
# Tool 粒度
capability.invoke(ref: CapabilityRef, input: object) -> InvokeResult

InvokeResult:
  ok: boolean
  output: object | null       # 符合 output_schema
  error: CapabilityError | null
  duration_ms: integer
```

**一致性约束**：
- `invoke` **MUST** 是同步语义的契约（实现 **MAY** 异步，但协议承诺同步返回语义）。
- `invoke` **MUST** 校验 `input` 符合 `input_schema`，否则返回 `INVALID_INPUT`。
- `invoke` **MUST** 返回符合 `output_schema` 的 `output`（如 manifest 声明了）。

### 3.3 错误码

| 码 | 语义 |
|----|------|
| `NOT_FOUND` | capability_id/version 不存在 |
| `INVALID_INPUT` | input 不符合 schema |
| `PERMISSION_DENIED` | 缺少 required_permissions |
| `EXECUTION_FAILED` | 能力内部失败 |
| `TIMEOUT` | 调用超时 |

---

## 4. 参考实现映射

CAP 是抽象剖面，已有协议如何映射：

### 4.1 MCP → CAP

| CAP 契约 | MCP 实现 |
|----------|---------|
| `capability.list` | `tools/list` |
| `capability.describe` | `tools/list` + filter |
| `capability.invoke` (tool) | `tools/call` |
| CapabilityManifest.input_schema | MCP tool `inputSchema` |
| transport 透明 | MCP stdio/SSE/HTTP 任选 |

**结论**：任何 MCP server 满足 CAP 的 Tool 粒度剖面，无需改造。

### 4.2 Skills 协议 → CAP

| CAP 契约 | Skills 实现 |
|----------|------------|
| `capability.list` | skill manifest 列表 |
| `capability.invoke` (skill) | skill 触发 |
| prompt_template / resources / permissions | Skills 协议原生字段 |

**结论**：Skills 协议满足 CAP 的 Skill 粒度剖面。

### 4.3 Function Calling（OpenAI 风格）

Function Calling 满足 CAP 的 Tool 粒度，但**不满足发现契约**（无 server-side `list`），需宿主层补全 manifest 注册。

---

## 5. 层间契约

### 5.1 CAP → AAP（L0 → L1）

AAP 层（agent runtime）通过 CapabilityRef 调用 CAP。**禁止**：
- agent 直接感知底层 transport（stdio/SSE）
- agent 直接读 MCP 原始 schema（必须经 manifest 抽象）

### 5.2 CAP → HACP（L0 → L2）

HACP 通过 `Constraints.must_use_capabilities` 引用能力，**只**用 CapabilityRef。HACP **MUST NOT** 直接调 CAP。

---

## 6. 一致性级别

声称"符合 CAP 0.1.0-draft"的实现 **MUST**：

1. 提供 `capability.list` / `describe` / `invoke` 三个接口
2. 每个 capability 有 `(capability_id, version)` 全局唯一标识
3. manifest 包含 input_schema
4. invoke 返回符合契约的 InvokeResult
5. 通过 §3.3 的错误码语义

实现 **MAY**：
- 只支持 Tool 粒度（纯 MCP server）或只支持 Skill 粒度
- 选择任意 transport
- 扩展 manifest 的自定义字段

---

## 7. 开放议题

| # | 议题 | 倾向 |
|---|------|------|
| 1 | Capability 版本兼容（v2 调用方能否 fallback 到 v1） | semver + 向后兼容声明 |
| 2 | 长任务（>30s）能力 | MAY 异步，但需定义进度协议 |
| 3 | 能力的副作用声明 | manifest 加 `side_effects: read-only \| stateful` |
| 4 | Skill 的权限声明具体 schema | 待 Skills 协议演进后对齐 |

---

## 附录：变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.1.0-draft | 2026-06-19 | 首个 draft，定义 L0 最小接口剖面，映射 MCP/Skills 参考实现 |
