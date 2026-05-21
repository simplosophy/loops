"""Long-lived Agent state model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from loop0.types import Message


@dataclass
class MemoryRecord:
    """Minimal long-term memory unit."""

    content: str
    scope: str = "agent"
    kind: str = "fact"
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    importance: float = 0.5
    pinned: bool = False
    expires_at: datetime | None = None
    id: str = field(default_factory=lambda: f"mem_{uuid4().hex[:12]}")
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_active(self, *, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return True
        return self.expires_at > (now or datetime.now(timezone.utc))

    def matches(self, query: str) -> bool:
        if not query:
            return self.is_active()
        return self.is_active() and query.lower() in self.content.lower()

    def render_for_prompt(self) -> str:
        return self.content


@dataclass
class ThreadState:
    thread_id: str
    messages: list[Message] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AgentState:
    """Long-lived state associated with one Agent."""

    agent_id: str = field(default_factory=lambda: f"agent_{uuid4().hex[:12]}")
    threads: dict[str, ThreadState] = field(default_factory=dict)
    memories: dict[str, MemoryRecord] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    component_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    checkpoints: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def append_message(self, thread_id: str, message: Message) -> None:
        thread = self.threads.setdefault(thread_id, ThreadState(thread_id=thread_id))
        thread.messages.append(message)
        thread.updated_at = datetime.now(timezone.utc)
        self.updated_at = thread.updated_at

    def get_history(self, thread_id: str, window: int | None = None) -> list[Message]:
        messages = list(self.threads.get(thread_id, ThreadState(thread_id)).messages)
        if window is not None and window >= 0:
            return messages[-window:]
        return messages

    def remember(self, record: MemoryRecord | str, **kwargs: Any) -> MemoryRecord:
        memory = record if isinstance(record, MemoryRecord) else MemoryRecord(content=str(record), **kwargs)
        self.memories[memory.id] = memory
        self.updated_at = datetime.now(timezone.utc)
        return memory

    def recall(self, query: str = "", *, scope: str | None = None, limit: int = 10) -> list[MemoryRecord]:
        matches = [
            memory
            for memory in self.memories.values()
            if memory.matches(query) and (scope is None or memory.scope == scope)
        ]
        matches.sort(key=lambda item: (item.pinned, item.importance, item.updated_at), reverse=True)
        return matches[:limit]

    def forget(self, memory_id: str) -> bool:
        removed = self.memories.pop(memory_id, None) is not None
        if removed:
            self.updated_at = datetime.now(timezone.utc)
        return removed

    def compact(self, thread_id: str, *, keep_last: int = 20) -> None:
        thread = self.threads.get(thread_id)
        if thread is None or len(thread.messages) <= keep_last:
            return
        thread.messages = thread.messages[-keep_last:]
        thread.updated_at = datetime.now(timezone.utc)
        self.updated_at = thread.updated_at

    def snapshot(self) -> "AgentState":
        import copy

        return copy.deepcopy(self)

    def restore(self, snapshot: "AgentState") -> None:
        self.agent_id = snapshot.agent_id
        self.threads = snapshot.threads
        self.memories = snapshot.memories
        self.artifacts = snapshot.artifacts
        self.component_state = snapshot.component_state
        self.checkpoints = snapshot.checkpoints
        self.updated_at = datetime.now(timezone.utc)
