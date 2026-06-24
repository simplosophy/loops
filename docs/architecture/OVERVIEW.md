# HLP SDK Architecture Overview

本文定义当前项目的架构边界：Loops 只提供 Human Loop Protocol
(HLP) SDK，不再提供自研 agent harness。外部 harness 继续拥有模型调用、
工具执行、规划循环、memory、channel 和运行时生命周期；HLP 只统一这些
harness 暴露给人的交互语义。

## 核心定位

HLP 是 agent harness 的 human-interaction control plane：

```text
Human principal / reviewer
  -> HLP SDK: Task, Checkpoint, Artifact, Review, Ledger, Audit
  -> AgentAdapter / HarnessAdapter
  -> existing harness: Codex, Kimi, Claude Code, LangGraph, CrewAI, custom harness
```

HLP 的目标不是再造一个执行框架，而是让不同 harness 在人类委派、审批、
验收、审计这些语义上有一致的对象模型和操作顺序。

## HLP 拥有

- `Task`：人交给 agent 的有边界工作单元。
- `Ownership`：principal 不变、assignee 可流转的责任凭证。
- `Checkpoint`：agent 或 harness 需要人决策时形成的阻塞点。
- `Artifact` / `Review`：交付物及人的验收记录。
- `Ledger` / `Audit`：可累积、可重放、可审计的状态和事件。
- `HLPClient` / `HLPHost`：应用嵌入 HLP 的 SDK facade。
- `AgentAdapter`：HLP 向外部 harness 下发 delegate/block/resume/handoff/cancel。
- `HarnessAdapter`：外部 harness 将 human-facing 事件投影回 HLP。
- Store / EventBus：本地参考实现所需的状态和事件抽象。

## HLP 不拥有

- 模型 provider 抽象。
- tool/function/MCP/Skills 调用。
- agent planning loop。
- agent memory / RAG / prompt 组装。
- agent-to-agent 协议或 harness mesh。
- Web、IM、CLI、TUI 等 UI/channel 渲染与送达。
- 组织级身份、RBAC、计费、调度平台。

这些能力应由现有 harness、host application 或已有协议栈承担。HLP 只通过
窄 adapter contract 接入。

## 包结构

```text
loops/
  __init__.py          # HLP public API re-export
  hlp/
    __init__.py        # stable HLP SDK namespace
    host.py            # app embedding host
    _ids.py            # typed ULID helpers
    types.py           # ProtocolError + Literal aliases
    objects.py         # HLP objects and value objects
    state_machine.py   # Task transition table
    store.py           # in-memory reference store
    sqlite_store.py    # local snapshot store
    operations.py      # protocol operation layer
    sdk.py             # HLPClient facade
    adapters.py        # AgentAdapter / HarnessAdapter implementations
    events.py          # event bus abstractions
    audit.py           # append-only audit log
```

`loops.hlp` 当前承载 HLP 参考实现和稳定 SDK namespace。`loops` 顶层只
re-export 稳定公共 API。

## Adapter Boundary

HLP 有两个方向的 adapter：

| Adapter | 方向 | 作用 |
| --- | --- | --- |
| `AgentAdapter` | HLP -> harness | 委派任务、阻塞运行、恢复运行、handoff、取消运行 |
| `HarnessAdapter` | harness -> HLP | 把 harness 的人工审批、选择、输入、交付物事件投影为 HLP 对象 |

关键 invariant：

- `Task.id` 必须作为 runtime run 的 `correlation_id` 保留。
- `checkpoint.raise` 必须对应 harness 的 block/pause 语义。
- `checkpoint.resolve` 必须把人的决策传回 harness。
- harness 产出的 artifact 必须进入 HLP artifact/review 流程。
- adapter 失败必须 fail-before-commit，不能让 HLP 状态进入假成功。

## Human Inbox

HLP 只定义人需要处理什么，不定义 UI 长什么样：

```text
pending checkpoint -> HumanInboxItem(resolve_checkpoint)
review-ready artifact -> HumanInboxItem(submit_review)
```

Web、IM、CLI、桌面应用可以读取 `HLPClient.human_inbox(principal)`，再用自己的
channel 进行渲染和送达。

## 设计原则

- 极简：HLP SDK 只保留责任闭环必要对象和操作。
- 正交：协议对象、store、event bus、adapter、host 分开演进。
- 分层：HLP 不 import 或控制 harness 内部实现。
- Fail Fast：adapter 调用失败时，协议状态不推进。
- 约定优先：默认内存 store、fake adapter、demo 可直接跑；生产系统再替换后端。

## 验证路径

- SDK 单测验证对象、状态机、adapter、SQLite 和 demo。
- `loops-hlp-demo` 验证无外部依赖的人机闭环。
- `loops-hlp-adapters-demo` 验证 adapter contract。
- `loops-hlp-harness-demo` 验证外部 harness human-facing 事件投影。
- `loops-hlp-codex-harness-demo` 验证 Codex JSONL harness adapter 的端到端投影。
- 站点验证确保文档定位保持 HLP-first、SDK-only。
