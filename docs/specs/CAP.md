# L0 Capability Protocol Routes

> 本文不是新的 Capability 协议规范。它是 HLP 如何引用既有能力生态的路由说明。

## 1. 定位

HLP 不直接调用工具，也不定义工具协议。agent 调用能力这件事应该继续交给已有 L0 生态：

- MCP servers
- Agent Skills / Skills runtime
- local tools
- function calling registries

HLP 只需要在 Task 约束和 Artifact provenance 中引用能力，而不是感知 transport 或 invocation 细节。

---

## 2. HLP 对 L0 的最小期望

| HLP 需求 | L0 capability route 需要做到 |
|----------|------------------------------|
| 稳定引用 | 每个可被 HLP Task 约束引用的能力都有 `(capability_id, version)`。 |
| 隐藏 transport | HLP 不应知道 stdio/SSE/HTTP/local function name/credential。 |
| 可解释 | 能力 manifest 或 schema 足够让人理解 Task 为什么要求它。 |
| provenance | Artifact / Audit 可以记录实际使用了哪个 capability。 |
| 错误可追踪 | invocation 失败能通过 agent harness 或 host platform 形成结构化证据。 |

HLP 使用的边界对象是：

```yaml
CapabilityRef:
  capability_id: string
  version: string
```

---

## 3. 既有协议路由

| 路由 | 适用场景 | HLP adapter 重点 |
|------|----------|------------------|
| MCP | 工具通过 MCP server 暴露 | 将 MCP tool 映射为稳定 CapabilityRef，transport 留在 host/agent 层。 |
| Agent Skills | 能力以 Skill 包形式发布 | Skill 包和版本成为 capability identity，资源/权限进入 provenance。 |
| local tools | 平台本地执行 CLI 或 in-process tool | 建 registry/manifest，禁止 HLP Task 直接保存命令行。 |
| function calling | 能力来自模型 provider 的 function schema | 宿主侧补 discovery 和 stable id 后再给 HLP 引用。 |

---

## 4. 正确调用路径

```text
HLP Task.constraints.must_use_capabilities
  -> L1 agent harness
  -> L0 capability route
  -> MCP tool / Skill / local function
```

HLP 记录意图和证据；agent harness 或 host platform 决定如何调用、重试、鉴权和翻译 provider-specific error。

---

## 5. 不归 HLP 管

- MCP transport
- Skill package format
- function-calling provider schema
- tool authentication
- sandbox policy
- retry / timeout / rate limit 行为

这些属于既有 L0 生态或宿主平台。
