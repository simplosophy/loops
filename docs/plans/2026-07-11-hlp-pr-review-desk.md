# HLP Real Host Case: PR Review Desk

| | |
|---|---|
| **日期** | 2026-07-11 |
| **状态** | 已完成 |
| **关联** | `docs/plans/2026-07-11-hlp-engineering-cleanup.md` 后续：真实宿主落地 |

## 目标

交付一个**宿主应用**示例，证明 HLP 以 SDK 方式被嵌入，而不是再做一个 adapter smoke demo。

场景：工程团队的 **PR Review Desk**（PR 评审审批台）。

```text
Reviewer / principal (人)
  -> PRReviewDesk (host application)
       owns: PR domain, inbox cards, desk summary, SQLite path
  -> HLPHost / HLPClient (control plane)
       owns: Task, Checkpoint, Artifact, Review, Ledger, Audit
  -> CodexHarnessAdapter (first-class harness boundary)
  -> external code-review harness (offline injectable runner or real CLI)
```

## Host vs HLP vs Harness

| 层 | 负责 | 不负责 |
|---|---|---|
| `PRReviewDesk` | PR 领域模型、收件箱卡片、审批动作编排、报告展示 | 模型调用、工具执行 |
| HLP | 委派/阻塞/恢复/验收/审计语义 | UI 渲染、GitHub API |
| Harness adapter | run correlation、human-facing event 投影 | HLP 状态机本身 |

## 闭环流程

1. principal 打开 PR → host 创建 HLP Task（goal/acceptance 从 PR 生成）
2. desk 委派 code-review agent → harness `delegate` + `start`
3. harness 投影 `needs_approval`（例如是否允许在 PR 上发表评注）
4. host 从 `human_inbox` 渲染 DeskCard，principal 决策
5. `resolve_checkpoint` → harness `resume`
6. harness 投影 review report artifact
7. reviewer 对 deliverable 提交 Review
8. host 写 Ledger（PR 决策状态）并 `replay_audit`

可选：中途 `task.amend` 转向（聚焦 auth/权限），证明 continuous control。

## 交付物

- `examples/hlp_pr_review_desk.py`：宿主实现 + offline demo runner
- console script：`loops-hlp-pr-desk`
- offline 单测覆盖完整闭环
- README / notes 说明“如何把 HLP 嵌进自家 host”

## 非目标

- 不接真实 GitHub API
- 不做 Web UI
- 不把 desk 逻辑塞进 `loops.hlp` core
- 不默认依赖本机 Codex（offline 注入 runner；真 CLI 走 opt-in）

## 完成定义

- offline 可复现：创建 PR → 审批 → 验收 → ledger/audit
- 测试不访问外网
- 文档明确 host 边界与复用方式
