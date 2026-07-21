# TUI → 独立 Harness：`loops-hlp-tui` 升级计划

Date: 2026-07-21
Status: done (see docs/notes/2026-07-21.md)

## 背景与定位

不走 MCP 路线。目标：把 `loops.tui` 从"optional channel demo"升级为 HLP 上
**可日常使用的独立 harness host**——四家 CLI（codex/pi/claude/kimi）经已有
harness adapters（投影+结构化输出+会话恢复/分叉）驱动，人通过终端完成完整
责任闭环。协议层零改动，全部工作在 `loops/tui/`。

## 现状缺口（代码实测）

已有：prompt/chat、流式渲染、inbox、approve/reject/choose/input、amend、
soft/promote、interrupt、review、audit、session 管理（new/resume/fork/archive）、
permission 档位。

缺口（按 harness 完整度排序）：

1. **Ctrl+C 不能夺取控制权**——live 等待中 KeyboardInterrupt 直接退出程序；
   正确语义是 `task.interrupt`（人发起中断，任务转 blocked，可恢复）。
2. **无任务切换**——只有"当前任务"；`/tasks`（列表）与 `/use <id>`（切换）缺失。
3. **无 handoff 命令**——ownership.transfer + 会话分叉能力已建成但未接入 UI。
4. **启动无恢复感**——启动总是新建空 session；无 `--resume <id>` 入口；
   启动后不展示未决 inbox（pending checkpoint/review）。
5. **Artifact 不可见**——review 前看不到交付物；缺 `/artifacts` 与 `/show <id>`。
6. **help 无分组**（26 个命令平铺）；`--model` 不通配（四家 CLI 都支持模型选择）。
7. **`/grant` 暂不可做**（PermissionGrant 在不可变 TaskSpec.constraints 内，
   无 post-create 加授权的协议操作——记为 spec gap，不在本次范围）。

## 实施步骤

### P0 harness 完整度（本轮全部完成）

1. **Ctrl+C → task.interrupt**：`run_with_progress` 包装层捕获
   KeyboardInterrupt → 有 active task 时 `client.interrupt(by=principal,
   prompt="user interrupt")`，渲染中断结果，session 继续；无 active task 才退出。
2. **`/tasks`**：列出全部 task（id/state/goal 截断/是否 active）；**`/use <id>`**：
   切换 active_task_id（校验存在与非终态），显示该 task 的 open inbox。
3. **`/handoff <agent_id>`**：`ownership.transfer`（harness fork 自动生效于
   pi/claude），渲染新 run 与接手 agent；活动 task 的后续 prompt 路由给新 run。
4. **启动恢复**：`--resume <session_id>` 直接进入已有 session（复用 SessionStore）；
   启动横幅统一显示 adapter/principal/session/未决 inbox 数；启动即渲染 open inbox。
5. **`/artifacts`**（任务产物列表）与 **`/show <artifact_id>`**（payload 详情：
   kind/uri/checksum/size/provenance/版本链）。

### P1 日用打磨（同轮完成）

6. `/help` 分组输出（Session / HLP 操作 / 控制 / 其它），每行一句。
7. `--model <name>` 透传到四家 CLI（codex `-m`、pi `--model`、claude `--model`、
   kimi `-m`；build_client 组合命令时追加，未指定不动现状）。

### 测试与验证

- 离线：`controller.handle` 驱动全部新命令（fake adapter + 注入 runner 的两家
  harness），断言状态与渲染文本；Ctrl+C 路径（mock interrupt）；`--model` 命令
  组合断言；启动横幅/inbox 渲染。
- 直播 smoke（本机）：`loops-hlp-tui --adapter pi` 一轮真实
  prompt→checkpoint→/approve→/handoff→/show；`--adapter claude` 同等冒烟
  （短时，各 ~2-3 次调用），结果记 notes。
- 回归：既有 310 测试零回归；mypy strict、ruff 全清。

### 文档

README TUI 段更新（新命令与 Ctrl+C 语义）、CHANGELOG、notes、plan 归档；
不改 spec/AGENTS.md 边界（TUI 仍是 optional host，只是变强）。

## 非目标

- 不做 MCP server 集成、不做 `/grant`（spec gap：TaskSpec 不可变，无加授权操作）。
- 不改 adapter/协议层；不重写渲染框架（保持行式渲染，不上 full-screen TUI 库）。
- 不做多窗口/鼠标/编辑器内嵌。
