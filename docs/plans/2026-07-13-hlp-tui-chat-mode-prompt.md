# TUI chat-mode prompt

| | |
|---|---|
| **日期** | 2026-07-13 |
| **状态** | 已完成 |

## Two prompt styles

| Mode | When | Shape |
|------|------|--------|
| **chat** | TUI free-text `delegate` | User message first + short JSON/JSONL constraints |
| **protocol** | Default adapters, lifecycle ops, offline contracts | Full “HLP adapter operation” envelope |

## Wiring

- `prompt_mode` on `PromptCLIAdapter` / harness subclasses
- TUI `build_client("codex"|"pi")` sets `prompt_mode="chat"`
- `render_agent_reply` still surfaces `summary` after the run

## Non-goals

- Streaming multi-turn UI
- Removing protocol mode or projection semantics
