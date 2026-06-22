# loop2 架构

> HLP（Human Loop Protocol）参考实现。
> 对应规范：[`docs/specs/HLP.md`](../specs/HLP.md)
> 定位调整：[`docs/plans/2026-06-22-hlp-first-site-positioning.md`](../plans/2026-06-22-hlp-first-site-positioning.md)

## 定位

loop2 是 Human Loop Protocol (HLP) 的参考实现。它定义**人**与**自主 agent** 如何围绕一个有边界的工作单元（Task）进行委派、把关、交付与治理。

loop2 不与 loop0/loop1 竞争，而是补上 MCP / Agent Skills（agent↔工具）和 A2A / ACP / AGNTCY（agent↔agent）未覆盖的维度：**agent 与其负责人之间的责任闭环语义**。L1/L0 由既有协议承担，loop2 只通过 adapter 契约接入。

## owns coordination

loop2 owns coordination：负责多个用户、多个 agent 如何在项目空间内协同运行。核心单位是 `ProjectSpace / OrgRuntime`，但参考实现聚焦于**协议语义**而非组织模型——后者留后续。

## 包结构

```text
loops/loop2/
  __init__.py          # 公开 API re-export
  _ids.py              # ULID + 前缀生成器 (spec §3.1)
  types.py             # ProtocolError + Literal 类型别名
  objects.py           # 7 个一等对象 dataclass
  state_machine.py     # Task 状态机：合法转移表 + 校验
  store.py             # HumanLoopStore：内存存储
  operations.py        # 21 个操作 (spec §4)
  audit.py             # AuditEvent + AuditLog (append-only)
  contracts.py         # AAPBridge Protocol + InMemoryAAPBridge stub
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
                              ↘ review_ready → under_review → accepted → completed
                                              ↘ (changes) → in_progress
                                              ↘ rejected (终态)
```

合法转移由 `LEGAL_TRANSITIONS` 表显式定义，非法转移抛 `ProtocolError("PRECONDITION_FAILED")`。

## 集成契约（spec §5.1）

loop2 与 L1 agent runtime 的缝合点，通过 `AAPBridge` Protocol 定义。命名保留历史连续性，语义上它是 HLP→L1 adapter：

| HLP 操作 | L1 adapter 联动 | 铁律 |
|----------|---------|------|
| task.assign | delegate | TaskID = Run.correlation_id |
| checkpoint.raise | block | CheckpointID 传入 |
| checkpoint.resolve | resume | resolution 透传 |
| ownership.transfer | handoff | correlation_id 保持 |

参考实现提供 `InMemoryAAPBridge` stub——只记录调用不执行，用于验证 HLP 在正确时机调用了正确的 L1 adapter 方法，且 TaskID 贯穿。

## 分层纪律

loop2 刻意不 import loop1/loop0。这证明协议层可以独立存在（transport-agnostic），也为 spec §1.2 适用范围提供实证。有 `test_loop2_does_not_import_lower_layers` 守护此纪律。

## 不在本参考实现范围（spec §7 开放议题）

- transport 绑定（HTTP/gRPC/WebSocket）— 当前纯内存 async API
- 真实 L1 agent runtime adapter — 当前只 stub
- 真实持久化后端 — 当前内存 + 可选 JSONL
- CLI — 本阶段不做
- HLP→channel 通知 — stub
- 开放议题定论（checkpoint 超时、委派深度、Ledger 并发等）— 实现后待收敛

## 验证

- `uv run pytest tests/test_loop2_hlp.py -q`：39 passed
- 端到端闭环覆盖 spec 附录 A "Review PR #1234" 全时序
- 全仓库 `uv run pytest -q`：70 passed
