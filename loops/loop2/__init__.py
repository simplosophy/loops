"""loops.loop2 — HACP (Human-Agent Collaboration Protocol) reference implementation.

Loops Protocol Stack 的 L2 层：人机协作协议的参考实现。
对应 spec: docs/specs/HACP.md

本包不依赖 loop1/loop0 (分层纪律: 依赖只能向下)。
"""
from __future__ import annotations

from .audit import AuditEvent, AuditLog
from .contracts import AAPBridge, InMemoryAAPBridge
from .objects import (
    Artifact,
    ArtifactPayload,
    ArtifactProvenance,
    ArtifactRef,
    Checkpoint,
    CheckpointOption,
    CheckpointResolution,
    Constraints,
    Evidence,
    InputRef,
    Ledger,
    LedgerEntry,
    Ownership,
    OwnershipTransfer,
    Review,
    ReviewComment,
    Task,
    TaskSpec,
)
from .operations import HACPOperations
from .state_machine import LEGAL_TRANSITIONS, TERMINAL_STATES, check_transition, is_legal
from .store import HACPStore
from .types import (
    CheckpointKind,
    CheckpointResolutionAction,
    CheckpointState,
    ErrorCode,
    OwnershipTransferVia,
    ProtocolError,
    ReviewCommentSeverity,
    ReviewVerdict,
    TaskState,
)

__all__ = [
    # 操作 facade
    "HACPOperations",
    "HACPStore",
    # 契约
    "AAPBridge",
    "InMemoryAAPBridge",
    # 审计
    "AuditEvent",
    "AuditLog",
    # 对象
    "Task",
    "TaskSpec",
    "Checkpoint",
    "CheckpointOption",
    "CheckpointResolution",
    "Ownership",
    "OwnershipTransfer",
    "Review",
    "ReviewComment",
    "Artifact",
    "ArtifactPayload",
    "ArtifactProvenance",
    "ArtifactRef",
    "Ledger",
    "LedgerEntry",
    "Evidence",
    "InputRef",
    "Constraints",
    # 类型
    "TaskState",
    "CheckpointKind",
    "CheckpointState",
    "CheckpointResolutionAction",
    "OwnershipTransferVia",
    "ReviewVerdict",
    "ReviewCommentSeverity",
    "ErrorCode",
    "ProtocolError",
    # 状态机
    "LEGAL_TRANSITIONS",
    "TERMINAL_STATES",
    "check_transition",
    "is_legal",
]
