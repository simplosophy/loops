# AGENTS.md

Loops 是 **Human Loop Protocol (HLP)** 的协议规范与 Python 参考 SDK。
它提供人机责任闭环的 control plane，**不**提供自研 agent harness。

## 强制

- **KEEP UPDATE**: 如果较大代码变更，及时使用 git 提交代码，comment 中包含变化的详细描述
- 遵守架构设计文档 `docs/architecture/OVERVIEW.md`；若修改对架构有改造，需讨论并确认是否符合设计原则
- HLP 参考实现架构见 `docs/architecture/hlp.md` 与 `docs/architecture/LOOPS_STACK.md`
- **critical** 较大的修改重构按日期记录在 `docs/notes/yyyy-MM-dd.md`
- **critical** 较大变更计划记录在 `docs/plans/xxx.md`
- 用户可见变更在 `CHANGELOG.md` 的 `[Unreleased]` 段记录（Keep a Changelog 格式）

## 开发工作流

- 提交前必须通过：`uv run pytest tests/`、`uv run ruff check .`、`uv run ruff format --check .`、`uv run mypy loops`
- `pre-commit install` 后，lint/format/类型检查随提交自动执行
- CI = quality（ruff + mypy）与 tests（多平台 pytest + coverage + 元数据检查）；tag `v*` 触发 PyPI 发布

## 设计原则

- **极简**: 保持核心功能简单，避免复杂配置
- **正交性**: 保持核心功能正交，unix 设计思想，每个工具做一件事情，并且做好
- **一致性**: 代码风格和命名规范一致
- **分层架构**: 层与层之间通过接口通信
- **Fail Fast**: 快速失败，避免长时间阻塞
- **约定>配置**: 优先使用约定而非复杂配置
- **第一性原理**: 做设计和方案时使用第一性原理思考，避免陷入细节

## HLP 边界

**HLP owns**：Task / Checkpoint / Ownership / Artifact / Review / Ledger / Audit，
以及 `AgentAdapter` / `HarnessAdapter` 窄契约、human inbox 语义、audit 可重放。

**HLP does not own**：模型 provider、tool/MCP 调用、planning loop、memory/RAG、
agent-to-agent mesh、UI channel 送达、组织 RBAC/计费/调度。

TUI（`loops.tui`）是 **optional host/channel** 参考，不是协议核心。

## Adapter 深度

- **first-class**：真实 CLI/harness 投影（Codex / Claude / Kimi / Pi / Process）
- **shape-compatible**：Python framework 薄入口（OpenAI / LangGraph / CrewAI）
- **testing**：`Fake*` / `InMemory*`，仅离线单测与 demo

`HLP-industrial` 是 **reference profile**（CAS / idempotency / outbox / audit chain /
schema），不是多 writer 生产后端保证。

## 品味

- 为了确保上面的设计原则，需要敢于重构代码
- 敢于做大的不向后兼容重构
- 敢于质疑，提出问题
