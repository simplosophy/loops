# HLP SDK Stack Architecture

> **2026-06-24 定位更新**：Loops 不再维护自研 agent harness，也不再把
> 历史三层运行时命名作为要落地的框架。项目聚焦 HLP SDK：
> 统一人类交互语义，包裹既有 harness，复用既有 agent/capability 协议栈。

## Stack Model

```text
┌──────────────────────────────────────────────────────────────┐
│ Human-facing applications                                     │
│ Web, IM, CLI, IDE, task systems, project platforms             │
├──────────────────────────────────────────────────────────────┤
│ HLP SDK                                                       │
│ Task · Ownership · Checkpoint · Artifact · Review · Ledger     │
│ Audit · HumanInbox · HLPClient · HLPHost                       │
├──────────────────────────────────────────────────────────────┤
│ Adapter contracts                                             │
│ AgentAdapter: delegate/block/resume/handoff/cancel             │
│ HarnessAdapter: observe human-facing harness events            │
├──────────────────────────────────────────────────────────────┤
│ Existing agent harnesses                                      │
│ Codex · Kimi · Claude Code · OpenAI Agents SDK · LangGraph     │
│ CrewAI · custom in-house runtimes                              │
├──────────────────────────────────────────────────────────────┤
│ Existing capability ecosystems                                │
│ MCP · Agent Skills · local tools · function calling · APIs      │
└──────────────────────────────────────────────────────────────┘
```

HLP lives above existing harnesses. It does not absorb their execution model; it
only requires enough correlation and pause/resume semantics to make human
responsibility auditable.

## What Changed

Earlier design notes treated `loop0` as a minimal single-agent runtime and
`loop1` as a user interaction container. That direction duplicated the role of
real harnesses and pulled the project away from the protocol gap HLP should
own. The current architecture removes the self-implemented harness from the
product and repository.

Current rule:

- HLP SDK is the product.
- Existing harnesses own execution.
- L1 and L0 docs are routing references to existing protocols, not Loops-owned
  protocols.
- Public imports go through `loops` or `loops.hlp`.

## HLP SDK Responsibilities

- Create and track human-owned tasks.
- Delegate tasks to external harnesses through `AgentAdapter`.
- Project harness approval/input/artifact events through `HarnessAdapter`.
- Block work at checkpoints until a human decision is recorded.
- Expose a unified human inbox for host UIs.
- Commit artifacts and collect human reviews.
- Maintain append-only ledger and audit trails.

## External Harness Responsibilities

- Select models, prompts, tools, skills, and memory.
- Run planning and execution loops.
- Invoke capabilities through MCP, Skills, local tools, APIs, or custom systems.
- Manage runtime lifecycle, retries, streaming, logs, and internal state.
- Render or deliver UI if the host chooses to keep UI outside HLP.

## Integration Invariants

| Invariant | Reason |
| --- | --- |
| `Task.id == Run.correlation_id` | Audit replay must connect human work to harness runs. |
| Checkpoints map to harness block/resume | Human decisions must be authoritative. |
| Artifacts enter HLP review flow | Delivery and acceptance must be independent of harness internals. |
| Adapter failure is fail-before-commit | HLP state must not claim work moved when the harness rejected it. |
| Capability references hide transport | HLP should not know whether a capability came from MCP, Skills, local tools, or APIs. |

## Internal Package Notes

`loops.hlp` is the current implementation directory for HLP objects,
operations, store, adapters, host, and SDK facade.

There is intentionally no `loops.loop0` harness in the current architecture.
Projects that need execution should connect an existing harness through
`AgentAdapter` or `HarnessAdapter`.

## Open Design Questions

- Whether `HarnessAdapter.observe(run_id)` should remain pull-based only or add
  an async event stream interface.
- How much conformance metadata a harness should expose beyond the current
  capability labels.
- Whether production HLP services should standardize a durable outbox contract
  for adapter calls.
- How host applications should map `HumanInboxItem` into web, IM, IDE, and CLI
  interaction patterns without HLP becoming a UI protocol.
