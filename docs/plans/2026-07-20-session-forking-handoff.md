# Session Forking：handoff 真语义（接手 agent 继承上下文）

Date: 2026-07-20
Status: done (see docs/notes/2026-07-20.md)

## 背景

Session continuity 已让 block/resume/steer/cancel 恢复同一原生会话。但
`ownership.transfer → handoff` 目前对**所有** CLI 都是"新一次性会话 + 信封带
context"——接手 agent 没有原会话上下文，不是真正的交接。本次让支持 fork 的
CLI 在 handoff 时**分叉原生会话**（接手方继承全部上下文），其余保持回退。

## 机制矩阵（本机 help 实测）

| CLI | fork 能力 | handoff 命令 |
|---|---|---|
| Pi | `pi --fork <id>`（分叉为新会话） | `pi --mode json --fork <src_id> -p <prompt>` |
| Claude Code | `--fork-session`（配 `--resume`） | `claude --resume <src_id> --fork-session -p ...` |
| Codex | 无（exec resume 无 fork 选项） | 回退：一次性信封（现状） |
| Kimi | 无 | 回退：一次性信封（现状） |

分叉后新会话 ID 由 wire 自带（pi 新 `type=session` 事件；claude 新 `session_id`），
现有 `_bind_session(new_run_id, events)` 直接复用，无需改动。

## 设计（continuity 的同一扩展点，无契约变更）

1. `CodexHarnessAdapter._command_for_prompt`：`operation == "handoff"` 时，
   连续性开启且当前 run 有会话绑定 → 调 `self._fork_command(session_id, prompt)`；
   返回 `None`（该 CLI 不支持 fork）→ 回退一次性命令（现状）。
2. `_fork_command(session_id, prompt) -> tuple | None`：基类默认 `None`
   （codex 不支持）；cli.py 覆盖：pi / claude 返回上表命令，kimi 返回 `None`。
3. handoff 的结构化 `context` 仍随信封携带（分叉带历史 + 信封带显式交接上下文，
   双保险）；新 run 的会话绑定沿用现有 `_bind_session`。
4. 文档明确能力矩阵：pi/claude 为 fork 真交接；codex/kimi 为信封交接（记录差异，
   待 CLI 长出 fork 能力后接入）。

## 实施步骤

1. `codex.py`：`_command_for_prompt` 增加 handoff 分支 + `_fork_command` 默认实现。
2. `cli.py`：Pi/Claude/Kimi harness 覆盖 `_fork_command`。
3. 离线测试（`tests/test_hlp_session_continuity.py` 增补）：
   - pi/claude handoff 命中 fork 命令且含源会话 ID；新 run 绑定分叉后的新会话 ID；
   - codex/kimi handoff 保持一次性命令（无 fork flag）；
   - 无会话绑定时回退一次性。
4. 直播验证（暗号模式）：delegate(记住暗号) → handoff → 新 run steer(复述暗号)：
   - pi/claude 必须复述命中（分叉继承的证明）；
   - codex/kimi 只断言交接成功 + 信封携带 context（不断言暗号）。
   挂进 `examples/hlp_session_continuity_e2e.py` 的 handoff 探针段与
   `tests/external/test_hlp_session_continuity_real_cli.py`。
5. 文档：README 连续性段补 fork 矩阵、hlp.md 表、CHANGELOG、notes、plan 归档。

## 非目标

- 不做 codex/kimi 的"伪 fork"（如手工复制会话文件）——只接原生能力，差异透明记录。
- 不改 handoff 的请求/返回契约；不改 spec。
- transport binding（§7.1 服务化）属架构议题，另行讨论，不在本次。

## 验证

- 离线：全量 pytest / mypy strict / ruff 绿。
- 直播：pi/claude 分叉暗号命中；codex/kimi 回退正确；`tests/external/` 全套绿。
