# HLP TUI harness human-loop

| | |
|---|---|
| **日期** | 2026-07-13 |
| **状态** | 已完成 |
| **关联** | TUI 优美兼容 Pi / Codex harness 交互 |

## 目标

TUI 作为 host/channel，对 first-class harness（Codex / Pi）走同一人机闭环路径：

```text
prompt
  → HLP create/delegate/start
  → harness JSON(L) human events
  → project_harness_events
  → surface checkpoint / artifact
  → /approve|/reject|/review
  → re-project after resolve
```

## 行为

- `build_client("codex")` → `CodexHarnessAdapter`（非 one-shot CLI-only）
- `build_client("pi")` → `PiHarnessAdapter`（`pi --mode json -p --no-session --no-tools`）
- `build_client("fake")` → offline，不投影
- prompt / checkpoint resolve 后自动 `project_harness_events` + `render_human_loop`
- live：`--timeout` + progress heartbeat + 结构化 adapter 错误

## 非目标

- 全屏 TUI / token streaming
- 模型 provider / tool runtime 进 HLP core
- LangGraph 等 shape-compatible adapter 扩面
- 把 live 网络 E2E 当 CI gate

## 验证

- `uv run pytest tests/test_hlp_tui.py -q`
- offline injected Codex/Pi harness loop through real `TUIController`
- `uv run loops-hlp-tui --help`；`run_lines` + fake 离线路径
