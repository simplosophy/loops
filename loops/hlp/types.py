from __future__ import annotations

from typing import Literal


HLP_SPEC_VERSION = "0.2.0-draft"
HLP_SCHEMA_VERSION = "0.2"
HLP_PROFILE = "HLP-industrial"


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
    "VERSION_UNSUPPORTED",
]

_RETRYABLE_ERROR_CODES = frozenset({"CONFLICT", "DEADLINE_EXCEEDED"})


class ProtocolError(Exception):
    """HLP 协议错误。code 对应 spec §6.1 错误码。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str = "",
        *,
        details: dict | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(f"[{code}] {message}" if message else code)
        self.code = code
        self.message = message
        self.details = details or {}
        self.retryable = retryable if retryable is not None else code in _RETRYABLE_ERROR_CODES

    def to_dict(
        self,
        *,
        operation_id: str | None = None,
        correlation_id: str | None = None,
    ) -> dict:
        """Return the stable wire shape for protocol errors."""
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "retryable": self.retryable,
            "operation_id": operation_id,
            "correlation_id": correlation_id,
            "spec_version": HLP_SPEC_VERSION,
            "schema_version": HLP_SCHEMA_VERSION,
            "profile": HLP_PROFILE,
        }


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

CheckpointKind = Literal["approval", "choice", "input", "escalation", "interrupt"]
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

AutonomyTier = Literal[
    "autonomous",
    "plan_then_implement",
    "confirm_each_action",
    "read_only",
]
PermissionGrantDecision = Literal["allow", "deny"]
SteeringIntent = Literal["redirect", "clarify", "constrain", "abort_hint"]
ProposedActionRisk = Literal["low", "medium", "high"]
ReviewKind = Literal["plan", "deliverable"]
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
