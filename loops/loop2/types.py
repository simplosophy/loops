from __future__ import annotations

from typing import Literal


# ── 错误码 (HLP spec §6.1) ──
ErrorCode = Literal[
    "INVALID_SPEC",
    "PRECONDITION_FAILED",
    "UNAUTHORIZED",
    "NOT_FOUND",
    "CONFLICT",
    "IMMUTABLE_VIOLATION",
    "DEADLINE_EXCEEDED",
    "CHECKPOINT_EXPIRED",
]


class ProtocolError(Exception):
    """HLP 协议错误。code 对应 spec §6.1 错误码。"""

    def __init__(self, code: ErrorCode, message: str = "") -> None:
        super().__init__(f"[{code}] {message}" if message else code)
        self.code = code
        self.message = message


# ── Literal 类型别名 (spec §3) ──

TaskState = Literal[
    "created",
    "assigned",
    "in_progress",
    "blocked",
    "review_ready",
    "under_review",
    "accepted",
    "rejected",
    "completed",
]

CheckpointKind = Literal["approval", "choice", "input", "escalation"]
CheckpointState = Literal["pending", "resolved", "expired"]

CheckpointResolutionAction = Literal[
    "approve",
    "reject",
    "choose",
    "provide",
    "reassign",
]

OwnershipTransferVia = Literal[
    "assign",
    "checkpoint",
    "approve",
    "reject",
    "handoff",
]

ReviewVerdict = Literal["approved", "changes_requested", "rejected"]
ReviewCommentSeverity = Literal["blocker", "major", "minor", "nit"]

HarnessConformance = Literal[
    "delegate-only",
    "checkpoint-capable",
    "artifact-aware",
    "event-streaming",
    "full-hlp",
]

HarnessEventKind = Literal[
    "needs_approval",
    "needs_choice",
    "needs_input",
    "artifact",
]

HumanInboxKind = Literal["checkpoint", "review"]
HumanInboxAction = Literal["resolve_checkpoint", "submit_review"]
