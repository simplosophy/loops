"""loops.loop2 — HLP (Human Loop Protocol) reference implementation.

Loops Protocol Stack 的 L2 层：人机责任闭环协议的参考实现。
对应 spec: docs/specs/HLP.md

本包不依赖 loop1/loop0 (分层纪律: 依赖只能向下)。
"""
from __future__ import annotations

from .adapters import (
    AgentAdapter,
    AgentAdapterError,
    AgentRunHandle,
    ClaudeCodeCLIAdapter,
    CodexCLIAdapter,
    CrewAIAdapter,
    FakeAgentAdapter,
    HermesCLIAdapter,
    HermsCLIAdapter,
    InMemoryAgentAdapter,
    KimiCLIAdapter,
    LangGraphAdapter,
    OpenAIAgentsSDKAdapter,
    OpenAIPythonSDKAdapter,
    PromptCLIAdapter,
    ProcessResult,
    ProcessAgentAdapter,
    PythonCallableAgentAdapter,
)
from .audit import AuditEvent, AuditLog
from .events import EventBus, HLPEvent, InMemoryEventBus
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
from .operations import HumanLoopOperations
from .sdk import HLPClient
from .sqlite_store import SQLiteHumanLoopStore
from .state_machine import LEGAL_TRANSITIONS, TERMINAL_STATES, check_transition, is_legal
from .store import HumanLoopStore
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
    "HLPClient",
    "HumanLoopOperations",
    "HumanLoopStore",
    # 契约
    "AgentAdapter",
    "AgentAdapterError",
    "AgentRunHandle",
    "ClaudeCodeCLIAdapter",
    "CodexCLIAdapter",
    "CrewAIAdapter",
    "FakeAgentAdapter",
    "HermesCLIAdapter",
    "HermsCLIAdapter",
    "InMemoryAgentAdapter",
    "KimiCLIAdapter",
    "LangGraphAdapter",
    "OpenAIAgentsSDKAdapter",
    "OpenAIPythonSDKAdapter",
    "PromptCLIAdapter",
    "ProcessResult",
    "ProcessAgentAdapter",
    "PythonCallableAgentAdapter",
    # 事件
    "EventBus",
    "HLPEvent",
    "InMemoryEventBus",
    # 持久化
    "SQLiteHumanLoopStore",
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
