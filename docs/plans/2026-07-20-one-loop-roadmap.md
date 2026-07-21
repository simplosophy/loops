# One Loop to Rule Them All：HLP 成为通用人类控制面的路线图

Date: 2026-07-20
Status: approved roadmap; L1 spike underway (see docs/notes/2026-07-20.md)

## 目标的可检验定义

"HLP on top of all harnesses" 落到可验证的事，是三条：

1. **任何 harness 接入 HLP 的边际成本 ≈ 0**——不是靠我们给每个 CLI 写一个 adapter，而是存在一个通用接入向量，harness 自己就能投影。
2. **人在回路真正闭合**——审批/checkpoint 到达人每天真实使用的渠道（IM/手机），而不是只到一个 Python TUI。
3. **协议可信**——不止一个实现、不止一家在用，spec 能离开本仓库独立成立。

## 现状 → 差距地图

| 层 | 已有（2026-07-20） | 到"rule them all"的差距 |
|---|---|---|
| 协议 | 0.2.0-draft + realtime 0.3-draft、conformance 三 profile、§7.1/§7.5 已收敛 | 剩余开放议题未收敛（§7.2/7.3/7.4/7.6/7.7）；无第二实现；wire 金样 fixtures 缺失 |
| 接入 | 4 家 CLI first-class（投影+结构化输出+会话恢复/分叉） | **每接一个 harness 都要我们写 adapter**——不可扩展；无第三方 adapter 工具链 |
| 核心 | reference profile（CAS/幂等/outbox 恢复/expire 扫描）、内存+SQLite | 无生产级持久层（PG）、outbox 无消费者、无多写者、无调度器、审计无签名证据 |
| 服务 | stdlib HTTP 参考绑定 v1 | 单进程参考实现；无框架版 server、无 TLS/tenancy |
| 人类通道 | TUI 参考、BCI 参考切片 | **人不在 TUI 里**：没有 IM bot、没有 web/mobile 审批界面 |
| 生态 | PyPI、文档站、dependabot、开源基建 | 无 adapter 目录、无原生插件、无 RFC/治理、无采用者案例 |

## 五条主线（按杠杆排序）

### L1 通用接入向量：HLP as MCP server（最高杠杆）

现状每家 CLI 都靠我们解析私有 JSONL 方言。已实测：Codex/Claude/Kimi/Pi 全部支持
MCP 或扩展机制。**把 HLP 以 MCP server 形式提供**（`checkpoint.raise`、
`artifact.commit`、`needs_decision` 等作为 MCP tools），任何 MCP 兼容 harness
即可原生投影 HLP 事件——从"我们适配每个 CLI"变成"harness 自带接入"。
交付：`loops-hlp-mcp`（stdio MCP server，映射到 HumanLoopOperations + adapter
outbox）、四家在跑验证、adapter 声明指南。这一步直接决定"on top of all"是否成立。

### L2 人类通道：IM bot + 最小 Console

回路的另一半是人。`human_inbox` 语义已 UI-agnostic（spec §5.3）。
交付：一个 IM channel（Lark 或 Slack 选一）——checkpoint 卡片（approve/reject/
choose）、review 通知、audit 链接；再加一个只读 web console（inbox 列表 +
audit 回放页，挂 transport v1 即可）。人能在 30 秒内从手机关掉一个 checkpoint，
HLP 才从"协议"变成"工具"。

### L3 生产核心：reference → deployable

把 industrial profile 从参考切片变成可部署物：
Postgres store（schema 从对象模型直出）+ outbox 消费者（retry/backoff，现在只有
intent 记录与手动重试）+ server 版 expire 调度 + 框架版 server（可选 extra，
fastapi；stdlib 参考绑定保留）+ 审计签名证据位（ExternalRef attestation profile）。
不含多租户 RBAC（§1.2 边界），但留 tenancy key。

### L4 协议可信：第二实现 + 1.0

一个实现的协议是库。交付：TypeScript SDK（对象+操作+wire 对齐，吃 JS agent
生态）+ golden wire test vectors（从 conformance 抽出 JSON fixtures，跨实现
互验）+ 剩余开放议题收敛（§7.2 超时默认、§7.3 委派深度、§7.4 Ledger 并发、
§7.6 跨项目引用、§7.7 版本兼容策略）→ HLP 1.0。realtime profile 随 1.0 转正。

### L5 生态与治理（持续项，不是阶段）

adapter 目录（谁声称 HLP-integrated，conformance 证据链）、至少一个 harness
厂商的原生插件（用 L1 的 MCP 包做敲门砖）、公开 RFC 流程（spec 变更治理）、
一个企业叙事（审计/合规故事：hash 链 + 签名证据 = 可核查的责任链）。

## 建议顺序与理由

- **P1（接下来 4-6 周）**：L1 MCP 向量 → L2 IM bot（先 Lark，团队自用即吃狗粮）
  → L3 的 PG store + outbox 消费者。理由：L1 决定覆盖上限，L2 决定有没有人用，
  L3 决定敢不敢上生产；三者都可并行、互不阻塞。
- **P2（随后）**：L4 TS SDK + golden vectors → spec 1.0；console web UI。
- **P3（持续）**：L5 生态项，随采用自然发生，不前置。

## 非目标（防止"rule them all"变成"do them all"）

- 不做自有 harness/模型路由/规划器（HLP 边界，AGENTS.md 已锁）。
- 不把 RBAC/计费/组织模型做进协议（留 host/部署层）。
- 不追求覆盖所有 CLI 的原生方言 adapter——原生方言只维护四家参考实现，
  其余一律走 L1 MCP 向量。
- 不做 UI 产品创新（console 保持只读 + 操作两个动作，通道逻辑在 host）。

## 度量

- 接入：支持 harness 数（原生 4 → MCP 向量覆盖数）；第三方 adapter 数。
- 使用：人侧 checkpoint 中位响应时间；周活跃审批人；PR desk 式落地案例数。
- 可信：独立实现数（≥2）；声称 conformance 的外部项目数；spec 引用/引用实现比。

## 立即可做的第一步（本计划批准后）

L1  spike：`loops/hlp/mcp_server.py` 原型（stdio MCP server，暴露
checkpoint_raise / artifact_commit / inbox_poll 三个 tools），claude
`--mcp-config` 实测端到端投影，一天内出结论（MCP 语义是否足够承载
HarnessEvent 四类事件 + cursor ack）。
