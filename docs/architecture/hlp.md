# HLP Reference Implementation Architecture

> HLP（Human Loop Protocol）参考实现。
> 对应规范：[`docs/specs/HLP.md`](../specs/HLP.md)
> 定位调整：[`docs/plans/2026-06-22-hlp-first-site-positioning.md`](../plans/2026-06-22-hlp-first-site-positioning.md)

## 定位

`loops.hlp` 是 Human Loop Protocol (HLP) 当前的参考实现目录。它定义
**人**与**自主 agent harness** 如何围绕一个有边界的工作单元（Task）进行
委派、把关、交付与治理。

HLP 不提供自研 agent harness，也不与 MCP / Agent Skills（agent↔工具）
或 A2A / ACP / AGNTCY（agent↔agent）竞争。它补的是这些生态未覆盖的维度：
**agent 与其负责人之间的责任闭环语义**。L1/L0 由既有协议和 runtime 承担，
HLP 只通过 adapter 契约接入。

## owns human interaction semantics

HLP owns human interaction semantics：负责一次 harness 运行中哪些事项需要人
负责、决策、验收和审计。组织模型、调度平台、UI channel、agent execution loop
都留给 host application 或既有 harness。

## 包结构

```text
loops/hlp/
  __init__.py          # 公开 API re-export
  host.py              # application embedding host
  _ids.py              # ULID + 前缀生成器 (spec §3.1)
  types.py             # ProtocolError + Literal 类型别名
  objects.py           # 7 个一等对象 dataclass
  state_machine.py     # Task 状态机：合法转移表 + 校验
  store.py             # HumanLoopStore：内存存储
  sqlite_store.py      # SQLiteHumanLoopStore：本地 snapshot store（非生产并发后端）
  sdk.py               # HLPClient：稳定 SDK facade
  adapters/            # AgentAdapter + HarnessAdapter 包
    protocol.py        # 契约与 handle / harness event
    fake.py            # testing adapters
    process.py         # process / prompt CLI base
    codex.py           # Codex CLI + harness projection
    cli.py             # Pi / Claude / Kimi CLI + harness, Hermes
    frameworks.py      # shape-compatible framework shims
  events.py            # HLPEvent + InMemoryEventBus
  operations/          # 23 个操作 (spec §4)，按域 mixin 包
  audit.py             # AuditEvent + AuditLog (append-only)
```

## 7 个一等对象

| 对象 | 作用 | 可变性 |
|------|------|--------|
| Task | 协议主语，人交给 agent 的工作单元 | 可变（state/ownership 流转），spec 不可变 |
| Checkpoint | 上行把关，agent 声明的决策点 | 可变（state: pending→resolved） |
| Ownership | 可转移凭证，assignee 流转 | 可变（chain append-only） |
| Review | 人对 Artifact 的结构化反馈 | 提交后封印（frozen 语义） |
| Artifact | Task 的交付物，独立生命周期 | 创建后封印，版本递进 |
| Ledger | 组织级状态沉淀 | append-only |
| Audit | 不可变操作日志 | 永不删改 |

## 状态机（spec §3.3）

```text
created → assigned → in_progress → blocked → (resolve) → in_progress
                │              │ │
                │              │ │ task.interrupt (人发起)
                │              │ └──────▶ blocked
                │              ▼
                │         review_ready → under_review → accepted → completed
                │                          │   │
                │                          │   └─ (changes / plan approved) → in_progress
                │                          └─ rejected (终态)
```

合法转移由 `LEGAL_TRANSITIONS` 表显式定义，非法转移抛 `ProtocolError("PRECONDITION_FAILED")`。
新增连续控制转移：`task.interrupt`（人发起，`in_progress→blocked`，系统 raise
`kind=interrupt` checkpoint）与 `under_review→in_progress`（plan approved）。
`task.amend` 不改 state，只向 append-only `steering_log` 追加方向修正。

## SDK 入口

应用侧优先使用 `loops.hlp.HLPClient`。`HumanLoopOperations` 仍是协议操作层，负责状态机、前置条件、audit 和 adapter 联动；`HLPClient` 负责稳定 SDK 命名、事件发射、持久化 flush 和 demo-friendly workflow。

SDK 与 store 的读 API 返回 snapshot，调用方不能通过返回对象直接修改内部 aggregate。协议状态只能通过 operation 前进。`HumanLoopOperations` 内部使用 store 的 update path 修改 aggregate，以保持 read model 与 write model 分离。

```python
from loops.hlp import HLPClient, SQLiteHumanLoopStore

client = HLPClient(store=SQLiteHumanLoopStore("hlp.db"))
task = await client.create_task(principal="user_alice", goal="Review PR #1234")
run = await client.delegate(task.id, "agent_reviewer", capability="code-review")
```

## 集成契约（spec §5）

HLP 与外部 agent harness 的缝合点分成两个方向：

- `AgentAdapter`：HLP→harness，下发 delegate / block / resume / steer / handoff / cancel。
  `steer` 是 0.2.0 新增动作，对应 `task.amend`，把方向修正注入运行中的 agent run 而不重启。
- `HarnessAdapter`：harness→HLP，投影 needs_approval / needs_choice / needs_input / artifact 等 human-facing event。

历史上的 `AAPBridge` / `InMemoryAAPBridge` 兼容别名已经移除；HLP 不定义新的
agent-to-agent 协议或 harness mesh。

| HLP 操作 | Adapter 联动 | 铁律 |
|----------|---------|------|
| task.assign | delegate | TaskID = Run.correlation_id |
| checkpoint.raise | block | CheckpointID 传入 |
| checkpoint.resolve | resume | resolution 透传；若带 state_patch/edited_artifact_ref 则从该状态恢复 |
| task.interrupt | block | 人发起中断；harness 停当前 turn |
| task.amend | steer | 方向修正注入运行中的 run，不重启 |
| ownership.transfer | handoff | correlation_id 保持 |
| harness event | project into HLP object | human-facing event 不泄漏 harness internals |

生产和 demo 路径显式选择真实 adapter：`CodexCLIAdapter`、`KimiCLIAdapter`、`ClaudeCodeCLIAdapter` 通过本机 CLI prompt mode 覆盖完整 HLP lifecycle；`CodexHarnessAdapter` 对 `codex exec --json` 的 JSONL event stream 做窄投影，把显式 HLP human-facing events 映射为 `HarnessEvent`，但不接管 Codex execution loop。`FakeAgentAdapter` 和 `FakeHarnessAdapter` 是 deterministic test fixtures，仅用于单元测试、离线合约探针和故障注入，不作为 quickstart 或 production/demo 默认路径。`OpenAIAgentsSDKAdapter` 可通过注入 `runner + agent` 调用 OpenAI Agents SDK 的 `run/run_sync` 形态；`LangGraphAdapter` 可通过注入 compiled graph 调用 `ainvoke/invoke`；`CrewAIAdapter` 可通过注入 crew 调用 `akickoff/kickoff_async/kickoff`；`OpenAIPythonSDKAdapter` 可通过注入 `client.responses.create(...)` 调用 OpenAI Python SDK；`ProcessAgentAdapter` 使用 JSON-over-stdin/stdout runner 覆盖自定义 CLI/process 形态；`PromptCLIAdapter` 将 HLP request 嵌入 one-shot prompt，用于贴合 Codex CLI、Kimi CLI、Claude Code CLI 这类本机 coding-agent 命令。

adapter-coupled 操作遵循 fail-before-commit：如果 `delegate` / `block` / `resume` / `handoff` / `cancel` 失败，HLP Task、Checkpoint、Ownership、audit 和 run binding 不推进到假成功状态。当前参考实现用同步调用保证本地一致性；生产服务端应演进为 transaction + durable outbox + idempotency key。

Adapter capability baseline:

| Adapter | start/delegate | block/resume | handoff/cancel | correlation |
|---------|----------------|--------------|----------------|-------------|
| `ProcessAgentAdapter` | JSON object or JSONL stdout | JSON command wrapper | JSON command wrapper | validates returned `correlation_id` when present |
| `PromptCLIAdapter` | one-shot prompt + parsed JSON result | one-shot prompt wrapper | one-shot prompt wrapper | prompt requires returned `correlation_id`; validates when present |
| `CodexCLIAdapter` / `KimiCLIAdapter` / `ClaudeCodeCLIAdapter` | local CLI prompt mode | local CLI prompt mode | local CLI prompt mode | HLP `task_id` kept as run correlation |
| `CodexHarnessAdapter` | `codex exec --json` prompt mode | `codex exec resume`（session 连续性，默认开） | local CLI prompt mode | validates returned and projected event `correlation_id` when present |
| `PiHarnessAdapter` | `pi --mode json` prompt mode | `pi --session <id>` 恢复原生会话 | local CLI prompt mode | same shared JSONL projection + peek/ack |
| `ClaudeCodeHarnessAdapter` | `claude -p --output-format stream-json` prompt mode（protocol 模式原生 `--json-schema` 约束信封） | `claude --resume <id>` 恢复原生会话 | local CLI prompt mode | same shared projection; transport-level duplicate events（result envelope 重复 assistant 文本）按签名入队去重 |
| `KimiHarnessAdapter` | `kimi -p --output-format stream-json` prompt mode | `kimi --session <id>` 恢复原生会话 | local CLI prompt mode | same shared projection（HLP payload 嵌在 assistant content 文本内） |
| `OpenAIPythonSDKAdapter` | `client.responses.create(...)` | local contract recording, not real runtime pause yet | local contract recording | metadata + local handle |
| `OpenAIAgentsSDKAdapter` | injected `runner.run/run_sync` | local contract recording, not real runtime pause yet | local contract recording | local handle |
| `LangGraphAdapter` | `ainvoke/invoke` with `configurable.thread_id` | local contract recording, not real runtime pause yet | local contract recording | metadata + local handle |
| `CrewAIAdapter` | `akickoff/kickoff_async/kickoff` | local contract recording, not real runtime pause yet | local contract recording | metadata + local handle |

Test fixtures:

| Adapter | Scope | Purpose |
|---------|-------|---------|
| `FakeAgentAdapter` | unit tests only | records contract calls and failure-injection probes without executing a real runtime |
| `FakeHarnessAdapter` | unit tests only | queues deterministic harness events for projection contract tests |

Harness event projection baseline:

| Harness event | HLP projection | Human inbox |
| --- | --- | --- |
| `needs_approval` | `Checkpoint(kind="approval")` | `resolve_checkpoint` |
| `needs_choice` | `Checkpoint(kind="choice")` | `resolve_checkpoint` |
| `needs_input` | `Checkpoint(kind="input")` | `resolve_checkpoint` |
| `artifact` | `Artifact` committed to task | `submit_review` |

`CodexHarnessAdapter` consumes explicit HLP event payloads inside Codex JSONL
events. A delegated Codex run can emit:

```json
{"type":"hlp.event","run_id":"codex_run_1","correlation_id":"task_...","hlp":{"kind":"needs_approval","prompt":"Apply patch?","agent_id":"agent_codex"}}
```

The adapter turns this into `HarnessEvent(kind="needs_approval")`, and
`HLPClient.project_harness_events(...)` raises the protocol checkpoint. After
the human resolves the checkpoint, later Codex events with
`{"hlp":{"kind":"artifact", ...}}` become reviewable HLP artifacts.

`ProcessAgentAdapter` 约定所有操作都向 runner 传入结构化请求：

```json
{
  "operation": "delegate",
  "task_id": "task_...",
  "agent_id": "agent_codex",
  "capability": "code-review",
  "input": {"goal": "Review PR #1234"},
  "parent_run": null,
  "correlation_id": "task_..."
}
```

runner 返回 JSON object 或 JSONL event stream，`delegate` 至少应返回 `run_id`。如果返回 `correlation_id`，必须等于 HLP `task_id`。非零退出码、非法 JSON、runner exception、未知 run 和 SDK client exception 都包装为 `AgentAdapterError`。

本机 CLI adapter 使用同一结构化 request，但不是把 request 原样写入 stdin；它们会构造一个要求返回 JSON object 的 prompt，并把 prompt 作为 one-shot CLI 参数执行。`loops-hlp-local-cli-demo` 用真实 `codex`、`kimi`、`claude` 命令跑最小 delegate smoke test，用于验证本机环境是否能承载 HLP adapter。

## 分层纪律

HLP 参考实现刻意不依赖任何自研下层 runtime。这证明协议层可以独立存在
（transport-agnostic / harness-agnostic），也为 spec §1.2 适用范围提供实证。
有 `test_hlp_does_not_import_lower_layers` 守护此纪律。

## 不在本参考实现范围（spec §7 开放议题）

- transport 绑定（HTTP/gRPC/WebSocket）— 当前纯内存 async API；§7.1 已有 **stdlib 参考绑定 v1**（`loops.hlp.transport`：`POST /v1/ops/<object.verb>` 全 23 操作 + SSE audit 流 + version/health，零新增依赖；非目标：TLS/RBAC/WebSocket/远程 adapter 注册/typed from_wire；spec 文本未改，§7.1 收敛为后续提案）
- vendor package 直接依赖 — 当前通过对象注入提供框架级契约，不强依赖第三方包
- 服务端数据库后端 — 当前提供内存 store + SQLite 本地 snapshot store；生产级对象表、CAS、schema migration、audit hash chain 和 outbox/recovery 是后续 hardening 项
- HLP server/CLI 管理面 — 当前只提供 SDK 和 demo console script
- HLP→channel 通知 — 当前只提供 `human_inbox` 语义，不定义 UI/channel；BCI/语音等传感器输入走附录 C 的 channel/sensor plane（参考切片：`examples/hlp_bci_channel_demo.py`，协议零改动，D3 高风险 fail-closed）
- 开放议题定论（checkpoint 超时、委派深度、Ledger 并发等）— 实现后待收敛

## 验证

- `uv run pytest tests/test_hlp_sdk.py -q`：SDK facade、adapter、event、SQLite、demo
- `uv run loops-hlp-local-cli-demo --adapters codex,kimi,claude --strict`：真实本机 CLI adapter full lifecycle test
- `HLP_RUN_EXTERNAL_CLI_E2E=1 uv run pytest tests/external/test_hlp_real_cli_e2e.py -q`：opt-in external CLI E2E
- `uv run pytest tests/test_hlp_protocol.py -q`
- `uv run loops-hlp-demo`：Codex CLI adapter 端到端 demo，测试通过注入 runner 离线覆盖同一路径
- `uv run loops-hlp-adapters-demo`：无外部依赖 adapter compatibility demo
- `uv run loops-hlp-harness-demo`：Codex harness adapter wrapping demo，测试通过注入 runner 离线覆盖同一路径
- `uv run loops-hlp-codex-harness-demo`：无外部依赖 Codex JSONL harness adapter demo
- 端到端闭环覆盖 spec 附录 A "Review PR #1234" 全时序
