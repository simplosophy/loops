# HLP Real Adapter E2E Plan

| | |
|---|---|
| **日期** | 2026-07-06 |
| **状态** | 执行中 |
| **关联** | HLP adapter boundary, local CLI adapters, demo/site quickstarts |

## 背景

HLP 已有完整 reference state machine、adapter outbox、audit/hash-chain、
conformance suite 和本机 CLI adapter 类型，但 public demo、quickstart 和部分 E2E
仍容易把 `FakeAgentAdapter` 理解为默认路径。工业级协议不能用 fake runtime 证明
端到端集成能力；fake 只能保留在单元级 contract probe 和 failure injection。

## 目标

- demo、site quickstart 和 README 嵌入示例默认使用显式真实 adapter：
  `CodexCLIAdapter`、`KimiCLIAdapter`、`ClaudeCodeCLIAdapter` 或
  `CodexHarnessAdapter`。
- `examples/hlp_local_cli_e2e.py` 覆盖完整 HLP lifecycle，而不只是 delegate smoke：
  create、delegate、start、amend、checkpoint raise/resolve、artifact commit、
  review submit、ledger write、audit replay，以及 handoff/cancel control path。
- 默认测试仍离线稳定：通过 injected runner 验证真实 adapter path，不要求网络、模型凭证
  或 CLI 登录态。
- 真实外部 CLI E2E 只在 `HLP_RUN_EXTERNAL_CLI_E2E=1` 时运行；一旦启用，缺失命令、
  认证失败或非 `ok` adapter payload 都是结构化失败。
- `FakeAgentAdapter` / `FakeHarnessAdapter` 保持导出兼容，但文档明确为 test fixture。

## 范围

- `examples/hlp_e2e_demo.py` 改为 Codex CLI adapter 默认路径，并支持注入 runner、
  timeout 和 strict CLI 行为。
- `examples/hlp_local_cli_e2e.py` 增加 `--adapters`、`--timeout`、`--strict` 和每
  adapter 结构化结果：status、task/run/correlation、adapter operations、最终 task
  state、review/ledger/audit、error/details。
- `examples/hlp_harness_wrap_demo.py` 改用 `CodexHarnessAdapter` 和 injected runner，
  保留离线可运行的 harness event projection。
- 新增 `tests/external/test_hlp_real_cli_e2e.py`，由 `HLP_RUN_EXTERNAL_CLI_E2E=1` 显式
  开启。
- README、site quickstarts、`docs/architecture/OVERVIEW.md` 和
  `docs/architecture/hlp.md` 迁出 fake default language。

## 非目标

- 不删除 `FakeAgentAdapter` 或 `FakeHarnessAdapter`。
- 不把 HLP core 变成 agent harness、模型 runtime、tool runtime 或 channel delivery。
- 默认 release verification 不依赖外部 CLI、网络或用户凭证。

## 验证

- `uv run pytest -q`
- `uv run pytest tests/conformance -q`
- `uv run python -m compileall loops tests examples`
- `uv run python scripts/check_release_metadata.py`
- `uv run python scripts/check_spec_site_sync.py`
- `git diff --check`
- `npm run verify`
- Opt-in: `HLP_RUN_EXTERNAL_CLI_E2E=1 uv run pytest tests/external/test_hlp_real_cli_e2e.py -q`
