from __future__ import annotations

from .types import ProtocolError, TaskState

# Legal state transition table (spec §3.3)
# Any from→to transition not listed here is illegal and raises PRECONDITION_FAILED
LEGAL_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    "created": frozenset({"assigned", "completed"}),  # assign / cancel
    "assigned": frozenset({"in_progress", "completed"}),  # start / cancel
    "in_progress": frozenset({"blocked", "review_ready", "completed"}),
    "blocked": frozenset({"in_progress", "completed"}),  # resolve / cancel
    "review_ready": frozenset({"under_review"}),
    "under_review": frozenset({"in_progress", "accepted", "rejected"}),
    "accepted": frozenset({"completed"}),
    "rejected": frozenset(),  # terminal state
    "completed": frozenset(),  # terminal state
}

# Terminal states
TERMINAL_STATES: frozenset[TaskState] = frozenset({"completed", "rejected"})


def check_transition(current: TaskState, target: TaskState) -> None:
    """Validate a state transition; raise ProtocolError(PRECONDITION_FAILED) if illegal.

    Corresponds to the spec §4.3 preconditions + §6.1 error codes.
    """
    if current == target:
        return  # same-state is idempotent, not treated as illegal

    allowed = LEGAL_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise ProtocolError(
            "PRECONDITION_FAILED",
            f"illegal task state transition: {current!r} -> {target!r}",
        )


def is_legal(current: TaskState, target: TaskState) -> bool:
    """Non-validating variant, for queries."""
    if current == target:
        return True
    return target in LEGAL_TRANSITIONS.get(current, frozenset())
