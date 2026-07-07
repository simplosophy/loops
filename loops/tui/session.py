from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TranscriptEvent:
    kind: str
    text: str
    at: str = field(default_factory=_now)
    ref: str = ""


@dataclass(frozen=True)
class TUISession:
    id: str
    cwd: str
    adapter: str
    principal: str = "user_local"
    active_task_id: str = ""
    active_run_id: str = ""
    permission_mode: str = "auto"
    model: str = ""
    theme: str = "system"
    composer_mode: str = "default"
    archived: bool = False
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    transcript: tuple[TranscriptEvent, ...] = ()


class SessionStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def create(self, *, cwd: str, adapter: str, principal: str = "user_local") -> TUISession:
        session = TUISession(
            id=self._next_id(),
            cwd=cwd,
            adapter=adapter,
            principal=principal,
        )
        self._put(session)
        return session

    def resume(self, session_id: str) -> TUISession:
        sessions = self._load()
        if session_id not in sessions:
            raise KeyError(f"unknown session: {session_id}")
        return sessions[session_id]

    def list(self) -> list[TUISession]:
        return sorted(self._load().values(), key=lambda item: item.updated_at)

    def append(self, session_id: str, event: TranscriptEvent) -> TUISession:
        session = self.resume(session_id)
        updated = self._replace(
            session,
            transcript=(*session.transcript, event),
            updated_at=_now(),
        )
        self._put(updated)
        return updated

    def set_active(self, session_id: str, *, task_id: str, run_id: str) -> TUISession:
        session = self.resume(session_id)
        updated = self._replace(
            session,
            active_task_id=task_id,
            active_run_id=run_id,
            updated_at=_now(),
        )
        self._put(updated)
        return updated

    def set_preference(self, session_id: str, *, field: str, value: str) -> TUISession:
        session = self.resume(session_id)
        allowed = {"permission_mode", "model", "theme", "composer_mode"}
        if field not in allowed:
            raise ValueError(f"unsupported preference: {field}")
        updated = self._replace(session, **{field: value, "updated_at": _now()})
        self._put(updated)
        return updated

    def clear_visible(self, session_id: str) -> TUISession:
        session = self.resume(session_id)
        updated = self._replace(session, transcript=(), updated_at=_now())
        self._put(updated)
        return updated

    def fork(self, session_id: str) -> TUISession:
        session = self.resume(session_id)
        forked = self._replace(
            session,
            id=self._next_id(),
            active_task_id="",
            active_run_id="",
            archived=False,
            created_at=_now(),
            updated_at=_now(),
        )
        self._put(forked)
        return forked

    def archive(self, session_id: str) -> TUISession:
        session = self.resume(session_id)
        updated = self._replace(session, archived=True, updated_at=_now())
        self._put(updated)
        return updated

    def delete(self, session_id: str) -> None:
        sessions = self._load()
        sessions.pop(session_id, None)
        self._save(sessions)

    def _put(self, session: TUISession) -> None:
        sessions = self._load()
        sessions[session.id] = session
        self._save(sessions)

    def _load(self) -> dict[str, TUISession]:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text())
        return {
            item["id"]: TUISession(
                **{
                    **item,
                    "transcript": tuple(
                        TranscriptEvent(**event) for event in item.get("transcript", ())
                    ),
                }
            )
            for item in data
        }

    def _save(self, sessions: dict[str, TUISession]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.tmp")
        payload = []
        for session in sorted(sessions.values(), key=lambda item: item.updated_at):
            row = asdict(session)
            row["transcript"] = [asdict(event) for event in session.transcript]
            payload.append(row)
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(self.path)

    @staticmethod
    def _replace(session: TUISession, **changes: object) -> TUISession:
        values = asdict(session)
        values.update(changes)
        values["transcript"] = tuple(
            event
            if isinstance(event, TranscriptEvent)
            else TranscriptEvent(**event)
            for event in values["transcript"]
        )
        return TUISession(**values)

    @staticmethod
    def _next_id() -> str:
        return f"tui_{uuid4().hex[:12]}"
