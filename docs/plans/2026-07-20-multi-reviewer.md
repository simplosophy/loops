# Multi-Reviewer（§7.5 收敛）：评审聚合语义 + 参考实现

Date: 2026-07-20
Status: done (option A: veto-dominant; see docs/notes/2026-07-20.md)

## 背景

Spec §3.6/§7.5：多人 review 语义未定，当前假设单 reviewer——`review_submit` 的
verdict 立即驱动 Task 状态（approved→completed、changes_requested→返工、
rejected→终态）。本计划收敛 §7.5：定义确定性的多人聚合规则，保持 forward-only
与不可变约束，向后完全兼容（无 policy 时行为与现状逐字节一致）。

## 设计（spec 修订，0.2.0-draft 附录 B 记录）

**§3.2 TaskSpec** 新增可选字段 `review_policy`（创建后不可变，默认 `null`）：

```yaml
ReviewPolicy:
  required_reviewers: [user_]     # REQUIRED, 非空
  quorum: "all" | "majority" | "any"   # 默认 "all"
```

**§3.6 Review** 新增可选字段 `artifact_version`（提交时记录被评审 artifact 的
当前版本；聚合只计**当前版本**的评审——新版本提交后旧轮次评审自然失效，
forward-only 记录不删不改）。

**§3.6 聚合规则**（deliverable 且 task.spec.review_policy 非空时启用；kind=plan
维持逐条即时语义不变）：取每位 required reviewer 对当前 artifact 版本的**最新**
verdict（改意见=追加新 Review，§3.6 已有），按确定性优先级：

1. **veto**：任一 required reviewer 最新 verdict 为 `rejected` → 结果 `rejected`
   （Task→rejected 终态）
2. **quorum-approve**：`all`=全员 approved；`majority`=严格过半 approved；
   `any`=≥1 approved → 结果 `approved`（→accepted→completed）
3. **changes_requested**：任一 required reviewer 最新 verdict 为
   `changes_requested` → 立即返工（→in_progress，fail fast，不等齐）
4. 否则 → **pending**：Task 停留 under_review，等待剩余评审

**§4.3 前置条件**：policy 启用时 `reviewer ∈ required_reviewers`，否则
`UNAUTHORIZED`。**§7.5** 标注已收敛（reference 语义）。

### 备选 B（未选）：纯 quorum 无 veto

三种 verdict 全按 quorum 计票（rejected 也需过半才终态）。更"民主"，但责任闭环
协议里单个 reviewer 无法阻止风险交付，弱于 A 的安全语义。**推荐 A**。

## 实施步骤

1. **Spec**：`docs/specs/HLP.md` §3.2/§3.6/§4.3/§7.5/附录 B 修订 +
   `docs/site/specs/hlp.md` 同步（check_spec_site_sync 保持绿）。
2. **对象**：`objects.py` 加 `ReviewPolicy`；`TaskSpec.review_policy: ReviewPolicy |
   None = None`；`Review.artifact_version: str | None = None`。
3. **聚合**：`review.py` —— `evaluate_review_outcome(reviews, policy) ->
   "approved" | "rejected" | "changes_requested" | "pending"`；review_submit 在
   policy 路径下：校验 reviewer 成员、记录 artifact_version、按聚合结果转移
   （pending 时不转移、不产 task.completed 副作用 audit）。
4. **Wire**：ReviewPolicy JSON schema + `from_wire` 注册；transport dispatch 的
   task.create 增加 review_policy 构造。
5. **测试**（`tests/test_hlp_protocol.py` + 新聚合单测）：
   - 三种 quorum × approved / veto / changes / pending 全矩阵；
   - 非成员 reviewer → UNAUTHORIZED；changes_requested 缺 requested_changes → INVALID_SPEC（现有语义保持）；
   - 同 reviewer 追加新 verdict 覆盖旧值（latest wins）；
   - 新 artifact 版本提交后旧轮次评审不计入；
   - 无 policy 行为与现状完全一致（回归既有套件）；
   - wire round-trip（ReviewPolicy / 带 artifact_version 的 Review）。
6. **文档**：README review 段一句、CHANGELOG、notes、plan 归档。

## 非目标

- 不引入 reviewer 角色权重/委托评审（角色模型留给实现，§1.2 RBAC 边界）。
- kind=plan 评审不做聚合（工作流内部节点，维持即时语义）。
- 不改 Review 既有字段语义；无 policy 任务路径零变化。

## 验证

- 离线全量 pytest / mypy strict / ruff 绿；spec/site 同步检查与 release 元数据检查绿。
- 聚合矩阵单测全覆盖；既有 297 测试零回归。
