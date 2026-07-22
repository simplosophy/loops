# 2026-07-22 TUI industrial UX: spinner, quick keys, broadcast

## 背景

目标：把 `loops-hlp-tui` 打磨到 codex / claude code 级别的终端 UX，并强化多
harness 能力。零新依赖（stdlib only）是硬约束。

## 变更

### 流式渲染（`loops/tui/stream.py` 重写）

- **信封降噪**：chat-mode 模型回复末尾的 HLP JSON 信封不再原样刷屏，只显示
  `summary`。kimi 把信封按 delta 流式输出，因此 `StreamPrinter` 对以 `{`
  开头的文本做投机挂起（speculative holdback）：能完整 `json.loads` 且含
  `summary` + `run_id`/`correlation_id` → 只打 summary；非信封 JSON / 不可
  解析 → 原文输出；流结束仍未闭合 → flush 原文。
- **thinking 暗色、error 红色**：`StreamPrinter(style=)` 由 `Console.style`
  注入。
- **收尾换行**：`run_prompt_process_streaming` / `make_streaming_prompt_runner`
  新增 `on_close` 钩子（成功与超时路径都触发），`build_client` 接
  `printer.close`，修复流文本与结果行粘连（`十started task …`）。

### 等待反馈（`loops/tui/app.py`）

- `run_with_progress(animate=)`：TTY 上 braille 帧 spinner（`\r` 覆盖同行），
  非 TTY 保持原心跳行；`animate=None` 自动判定。

### 交互（`loops/tui/_base.py`, `console.py`）

- **y/n 快速裁决**：活动任务有待决 checkpoint 时，裸 `y`/`n` 直接
  approve/reject；无待决时按普通 prompt 处理（不劫持输入）。
- **内联审批卡**：`_finish_with_harness_output` 末尾查 inbox，有待决
  checkpoint 时输出 `⚠ checkpoint pending: …` + `[y] approve · [n] reject ·
  /choose · /input` 提示。与 `render_human_loop` 的 pending 行并存。
- **进度面板内联**：snapshot 带 items/agents 时 prompt 输出直接渲染全量
  checklist/子代理树（`render_progress`），否则保持一行摘要。
- **多行输入**：`Console.input` 支持 `\` 续行（交互与非交互路径一致），
  EOF 中途断开返回已缓冲内容。

### 多 harness：`/broadcast`

- `task.assign` 要求 `created` 状态 → 每个 harness 一个独立 HLP task
  （`type="tui-broadcast"`，共享 store，各自完整审计链），串行 fan-out 到
  claude/codex/kimi/pi（`_SWITCHABLE_ADAPTERS - {"fake"}`，字母序）。
- 单家失败（binary 缺失、超时、协议错误）不拖垮其余：错误内联渲染在该家
  结果块里。
- 对比块：`── <adapter> ── task=… run=…` + 缩进 reply（600 字符截断），
  `render_agent_reply` 重构出 `agent_reply_text`（无 `agent: ` 前缀）复用。
- 广播是 side inquiry：不移动 `session.active_task_id`。

## 验证

- 单测 344 passed / 3 skipped（新增 12：审批卡、y/n 裁决、y 无待决回落、
  整块+delta 信封降噪、非信封 JSON 原文、spinner 帧与擦除、on_close、全量
  进度面板、广播顺序/共享 store/失败隔离/参数校验、`\` 续行）。
- mypy strict 60 文件、ruff check/format 全清。
- 直播：codex 真实问答（心跳回退 + 信封降噪）；kimi 真实问答（delta 信封
  只显示 summary，收尾换行正确）；`/broadcast` 四家真实 CLI 全部应答并渲染
  对比块（codex 答"二"、其余答"2"，对比视图确实有用）。

## 注意

- 投机挂起的边界：模型以 `{` 开头回复普通 JSON 文档时，会延迟到 JSON 闭合
  才输出（正确性优先于逐字流感）。
- `/broadcast` v1 串行；并行 fan-out 需要各家 timeout 叠加之外的并发控制，
  留待后续。

## 追加：广播错误诊断（同日）

初版广播行内错误只有 `error: {exc}`，把 `AgentAdapterError.details`
（exit_code / command / stderr）全丢了，用户无法区分"CLI 挂了"和"超时"。
改为行内直接复用 `render_error`（含 stderr 尾部与恢复 hint），错误行不受
600 字符截断限制（诊断文本已被 render_error 自身 400 字符 stderr 尾部约束）。
直播探针证实：kimi 偶发超过 30s（exit_code 124 超时），codex 为瞬时失败，
重跑即恢复。

