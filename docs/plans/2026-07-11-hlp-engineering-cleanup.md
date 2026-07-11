# HLP Engineering Cleanup Plan

| | |
|---|---|
| **日期** | 2026-07-11 |
| **状态** | 已完成 |
| **关联** | 项目审计意见：CI 护栏、遗留清理、adapter 拆分、文档口径 |

## 目标

在不改变 HLP 架构边界的前提下完成工程硬化：

1. 默认 offline CI 保护协议语义与发布元数据
2. 清理 loop0 时代遗留与未用依赖
3. 按正交性拆分 `adapters.py`
4. 明确 adapter 深度分级与 industrial reference-only 口径

## 非目标

- 不吸收 harness / model / tool runtime
- 不服务端化 HLP core
- 不移除现有 public 符号（仅分层标注，保持 import 兼容）

## Phase A — P0 护栏与清理

- 新增 GitHub Actions：pytest + release metadata + spec/site sync
- 移除未用 `jinja2` 依赖
- 删除/替换无意义 `main.py`、清理 `loop0.egg-info`
- 更新 `AGENTS.md` 到 HLP-first 现状
- README / conformance 标明 adapter depth 与 industrial reference-only

## Phase B — Adapter 正交拆分

将 `loops/hlp/adapters.py` 拆为包，保持 `from loops.hlp.adapters import X` 兼容：

```text
loops/hlp/adapters/
  __init__.py      # public re-export
  protocol.py      # contracts + value objects
  _util.py         # shared helpers
  _parsing.py      # stdout / JSON / HLP payload parsing
  fake.py          # Fake* / InMemory*
  process.py       # Process / Prompt CLI base
  callable.py      # PythonCallableAgentAdapter
  frameworks.py    # shape-compatible OpenAI/LangGraph/CrewAI
  codex.py         # Codex CLI + harness + event projection
  cli.py           # Claude / Kimi / Hermes / Pi
```

## Phase C — 验证

- `uv run pytest tests/ -q`
- `uv run python scripts/check_release_metadata.py`
- `uv run python scripts/check_spec_site_sync.py`
- 更新 `docs/notes/2026-07-11.md` 与 git commit

## 完成定义

- CI workflow 存在且命令与本地一致
- adapters 包结构落地，旧单文件消失
- 测试与 metadata 检查全绿
- 文档明确 first-class vs shape-compatible adapter，以及 industrial reference slice
