# Transport Binding v1：HLP HTTP 参考绑定（§7.1 服务化）

Date: 2026-07-20
Status: done (see docs/notes/2026-07-20.md)

## 背景与设计原则核对

§7.1 是 spec 的开放议题：参考实现目前纯进程内 async API。服务化让远程
host/channel（web/IM bot/其他服务）能用 HLP 语义。按 AGENTS.md 设计原则核对：

- **极简 / 零依赖**：SDK 现仅 2 个依赖。引入 web 框架（fastapi/aiohttp）违背
  极简；stdlib `http.server` + `urllib` 足够做**参考绑定**——wire 契约才是交付物，
  生产部署者自选框架重实现（spec 本就 transport-agnostic）。
- **约定>配置**：HLP 是 ops 协议（23 个 `<object>.<verb>`），不为它硬造 REST
  资源建模。单一 ops 端点直接映射操作表，无路由发明。
- **正交性**：transport 是薄薄一层（wire 进出 + 错误映射 + 事件流），业务全在
  既有 `HumanLoopOperations`；协议 spec 零改动（§7.1 收敛留待后续正式提案）。
- **Fail fast**：版本协商端点 + §6.4 schema 校验 + CAS/幂等透传。

## 设计决策

**D1 端点表（HTTP/JSON）**

| 端点 | 语义 |
|---|---|
| `POST /v1/ops/{object.verb}` | 全部 23 个协议操作 + `human.inbox` + `pending.outbox` + `checkpoints.expire_due`。Body：`{"actor","params",{...},"expected_task_revision","idempotency_key"}` |
| `GET /v1/events?after=<seq>` | SSE 流（`HLPEvent` wire dict，`id: seq`；`after` 断点续传） |
| `GET /v1/version` | spec/schema/profile 版本（对接 `negotiate_hlp_version`） |
| `GET /v1/health` | 存活 + adapter healthcheck |

**D2 Wire 与错误**

- 结果：`to_wire()`（已有，全对象覆盖）；客户端 v1 直接消费 wire dict
  （wire 即契约；typed `from_wire` 重建留作后续）。
- 结构化入参（CheckpointOption/ArtifactPayload/ReviewComment 等少数）由
  dispatch 表显式构造，其余参数原样透传。
- 错误：`ProtocolError` → §6.1 的 HTTP 类比表（400/401/404/408/409/410/412）
  + §6.2 错误对象 body；未知异常 → 500 + `INTERNAL`（不泄漏堆栈）。
- CAS/幂等：`expected_task_revision` / `idempotency_key` 随 body 透传，
  语义复用现有实现（含 CONFLICT 语义）。

**D3 身份**

- `X-HLP-Principal` 头：变更类操作**必须**携带（server 绑定 actor 与
  resolution.by）；§1.2 RBAC 不进 HLP——真实认证交给反向代理/中间件，
  文档明示。

**D4 实现形态**

- `loops/hlp/transport/server.py`：`ThreadingHTTPServer`，共享 asyncio
  循环线程跑 ops（`run_coroutine_threadsafe`）；SSE 用 seq 游标轮询
  `InMemoryEventBus.events`。
- `loops/hlp/transport/client.py`：`urllib` 参考客户端（wire 级方法面 +
  SSE 读取器）。
- `loops-hlp-serve` console script：`--host/--port/--adapter/--store`。
- `loops/hlp/transport/__init__.py` 导出；打包进 `loops*` 自动带上。

## 实施步骤

1. `loops/hlp/transport/`：server（dispatch 表 + 错误映射 + SSE + health/version）
   + client + console script 注册。
2. 真实 socket 测试（ephemeral 端口，无新依赖）：
   - 全生命周期 round-trip：create→assign→start→amend→interrupt→resolve→
     artifact→review→ledger→audit.replay；断言与进程内语义一致。
   - CAS：`expected_task_revision` 过期 → 409 CONFLICT；
     `idempotency_key` 重放 → 结果一致且无二次副作用（audit seq 不变）。
   - 错误映射：NOT_FOUND→404、PRECONDITION_FAILED→412、UNAUTHORIZED→401、
     INVALID_SPEC→400、CHECKPOINT_EXPIRED→410、VERSION_UNSUPPORTED→409。
   - 缺 `X-HLP-Principal` 的变更请求 → 401。
   - SSE：事件按 seq 顺序送达，`after` 续传不重不漏。
   - version 端点内容 = `negotiate_hlp_version` 期望。
3. 文档：README（Transport 段）、`docs/architecture/hlp.md`（参考绑定 v1 +
   明确非目标）、CHANGELOG、notes、plan 归档 docs/plans。
4. 明确非目标（写进文档）：无框架依赖、无 TLS、无 RBAC（§1.2）、无
   WebSocket/实时软信号、无远程 adapter 注册（adapter 仍 server 本地）、
   无 typed from_wire（v1 wire dict 即契约）、spec 文本不改。

## 验证

- 离线：全量 pytest（含新 transport 套件，真实 socket）、mypy strict、ruff 绿。
- 手测：`loops-hlp-serve --adapter fake` + `curl` 全生命周期 + SSE 事件。
