# Session-Resume 连续性：四家 CLI 真运行时恢复

Date: 2026-07-20
Status: done (see docs/notes/2026-07-20.md)

## 目标

block/resume/steer/cancel 等后续操作恢复**同一个 CLI 原生会话**（携带完整上下文），
取代"每个操作一个全新一次性进程"。这是落地路径上把逻辑连续性升级为真连续性的
第一步，并用真实本地环境验证（"记住暗号→恢复会话→复述暗号"）。

## 已探明的机制（本机实测）

| CLI | 会话 ID 在 wire 中的位置 | 恢复命令 | 注意 |
|---|---|---|---|
| Codex | `thread.started` 事件 `thread_id` | `codex exec resume <id> <prompt>` | 会话默认录制；`--ephemeral` 影响 worktree 而非录制 |
| Claude Code | 每个 stream-json 事件的 `session_id` | `claude --resume <id> -p ...`（或 `-c` 最近） | **必须去掉 `--no-session-persistence`**（否则不落盘不可恢复） |
| Kimi | `role=meta` 行 `session_id` | `kimi --session <id> -p ...`（`-S`；`-c` 最近） | 默认持久化，无禁用标志 |
| Pi | `type=session` 事件 `id`（实测：`{"type":"session","version":3,"id":...}`） | `pi --session <id> --mode json -p ...` | **必须去掉 `--no-session`** |

## 设计（不改协议、不改 adapter 契约）

全部落在 `CodexHarnessAdapter`（四家共享基类）+ 每 CLI 窄覆盖：

1. **会话绑定**：`_execute` 解析事件后，经 per-CLI 提取器拿原生会话 ID
   （`_parsing.py` 新增 `session_id_from_events(events)` 统一处理四种形状），
   delegate/handoff 时记 `self._run_sessions[run_id]`；新增只读查询
   `session_of_run(run_id) -> str | None`。
2. **命令构造钩子**：`_execute` 的 `(*self.command, prompt)` 改为
   `_command_for_prompt(operation, request, prompt)`：
   - op ∈ {block, resume, steer, cancel} 且已知会话 → 返回该 CLI 的恢复命令
   - 否则一次性命令（现状）。
   - 每个 adapter 覆盖恢复命令模板（上表）；codex 恢复命令保留 `--json`
     与 `--output-schema`（若直播验证不支持 resume+schema 则降级并在 notes 记录）。
3. **持久化开关**：`CodexHarnessAdapter(..., session_continuity: bool = True)`。
   开启时 claude 从命令中剔除 `--no-session-persistence`、pi 剔除 `--no-session`；
   关闭时与当前行为完全一致（两条默认命令保持含该 flag，向后兼容）。
4. **block/cancel 语义不变**：仍向会话发协议信封（audit 诚实：已通知运行时；
   进程本就一发即走，恢复=同会话新一轮——文档注明这是当前 CLI 能提供的最强连续性，
   不是冻结点续跑）。

## 实施步骤

1. `_parsing.py`：`session_id_from_events`（codex thread.started / claude session_id /
   kimi meta session_id / pi type=session id）。
2. `CodexHarnessAdapter`：`session_continuity` 构造参数、`_run_sessions`、
   `_command_for_prompt` 钩子、`session_of_run`；codex 恢复命令。
3. `cli.py`：Pi/Kimi/Claude harness 的恢复命令模板 + 持久化 flag 剔除逻辑；
   两个 Claude/Kimi CLI 薄 adapter 同样支持（它们直接继承 PromptCLIAdapter，
   无事件流——会话 ID 从 payload/文本提取，若不可得则记为不支持并留一次性路径）。
4. 离线测试（注入 runner）：每家断言
   - delegate 后 `session_of_run` 返回 wire 中的会话 ID；
   - resume/steer/block/cancel 命中恢复命令且含正确会话 ID；
   - 无会话 ID / `session_continuity=False` 时回退一次性命令；
   - 恢复输出的解析（同 wire 形状）。
5. **真实本地环境测试**：新增 `examples/hlp_session_continuity_e2e.py` —
   每 CLI：`delegate("记住暗号 XJ42…")` → 同 run `steer("复述暗号")`
   （及一轮 checkpoint block/resume），断言恢复回复含暗号；另跑一条 HLP 级
   流程（create→delegate→start→amend→checkpoint→resolve）验证连续性穿透。
   新增 `tests/external/test_hlp_session_continuity_real_cli.py`（`HLP_RUN_EXTERNAL_CLI_E2E=1` 门控），
   本机四家全跑并记录结果。
6. 文档：README Adapter Depth 补连续性说明、hlp.md adapter 段、CHANGELOG、
   notes、本计划归档 docs/plans。

## 非目标

- 不改 HLP spec、不加协议对象、不改 `AgentAdapter`/`HarnessAdapter` 契约。
- 不做真冻结/快照恢复（CLI 不支持）；不做会话分叉（pi --fork / claude --fork-session，留后续）。
- TUI 默认行为不变（build_client 不传 session_continuity 时默认开，chat 模式 steer/resume 自然受益；不新增 UI）。

## 验证

- 离线：全量 pytest、mypy strict、ruff 绿；新增连续性测试全绿。
- 直播：四家暗号复述全部命中（结果记入 notes）；`tests/external/` 全套仍绿。
