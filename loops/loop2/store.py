from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .audit import AuditLog
from .objects import Artifact, ArtifactRef, Checkpoint, Ledger, Review, Task
from .types import ProtocolError


@dataclass
class HumanLoopStore:
    """内存存储：所有 HLP 对象的集合 (spec §3)。

    参考实现用纯内存 dict/list，不持久化。生产实现可替换为
    SQLite/Postgres 后端，接口不变。

    - tasks/checkpoints/artifacts/ledgers: 按 id 索引
    - reviews: 按 id 索引，同时按 artifact_id 反向索引
    - 各 getter 在 not_found 时抛 ProtocolError("NOT_FOUND")
    """

    tasks: dict[str, Task] = field(default_factory=dict)
    checkpoints: dict[str, Checkpoint] = field(default_factory=dict)
    reviews: dict[str, Review] = field(default_factory=dict)
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    ledgers: dict[str, Ledger] = field(default_factory=dict)
    audit_log: AuditLog = field(default_factory=AuditLog)

    # artifacts 按 (id, version) 二元组也建索引（spec §3.7）
    _artifact_versions: dict[tuple[str, str], Artifact] = field(default_factory=dict, repr=False)
    # artifact reference 是消费关系索引，不修改已封印 Artifact 本体
    _artifact_references: dict[str, tuple[ArtifactRef, ...]] = field(default_factory=dict, repr=False)
    # task 的 run_id 映射（由 operations 维护，用于 checkpoint 联动）
    _task_runs: dict[str, str] = field(default_factory=dict, repr=False)

    # ── Task ──
    def put_task(self, task: Task) -> None:
        self.tasks[task.id] = task

    def get_task(self, task_id: str) -> Task:
        task = self.tasks.get(task_id)
        if task is None:
            raise ProtocolError("NOT_FOUND", f"task {task_id} not found")
        return task

    def list_tasks(self) -> list[Task]:
        return list(self.tasks.values())

    # ── Checkpoint ──
    def put_checkpoint(self, ckpt: Checkpoint) -> None:
        self.checkpoints[ckpt.id] = ckpt

    def get_checkpoint(self, ckpt_id: str) -> Checkpoint:
        ckpt = self.checkpoints.get(ckpt_id)
        if ckpt is None:
            raise ProtocolError("NOT_FOUND", f"checkpoint {ckpt_id} not found")
        return ckpt

    def pending_checkpoint_of(self, task_id: str) -> Checkpoint | None:
        """返回 task 当前 pending 的 checkpoint（参考实现假设单 checkpoint）。"""
        for ckpt in self.checkpoints.values():
            if ckpt.task_id == task_id and ckpt.state == "pending":
                return ckpt
        return None

    # ── Review ──
    def put_review(self, review: Review) -> None:
        self.reviews[review.id] = review

    def get_review(self, review_id: str) -> Review:
        r = self.reviews.get(review_id)
        if r is None:
            raise ProtocolError("NOT_FOUND", f"review {review_id} not found")
        return r

    def reviews_of_artifact(self, artifact_id: str) -> list[Review]:
        return [r for r in self.reviews.values() if r.artifact_id == artifact_id]

    # ── Artifact ──
    def put_artifact(self, art: Artifact) -> None:
        self.artifacts[art.id] = art
        self._artifact_versions[(art.id, art.version)] = art

    def get_artifact(self, art_id: str, version: str | None = None) -> Artifact:
        if version is not None:
            art = self._artifact_versions.get((art_id, version))
            if art is not None:
                return art
        art = self.artifacts.get(art_id)
        if art is None:
            raise ProtocolError("NOT_FOUND", f"artifact {art_id}@{version} not found")
        return art

    def artifact_versions(self, art_id: str) -> list[Artifact]:
        """返回某 artifact 的所有版本，按版本时间序。"""
        return [a for (aid, _v), a in self._artifact_versions.items() if aid == art_id]

    def add_artifact_reference(self, art_id: str, ref: ArtifactRef) -> None:
        self.get_artifact(art_id)
        self._artifact_references[art_id] = (
            *self._artifact_references.get(art_id, ()),
            ref,
        )

    def artifact_references(self, art_id: str) -> list[ArtifactRef]:
        self.get_artifact(art_id)
        return list(self._artifact_references.get(art_id, ()))

    # ── Ledger ──
    def put_ledger(self, ledger: Ledger) -> None:
        self.ledgers[ledger.id] = ledger

    def get_ledger(self, ledger_id: str) -> Ledger:
        ledger = self.ledgers.get(ledger_id)
        if ledger is None:
            raise ProtocolError("NOT_FOUND", f"ledger {ledger_id} not found")
        return ledger

    def find_ledger_by_scope(self, scope: str) -> Ledger | None:
        for ledger in self.ledgers.values():
            if ledger.scope == scope:
                return ledger
        return None

    def get_or_create_ledger(self, scope: str) -> Ledger:
        ledger = self.find_ledger_by_scope(scope)
        if ledger is not None:
            return ledger
        ledger = Ledger(scope=scope)
        self.put_ledger(ledger)
        return ledger

    # ── Task↔Run 映射 (供 checkpoint 联动) ──
    def bind_run(self, task_id: str, run_id: str) -> None:
        self._task_runs[task_id] = run_id

    def run_of_task(self, task_id: str) -> str | None:
        return self._task_runs.get(task_id)
