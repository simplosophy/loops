from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .audit import AuditLog
from .objects import (
    AdapterOutboxRecord,
    Artifact,
    ArtifactRef,
    Checkpoint,
    IdempotencyRecord,
    Ledger,
    Review,
    Task,
)
from .types import ProtocolError


def _snapshot[T](value: T) -> T:
    return deepcopy(value)


@dataclass
class HumanLoopStore:
    """In-memory store: the collection of all HLP objects (spec §3).

    The reference implementation uses pure in-memory dict/list, no persistence.
    A production implementation can swap in a SQLite/Postgres backend; the interface is unchanged.

    - tasks/checkpoints/artifacts/ledgers: indexed by id
    - reviews: indexed by id, with a reverse index by artifact_id
    - each getter raises ProtocolError("NOT_FOUND") on not_found
    """

    tasks: dict[str, Task] = field(default_factory=dict)
    checkpoints: dict[str, Checkpoint] = field(default_factory=dict)
    reviews: dict[str, Review] = field(default_factory=dict)
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    ledgers: dict[str, Ledger] = field(default_factory=dict)
    audit_log: AuditLog = field(default_factory=AuditLog)

    # artifacts are also indexed by the (id, version) pair (spec §3.7)
    _artifact_versions: dict[tuple[str, str], Artifact] = field(default_factory=dict, repr=False)
    # artifact reference is a consumption-relationship index; it does not modify the sealed Artifact itself
    _artifact_references: dict[str, tuple[ArtifactRef, ...]] = field(
        default_factory=dict, repr=False
    )
    # task → run_id mapping (maintained by operations, for checkpoint coordination)
    _task_runs: dict[str, str] = field(default_factory=dict, repr=False)
    # task-scoped idempotency records, keyed by (task_id, idempotency_key)
    _idempotency_records: dict[tuple[str, str], IdempotencyRecord] = field(
        default_factory=dict, repr=False
    )
    _adapter_outbox: dict[str, AdapterOutboxRecord] = field(default_factory=dict, repr=False)

    # ── Task ──
    def put_task(self, task: Task) -> None:
        self.tasks[task.id] = task

    def _get_task_for_update(self, task_id: str) -> Task:
        task = self.tasks.get(task_id)
        if task is None:
            raise ProtocolError("NOT_FOUND", f"task {task_id} not found")
        return task

    def get_task(self, task_id: str) -> Task:
        return _snapshot(self._get_task_for_update(task_id))

    def list_tasks(self) -> list[Task]:
        return [_snapshot(task) for task in self.tasks.values()]

    def bump_task_revision(self, task: Task) -> None:
        task.revision += 1

    def get_idempotency_record(
        self,
        task_id: str,
        key: str,
    ) -> IdempotencyRecord | None:
        record = self._idempotency_records.get((task_id, key))
        return _snapshot(record) if record is not None else None

    def put_idempotency_record(self, record: IdempotencyRecord) -> None:
        self._idempotency_records[(record.task_id, record.key)] = record

    def put_adapter_outbox_record(self, record: AdapterOutboxRecord) -> None:
        self._adapter_outbox[record.operation_id] = record

    def get_adapter_outbox_record(self, operation_id: str) -> AdapterOutboxRecord:
        record = self._adapter_outbox.get(operation_id)
        if record is None:
            raise ProtocolError("NOT_FOUND", f"adapter outbox {operation_id} not found")
        return _snapshot(record)

    def _get_adapter_outbox_record_for_update(self, operation_id: str) -> AdapterOutboxRecord:
        record = self._adapter_outbox.get(operation_id)
        if record is None:
            raise ProtocolError("NOT_FOUND", f"adapter outbox {operation_id} not found")
        return record

    def mark_adapter_outbox_succeeded(
        self,
        operation_id: str,
        *,
        result: object = None,
    ) -> None:
        record = self._get_adapter_outbox_record_for_update(operation_id)
        record.result = result
        record.state = "succeeded"
        record.updated_at = datetime.now(UTC)

    def adapter_outbox_records(self) -> list[AdapterOutboxRecord]:
        return [_snapshot(record) for record in self._adapter_outbox.values()]

    # ── Checkpoint ──
    def put_checkpoint(self, ckpt: Checkpoint) -> None:
        self.checkpoints[ckpt.id] = ckpt

    def _get_checkpoint_for_update(self, ckpt_id: str) -> Checkpoint:
        ckpt = self.checkpoints.get(ckpt_id)
        if ckpt is None:
            raise ProtocolError("NOT_FOUND", f"checkpoint {ckpt_id} not found")
        return ckpt

    def get_checkpoint(self, ckpt_id: str) -> Checkpoint:
        return _snapshot(self._get_checkpoint_for_update(ckpt_id))

    def pending_checkpoint_of(self, task_id: str) -> Checkpoint | None:
        """Return the task's currently pending checkpoint (reference implementation assumes a single checkpoint)."""
        for ckpt in self.checkpoints.values():
            if ckpt.task_id == task_id and ckpt.state == "pending":
                return _snapshot(ckpt)
        return None

    # ── Review ──
    def put_review(self, review: Review) -> None:
        self.reviews[review.id] = review

    def _get_review_for_update(self, review_id: str) -> Review:
        r = self.reviews.get(review_id)
        if r is None:
            raise ProtocolError("NOT_FOUND", f"review {review_id} not found")
        return r

    def get_review(self, review_id: str) -> Review:
        return _snapshot(self._get_review_for_update(review_id))

    def reviews_of_artifact(self, artifact_id: str) -> list[Review]:
        return [_snapshot(r) for r in self.reviews.values() if r.artifact_id == artifact_id]

    # ── Artifact ──
    def put_artifact(self, art: Artifact) -> None:
        self.artifacts[art.id] = art
        self._artifact_versions[(art.id, art.version)] = art

    def _get_artifact_for_update(self, art_id: str, version: str | None = None) -> Artifact:
        if version is not None:
            art = self._artifact_versions.get((art_id, version))
            if art is None:
                raise ProtocolError("NOT_FOUND", f"artifact {art_id}@{version} not found")
            return art
        art = self.artifacts.get(art_id)
        if art is None:
            raise ProtocolError("NOT_FOUND", f"artifact {art_id}@{version} not found")
        return art

    def get_artifact(self, art_id: str, version: str | None = None) -> Artifact:
        return _snapshot(self._get_artifact_for_update(art_id, version))

    def artifact_versions(self, art_id: str) -> list[Artifact]:
        """Return all versions of an artifact, ordered by version time."""
        return [_snapshot(a) for (aid, _v), a in self._artifact_versions.items() if aid == art_id]

    def add_artifact_reference(self, art_id: str, ref: ArtifactRef) -> None:
        self.get_artifact(art_id)
        self._artifact_references[art_id] = (
            *self._artifact_references.get(art_id, ()),
            ref,
        )

    def artifact_references(self, art_id: str) -> list[ArtifactRef]:
        self.get_artifact(art_id)
        return [_snapshot(ref) for ref in self._artifact_references.get(art_id, ())]

    # ── Ledger ──
    def put_ledger(self, ledger: Ledger) -> None:
        self.ledgers[ledger.id] = ledger

    def _get_ledger_for_update(self, ledger_id: str) -> Ledger:
        ledger = self.ledgers.get(ledger_id)
        if ledger is None:
            raise ProtocolError("NOT_FOUND", f"ledger {ledger_id} not found")
        return ledger

    def get_ledger(self, ledger_id: str) -> Ledger:
        return _snapshot(self._get_ledger_for_update(ledger_id))

    def find_ledger_by_scope(self, scope: str) -> Ledger | None:
        for ledger in self.ledgers.values():
            if ledger.scope == scope:
                return _snapshot(ledger)
        return None

    def _find_ledger_by_scope_for_update(self, scope: str) -> Ledger | None:
        for ledger in self.ledgers.values():
            if ledger.scope == scope:
                return ledger
        return None

    def get_or_create_ledger(self, scope: str) -> Ledger:
        ledger = self._find_ledger_by_scope_for_update(scope)
        if ledger is not None:
            return ledger
        ledger = Ledger(scope=scope)
        self.put_ledger(ledger)
        return ledger

    # ── Task↔Run mapping (for checkpoint coordination) ──
    def bind_run(self, task_id: str, run_id: str) -> None:
        self._task_runs[task_id] = run_id

    def run_of_task(self, task_id: str) -> str | None:
        return self._task_runs.get(task_id)

    def task_of_run(self, run_id: str) -> str | None:
        for task_id, bound_run in self._task_runs.items():
            if bound_run == run_id:
                return task_id
        return None
