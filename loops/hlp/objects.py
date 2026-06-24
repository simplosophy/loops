from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from ._ids import (
    gen_artifact_id,
    gen_checkpoint_id,
    gen_ledger_id,
    gen_task_id,
)
from .types import (
    CheckpointKind,
    CheckpointResolutionAction,
    CheckpointState,
    HumanInboxAction,
    HumanInboxKind,
    OwnershipTransferVia,
    ProtocolError,
    ReviewCommentSeverity,
    ReviewVerdict,
    TaskState,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ════════════════════════════════════════════════════════════
# 不可变值对象 (frozen) —— spec §2.3 前进性约束
# ════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class TaskSpec:
    """Task 的意图层。创建后不可变 (spec §3.2)。"""

    goal: str
    acceptance_criteria: tuple[str, ...] = ()
    inputs: tuple["InputRef", ...] = ()
    constraints: "Constraints | None" = None


@dataclass(frozen=True)
class InputRef:
    kind: Literal["artifact", "resource"]
    id: str | None = None        # kind=artifact 时为 art_
    version: str | None = None   # kind=artifact 时必填
    uri: str | None = None       # kind=resource 时必填


@dataclass(frozen=True)
class ExternalRef:
    """Opaque external evidence reference.

    HLP stores this for human decision and audit context; the host or lower
    protocol stack owns interpretation, authorization, and invocation.
    """

    kind: str
    namespace: str
    id: str
    version: str | None = None
    label: str | None = None


@dataclass(frozen=True)
class Constraints:
    max_duration: str | None = None
    external_refs: tuple[ExternalRef, ...] = ()


@dataclass(frozen=True)
class OwnershipTransfer:
    """ownership 转移链的一条记录 (spec §3.5)。"""

    from_: str
    to: str
    at: datetime = field(default_factory=_now)
    via: OwnershipTransferVia = "assign"


@dataclass(frozen=True)
class CheckpointOption:
    id: str
    label: str
    risk: Literal["low", "medium", "high"] = "medium"


@dataclass(frozen=True)
class Evidence:
    kind: Literal["artifact", "text"]
    id: str | None = None      # kind=artifact
    content: str | None = None  # kind=text


@dataclass(frozen=True)
class CheckpointResolution:
    by: str                     # 必须是人 (user_*)
    action: CheckpointResolutionAction
    choice: str | None = None   # action=choose 时
    input: str | None = None    # action=provide 时
    reassign_to: str | None = None  # action=reassign 时
    comment: str | None = None
    at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ReviewComment:
    anchor: str
    severity: ReviewCommentSeverity = "minor"
    body: str = ""


@dataclass(frozen=True)
class ArtifactProvenance:
    produced_by: str            # task_id
    produced_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ArtifactPayload:
    kind: Literal["diff", "blob", "ref", "inline"]
    uri: str
    checksum: str               # sha256:...
    size: int = 0


@dataclass(frozen=True)
class ArtifactRef:
    task_id: str
    as_: Literal["input", "output"] = "output"


@dataclass(frozen=True)
class LedgerEntry:
    key: str
    value: Any
    by: str                     # 写入者 task_id
    written_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class HumanInboxItem:
    """Projected human action item for UI/channel hosts.

    HLP owns the interaction semantics; host platforms still own rendering and
    delivery.
    """

    kind: HumanInboxKind
    action: HumanInboxAction
    task_id: str
    subject_id: str
    title: str
    principal: str
    created_at: datetime = field(default_factory=_now)


# ════════════════════════════════════════════════════════════
# 可变状态对象 —— 持有协议运行时状态
# ════════════════════════════════════════════════════════════


@dataclass
class Ownership:
    """可转移凭证 (spec §3.5)。principal 永不变，assignee 流转。"""

    principal: str              # 人, 永不变
    assignee: str               # 当前执行者
    delegable: bool = True
    chain: tuple[OwnershipTransfer, ...] = ()

    def transfer(
        self,
        to: str,
        via: OwnershipTransferVia,
    ) -> "Ownership":
        """返回转移后的新 Ownership（chain 追加一条）。"""
        return Ownership(
            principal=self.principal,
            assignee=to,
            delegable=self.delegable,
            chain=(*self.chain, OwnershipTransfer(from_=self.assignee, to=to, via=via)),
        )


@dataclass
class Task:
    """协议主语 (spec §3.2)。spec 创建后不可变，state/ownership 可流转。"""

    id: str = field(default_factory=gen_task_id)
    type: str = ""
    spec: TaskSpec = field(default_factory=lambda: TaskSpec(goal=""))
    ownership: Ownership = field(
        default_factory=lambda: Ownership(principal="", assignee="")
    )
    state: TaskState = "created"
    parent_task: str | None = None
    created_at: datetime = field(default_factory=_now)
    deadline: datetime | None = None
    checkpoints: list[str] = field(default_factory=list)     # ckpt_id 列表
    artifacts: list[str] = field(default_factory=list)       # art_id 列表

    @property
    def is_terminal(self) -> bool:
        return self.state in ("completed", "rejected")


@dataclass
class Checkpoint:
    """上行把关 (spec §3.4)。agent 声明，人回应。"""

    id: str = field(default_factory=gen_checkpoint_id)
    task_id: str = ""
    kind: CheckpointKind = "approval"
    prompt: str = ""
    options: tuple[CheckpointOption, ...] = ()
    context: tuple[Evidence, ...] = ()
    state: CheckpointState = "pending"
    raised_at: datetime = field(default_factory=_now)
    expires_at: datetime | None = None
    resolution: CheckpointResolution | None = None


@dataclass
class Review:
    """人对 Artifact 的结构化反馈 (spec §3.6)。提交后不可变。"""

    id: str = field(default_factory=lambda: "")
    task_id: str = ""
    artifact_id: str = ""
    reviewer: str = ""
    verdict: ReviewVerdict = "approved"
    comments: tuple[ReviewComment, ...] = ()
    requested_changes: tuple[str, ...] = ()
    at: datetime = field(default_factory=_now)
    _sealed: bool = field(default=False, repr=False)

    def __setattr__(self, name: str, value: Any) -> None:
        if name != "_sealed" and getattr(self, "_sealed", False):
            raise ProtocolError(
                "IMMUTABLE_VIOLATION",
                f"review {self.id} is sealed; cannot modify {name}",
            )
        object.__setattr__(self, name, value)

    def seal(self) -> "Review":
        """提交后封印，之后不可改 (spec §2.3)。"""
        object.__setattr__(self, "_sealed", True)
        return self


@dataclass
class Artifact:
    """独立生命周期的产物 (spec §3.7)。创建后不可变，要改产新版本。"""

    id: str = field(default_factory=gen_artifact_id)
    type: str = ""
    provenance: ArtifactProvenance | None = None
    version: str = "v1"
    parent_version: str | None = None
    payload: ArtifactPayload | None = None
    references: tuple[ArtifactRef, ...] = ()
    _sealed: bool = field(default=False, repr=False)

    def __setattr__(self, name: str, value: Any) -> None:
        if name != "_sealed" and getattr(self, "_sealed", False):
            raise ProtocolError(
                "IMMUTABLE_VIOLATION",
                f"artifact {self.id} is sealed; cannot modify {name}",
            )
        object.__setattr__(self, name, value)

    def seal(self) -> "Artifact":
        object.__setattr__(self, "_sealed", True)
        return self


@dataclass
class Ledger:
    """组织级状态沉淀 (spec §3.8)。append-only，永不删。"""

    id: str = field(default_factory=gen_ledger_id)
    scope: str = ""
    entries: dict[str, tuple[LedgerEntry, ...]] = field(default_factory=dict)

    def read(self, key: str) -> Any | None:
        history = self.entries.get(key, ())
        return history[-1].value if history else None

    def write(self, key: str, value: Any, by: str) -> LedgerEntry:
        """追加写入，读取时按 last-write-wins 取最新值。"""
        entry = LedgerEntry(key=key, value=value, by=by)
        self.entries[key] = (*self.entries.get(key, ()), entry)
        return entry

    def history(self, key: str) -> list[LedgerEntry]:
        return list(self.entries.get(key, ()))
