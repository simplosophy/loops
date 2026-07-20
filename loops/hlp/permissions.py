from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from .types import ProtocolError

_SCOPE_RE = re.compile(r"^[a-z][a-z0-9_-]*:[^\s]+$")


def normalize_permission_scope(scope: str) -> str:
    """Normalize and validate an HLP permission scope string."""
    normalized = scope.strip()
    if normalized == "*":
        return normalized
    if not normalized or _SCOPE_RE.fullmatch(normalized) is None:
        raise ProtocolError(
            "INVALID_SPEC",
            "permission scope must be '<namespace>:<target>' with no whitespace",
        )
    if "*" in normalized and not normalized.endswith("*"):
        raise ProtocolError(
            "INVALID_SPEC",
            "permission scope wildcard is only allowed as a suffix",
        )
    return normalized


def permission_scope_matches(grant_scope: str, requested_scope: str) -> bool:
    grant = normalize_permission_scope(grant_scope)
    requested = normalize_permission_scope(requested_scope)
    if grant == "*":
        return True
    if grant.endswith("*"):
        prefix = grant[:-1]
        if requested.startswith(prefix):
            return True
        if prefix.endswith(":"):
            return requested.startswith(f"{prefix[:-1]}/")
        return False
    return grant == requested


def is_permission_scope_pre_authorized(
    grants: tuple[Any, ...],
    requested_scope: str,
    *,
    at: datetime | None = None,
) -> bool:
    """Return whether active grants pre-authorize a scope.

    Active matching denies take precedence over active matching allows.
    """
    checked_at = at or datetime.now(UTC)
    requested = normalize_permission_scope(requested_scope)
    matching = [
        grant
        for grant in grants
        if _grant_is_active(grant, checked_at)
        and permission_scope_matches(str(grant.scope), requested)
    ]
    if any(grant.decision == "deny" for grant in matching):
        return False
    return any(grant.decision == "allow" for grant in matching)


def _grant_is_active(grant: Any, at: datetime) -> bool:
    until = grant.until
    if until in ("task", "session"):
        return True
    if isinstance(until, datetime):
        return at <= until
    raise ProtocolError(
        "INVALID_SPEC",
        "permission grant until must be 'task', 'session', or timestamp",
    )
