"""HLP (Human Loop Protocol) reference implementation.

当前目录承载 HLP SDK 的内部参考实现：协议对象、操作层、store、adapter
和 SDK facade。稳定公共入口是 `loops` / `loops.hlp`。
对应 spec: docs/specs/HLP.md

本包不依赖自研 agent harness；执行机制通过 adapter 接入外部 harness。
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
    FakeHarnessAdapter,
    HarnessAdapter,
    HarnessCapabilities,
    HarnessEvent,
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
    HumanInboxItem,
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
    HarnessConformance,
    HarnessEventKind,
    HumanInboxAction,
    HumanInboxKind,
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
    "FakeHarnessAdapter",
    "HarnessAdapter",
    "HarnessCapabilities",
    "HarnessEvent",
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
    "HumanInboxItem",
    # 类型
    "TaskState",
    "CheckpointKind",
    "CheckpointState",
    "CheckpointResolutionAction",
    "OwnershipTransferVia",
    "ReviewVerdict",
    "ReviewCommentSeverity",
    "HarnessConformance",
    "HarnessEventKind",
    "HumanInboxAction",
    "HumanInboxKind",
    "ErrorCode",
    "ProtocolError",
    # 状态机
    "LEGAL_TRANSITIONS",
    "TERMINAL_STATES",
    "check_transition",
    "is_legal",
]
