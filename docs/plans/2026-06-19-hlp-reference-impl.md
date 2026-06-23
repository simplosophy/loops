# HLP 参考实现 — 实施计划

> 日期：2026-06-19
> 状态：已完成（代码 + 测试 + 文档全部落地）
> 规范：[`docs/specs/HLP.md`](../specs/HLP.md)

## 目标

在 `loops/loop2/` 下实现 HLP 0.1.0-draft 的最小可验证参考实现，验证 spec 可落地，为收敛开放议题提供基础。

## 范围

实现 spec §8 一致性级别全部 7 条硬指标：
1. 7 个一等对象（Task/Checkpoint/Ownership/Review/Artifact/Ledger/Audit）
2. 21 个操作
3. Task 状态机 §3.3（含合法转移校验）
4. 不可变性约束 §2.3
5. 每个操作产生 audit event §4.2
6. 操作前置条件 §4.3
7. 层间契约 §5（HLP→AAP stub，不实现 AAP 本身）

**不做**：transport 绑定、真实 AAP/CAP 实现真实执行、UI、真实持久化后端、CLI。这些是 spec §7 开放议题。

## 技术决策

- **风格**：stdlib dataclasses + `typing.Literal`（非 enum）+ `from __future__ import annotations`，严格对齐 `loops/loop0/` 现有风格，无 pydantic。
- **ID**：python-ulid 依赖 + 前缀（`task_` `ckpt_` 等），符合 spec §3.1。引入仓库第二个运行时依赖（首个是 jinja2），并显式补 typing-extensions（python-ulid 传递依赖，uv.lock 未自动解析）。
- **时间戳**：`datetime.now(timezone.utc)`，符合 RFC 3339。
- **持久化**：纯内存 HumanLoopStore + 可选 JSONL audit sink。
- **状态机**：显式 `LEGAL_TRANSITIONS` 转移表 dict + 非法转移抛 `ProtocolError(PRECONDITION_FAILED)`。
- **位置**：`loops/loop2/`（新建，不依赖 loop1/loop0）。
- **测试**：遵循 `tests/test_loops_core.py` 约定——同步 `def test_*` + `asyncio.run()` 驱动 async 操作，不引入 pytest-asyncio。
- **CLI**：本阶段不做，专注协议核心。

## 实施结果

### 包结构
```
loops/loop2/
  __init__.py, _ids.py, types.py, objects.py, state_machine.py,
  audit.py, store.py, contracts.py, operations.py
tests/test_loop2_hlp.py  (31 tests)
docs/architecture/loop2.md
docs/notes/2026-06-19.md
```

### 验证标准（全部达成）
- `uv run pytest tests/test_loop2_hlp.py -q`：31 passed
- 全仓库 `uv run pytest -q`：62 passed（含 loop0 现有 31）
- 端到端闭环覆盖 spec 附录 A "Review PR #1234" 全时序
- 非法状态转移被拦截并抛 PRECONDITION_FAILED
- 不可变对象封印（sealed）
- 每操作产生正确 action 的 audit event
- audit 可 replay 重建 Task 历史
- 不依赖 loop1/loop0（test_loop2_does_not_import_lower_layers）

### 实施中发现并修正的问题
1. **typing-extensions 传递依赖缺失**：python-ulid 3.1.0 需要 typing_extensions，但 uv add python-ulid 时 uv.lock 未解析到。显式 `uv add typing-extensions` 解决。
2. **LedgerEntry frozen 字段顺序**：frozen dataclass 要求无默认值字段在前，`by` 被 `written_at` 顶到后面，调整字段顺序。
3. **review_submit 状态机缺转移**：原实现直接从 review_ready 转 in_progress（changes_requested 时），但 spec §3.3 要求 review_ready→under_review→in_progress。修正为先转 under_review 再按 verdict 转。
4. **async 测试方式**：仓库无 pytest-asyncio，沿用 `tests/test_loops_core.py` 的同步 `def test_*` + `asyncio.run()` 模式。

## 开放议题的实证（待后续定论）

实现过程中暴露的真实约束：
- **checkpoint 并发**（spec §7.x）：参考实现假设单 pending checkpoint，`pending_checkpoint_of` 返回第一个。多并发需补充。
- **accepted→completed 自动化**：已在 2026-06-23 hardening pass 中实现，`review.approved` 会推进 `accepted → completed` 并写入 `task.completed` audit。
- **artifact 版本号**：用 task 的 artifacts 列表长度 +1，简单但非全局唯一。跨 task 同 artifact 需补逻辑。
- **ownership 转回 agent**：checkpoint resolve 时把 assignee 转回 principal 作占位（真实应转回原 agent）。后续需记录 original assignee。
