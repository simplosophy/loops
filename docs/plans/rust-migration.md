# Python to Rust Migration Plan

目标：将当前 Python `loops` 项目迁移为 Rust 实现，并最终移除 Python runtime 作为主实现。

## 迁移原则

- 不追求向后兼容 Python 内部模块路径，最终以 Rust crate / binary 为主。
- 先迁移 loop0，再迁移 loop1/loop2；不要在 Rust loop0 中重新引入 channel/session/storage。
- 每个阶段必须能编译、能测试，并能通过当前样例配置验证关键路径。
- Python 代码在 Rust 功能覆盖前可以暂留，但不能成为最终完成标准。

## 阶段 1：Rust 基础骨架

- 建立 `Cargo.toml`、`src/`、`tests/*.rs`。
- 迁移 loop0 配置模型：prompt/provider/policy/agent/run/interaction/output。
- 迁移 dotenv 加载、JSON/TOML 配置解析、相对路径规则。
- 建立 Rust `loops-loop0` binary。
- 首版迁移 OpenAI-compatible 非流式 provider、prompt 渲染、tool loop 和 `shell.run`。

当前状态：已开始。

## 阶段 2：loop0 Runtime 完整化

- 对齐 Python loop0 的 `Agent` / `AgentSpec` / `AgentRuntime` 公共抽象。
- 完整迁移 `AgentEvent`、`EventSink`、`AgentState`、`ToolRegistry`、`Component`。
- 补齐 provider streaming、reasoning delta、usage、tool call delta folding。
- 补齐 shell tool 的安全策略、审批、background session、结构化日志。
- 增加 Rust 单元测试和端到端 CLI 测试。

当前状态：

- 已新增 Rust `AgentSpec` / `AgentRuntime`，让 CLI 运行路径通过 runtime 抽象执行。
- 已新增 Rust `EventSink`、`NullEventSink`、`InMemoryEventSink`。
- 已把 provider stream text/reasoning delta 转换为 `provider_delta` / `provider_reasoning_delta` 事件。
- 已新增 Rust `AgentState`，支持 thread history commit 和 recall 基础模型。
- 已新增 Rust `ToolRegistry` / `ToolExecutor`，并把 shell 接入 registry。
- 已新增 `run_input(UserInput, EventSink)`，使 Rust runtime 接近 loop0 的核心调用边界。
- 已新增 Rust `Component` / `Contribution` / `RunContext`，支持组件贡献 prompt blocks/tools 并观察 runtime events。
- 已补齐 Rust OpenAI-compatible streaming tool call delta folding。
- 已补齐 Rust shell 参数别名、结构化输出、安全拦截、外部路径策略和 background session 基础操作。
- 已扩展 Rust `loops-loop0` CLI flags，覆盖 provider、agent、policy、interaction、output 的主要配置面。
- 阶段 2 剩余重点：端到端 CLI 覆盖与更细的 shell 审批 host 接口。

## 阶段 3：替换 Python CLI 和包入口

- 将 `loops-loop0` 切到 Rust binary。
- 用 Rust README/示例替换 Python 示例。
- 明确保留或移除 `uv`/Python packaging；最终以 Cargo 为主。
- 清理 `.py` runtime 源码、Python tests、egg-info 和 uv lock。

## 阶段 4：loop1 / loop2 Rust 化

- 在 Rust 中建立 `loop1` 和 `loop2` crate/module 边界。
- 根据架构文档迁移 session/channel/storage/project organizer 抽象。
- 添加跨层协议测试，确保 `loop2 -> loop1 -> loop0` 单向依赖成立。

## 完成标准

- 仓库主实现为 Rust，Python runtime 源码不再是执行路径。
- `cargo test` 覆盖 loop0 核心 runtime、provider、tool、CLI config。
- `loops-loop0 --config examples/loop0.config.json` 走 Rust binary。
- 架构文档、README、样例和 notes 与 Rust 实现一致。
