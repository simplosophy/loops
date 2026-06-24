from __future__ import annotations

from .types import ProtocolError, TaskState


# 合法状态转移表 (spec §3.3)
# 未列出的 from→to 转移非法，抛 PRECONDITION_FAILED
LEGAL_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    "created": frozenset({"assigned", "completed"}),          # assign / cancel
    "assigned": frozenset({"in_progress", "completed"}),      # start / cancel
    "in_progress": frozenset({"blocked", "review_ready", "completed"}),
    "blocked": frozenset({"in_progress", "completed"}),       # resolve / cancel
    "review_ready": frozenset({"under_review"}),
    "under_review": frozenset({"in_progress", "accepted", "rejected"}),
    "accepted": frozenset({"completed"}),
    "rejected": frozenset(),      # 终态
    "completed": frozenset(),     # 终态
}

# 终态
TERMINAL_STATES: frozenset[TaskState] = frozenset({"completed", "rejected"})


def check_transition(current: TaskState, target: TaskState) -> None:
    """校验状态转移合法性，非法则抛 ProtocolError(PRECONDITION_FAILED)。

    对应 spec §4.3 前置条件 + §6.1 错误码。
    """
    if current == target:
        return  # 同状态幂等，不视为非法

    allowed = LEGAL_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise ProtocolError(
            "PRECONDITION_FAILED",
            f"illegal task state transition: {current!r} -> {target!r}",
        )


def is_legal(current: TaskState, target: TaskState) -> bool:
    """非校验版，用于查询。"""
    if current == target:
        return True
    return target in LEGAL_TRANSITIONS.get(current, frozenset())
