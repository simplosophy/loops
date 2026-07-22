# Harness 聚合状态投影：RunProgress 与人侧进度界面

Date: 2026-07-21
Status: done (see docs/notes/2026-07-21.md)

## 问题与边界

Claude Code / Codex 等 harness 会动态更新有用的"聚合状态"：todo list 进度、
sub-agent 树运行情况。HLP 目前只有粗粒度 Task.state，人在两次 checkpoint 之间
看不到"agent 做到哪了"。

边界判断（第一性 + AGENTS.md）：todo list / sub-agent 树是 **harness planning
内部**，HLP **MUST NOT** 把它们升级为一等对象或进 spec/audit——它们正是附录 C
§C.2 定义的 channel/sensor plane 语义（高频、可丢、不作责任依据）。正确形态是
**投影**：adapter 把 wire 里已有的聚合状态解析成一个展示用的、临时的
（ephemeral）快照，人在 TUI 查看。协议层零改动。

## Wire 实证（本机探测）

| Harness | todo/plan 形状 | sub-agent 形状 |
|---|---|---|
| Codex | `item.started/completed` `item.type=="todo_list"`：`items:[{text,completed}]` | （exec 无原生子代理事件，v1 略） |
| Claude Code | assistant content `tool_use` `name=="TodoWrite"`：`input.todos:[{content,status,activeForm}]` | `tool_use name=="Task"` + `parent_tool_use_id` 链接 |
| Pi | wire 未观察到 todo 事件 | — |
| Kimi | wire 未观察到 todo 事件 | — |

## 设计

### 值对象（`loops/hlp/objects.py`，ephemeral 非一等对象，不入 audit）

```python
@dataclass(frozen=True)
class ProgressItem:
    label: str
    state: Literal["pending", "in_progress", "done", "blocked", "skipped"]
    note: str = ""

@dataclass(frozen=True)
class SubAgentStatus:
    id: str
    label: str
    state: Literal["running", "done", "failed"]
    parent_id: str | None = None

@dataclass(frozen=True)
class RunProgressSnapshot:
    run_id: str
    task_id: str
    updated_at: datetime
    summary: str = ""
    items: tuple[ProgressItem, ...] = ()
    agents: tuple[SubAgentStatus, ...] = ()
```

### Adapter 累积（`HarnessAdapterBase`，可选能力，复用现有事件流）

- `_run_progress: dict[run_id, RunProgressSnapshot]`：每次 `_execute` 解析后，
  按 CLI 各自的形状更新快照（与 human-event 投影同一遍解析，零额外进程）。
- **codex**：`todo_list` item → items（completed→done；首个未完成→in_progress）。
- **claude**：`TodoWrite` tool_use → items（status 映射）；`Task` tool_use →
  running agent；对应 `tool_result` → done；`parent_tool_use_id` → parent 链。
- **pi / kimi**：wire 无来源，`run_progress` 返回 `None`（文档注明 graceful
  fallback），将来 wire 长出即补。
- 新 adapter 表面：`run_progress(run_id) -> RunProgressSnapshot | None`
  （可选能力，同 peek/ack 的定位，不进 AgentAdapter 契约必选集）。

### 人侧界面

- `HLPClient.run_progress(run_id)` 门面：adapter 不支持时返回 None。
- TUI **`/progress`**：渲染当前 run 的 todo 清单（✓/◐/○）+ sub-agent 树；
  每次 prompt 完成后自动追加一行紧凑摘要（`progress 2/4 done · 1 agent running`）。
- render：`render_progress(snapshot)`（render.py，风格对齐现有渲染）。

## 实施步骤

1. `objects.py`：三个值对象 + wire/from_wire 注册（快照可序列化便于调试）。
2. `HarnessAdapterBase`：`_run_progress` 累积 + `run_progress` 方法 +
   codex/claude 两套形状解析（放 `_parsing.py` 辅助函数）。
3. `HLPClient.run_progress` 门面。
4. TUI：`/progress` 命令 + prompt 后自动紧凑摘要 + `render_progress`。
5. 测试（离线 fixture 驱动）：
   - codex todo_list 事件 → 快照 items/state 正确（含跨操作累积）；
   - claude TodoWrite/Task → items + agents + parent 链；
   - pi/kimi → None（fallback）；
   - `/progress` 渲染与 TUI handle 集成；
   - HLPClient 门面 adapter-unsupported → None。
6. 直播验证：codex `--json` 真实 plan 探测（已证实形状）走一遍 `/progress`；
   claude TodoWrite 探测同理。结果记 notes。
7. 文档：README（progress 段）、hlp.md（投影边界说明）、CHANGELOG、notes、
   plan 归档。**明确非目标**写入文档：progress 不作责任依据、不进 spec/audit/
   wire schema（§C.2 语义）。

## 非目标

- 不做一等 Plan/Todo 对象、不改 spec、不进 audit。
- 不做 pi/kimi 的 todo 支持（wire 无来源）；不做 codex 子代理（exec 无事件）。
- 不做进度回放/历史（快照只保留最新态；历史叙事仍走 audit）。
