"""HLP-realtime reference helpers (appendix C).

Pure promotion utilities for Soft/Hard control. Does not change the Task state
machine. Hosts merge soft channel signals here (or with equivalent logic), then
call existing ``task.amend`` / checkpoint APIs with the promoted result.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .objects import ControlSignal, InteractionRef, SteeringAmendment
from .types import (
    HLP_REALTIME_PROFILE,
    ProtocolError,
    SteeringIntent,
    TaskState,
)


# Default confidence floor for promoting soft signals to steering (profile MAY override).
DEFAULT_SOFT_CONFIDENCE_THRESHOLD = 0.5


@dataclass(frozen=True)
class SoftPromotionResult:
    """Result of host-side soft merge → one SteeringAmendment + audit provenance."""

    amendment: SteeringAmendment
    provenance: dict[str, Any]
    signals: tuple[ControlSignal, ...]


def assert_soft_does_not_change_task_state(
    before: TaskState,
    after: TaskState,
) -> None:
    """D1: soft control must not change Task.state."""
    if before != after:
        raise ProtocolError(
            "PRECONDITION_FAILED",
            "HLP-realtime D1: soft control must not change Task.state "
            f"(before={before!r}, after={after!r})",
        )


def may_resolve_hard_checkpoint_with_signal(
    signal: ControlSignal,
    *,
    high_risk: bool,
    second_factor_present: bool = False,
) -> bool:
    """D3: BCI (and similar) alone must not close high-risk hard checkpoints.

    Returns True if this signal is allowed to act as the *sole* human binding for
    a hard resolve under default HLP-realtime policy.
    """
    if signal.strength != "hard" and signal.intent not in {"affirm", "deny", "halt"}:
        return False
    if not high_risk:
        # Low-risk hard gates: any bound principal channel may resolve when profile allows.
        return signal.confidence >= DEFAULT_SOFT_CONFIDENCE_THRESHOLD
    # High-risk: biological/single-sensor channels need a second factor by default.
    if signal.source_kind == "bci" and not second_factor_present:
        return False
    return signal.confidence >= DEFAULT_SOFT_CONFIDENCE_THRESHOLD


def require_hard_resolve_allowed(
    signal: ControlSignal,
    *,
    high_risk: bool,
    second_factor_present: bool = False,
) -> None:
    """Raise ProtocolError when D3 forbids BCI-alone high-risk resolve."""
    if not may_resolve_hard_checkpoint_with_signal(
        signal,
        high_risk=high_risk,
        second_factor_present=second_factor_present,
    ):
        raise ProtocolError(
            "UNAUTHORIZED",
            "HLP-realtime D3: high-risk hard checkpoint resolve requires a "
            "non-BCI-only principal confirmation (second factor)",
            details={
                "source_kind": signal.source_kind,
                "high_risk": high_risk,
                "second_factor_present": second_factor_present,
                "confidence": signal.confidence,
            },
        )


def merge_soft_control_signals(
    signals: Sequence[ControlSignal],
    *,
    by: str | None = None,
    intent: SteeringIntent = "clarify",
    confidence_threshold: float = DEFAULT_SOFT_CONFIDENCE_THRESHOLD,
) -> SoftPromotionResult:
    """D2: host merges soft streams into one amendment HLP will accept.

    - Drops non-soft signals and low-confidence soft signals.
    - Does not touch Task.state (caller must keep state unchanged — D1).
    - Returns a single SteeringAmendment text + audit provenance.
    """
    if not signals:
        raise ProtocolError("INVALID_SPEC", "merge_soft_control_signals requires signals")

    soft: list[ControlSignal] = []
    for signal in signals:
        if signal.strength != "soft":
            raise ProtocolError(
                "INVALID_SPEC",
                "merge_soft_control_signals only accepts strength=soft "
                f"(got {signal.strength!r}); promote hard via checkpoint/interrupt",
            )
        if signal.confidence < confidence_threshold:
            continue
        soft.append(signal)

    if not soft:
        raise ProtocolError(
            "PRECONDITION_FAILED",
            "no soft signals met confidence threshold for promotion",
            details={"threshold": confidence_threshold},
        )

    principal = by or soft[-1].principal_binding
    for signal in soft:
        if signal.principal_binding != principal:
            raise ProtocolError(
                "UNAUTHORIZED",
                "soft signals in one merge must share principal_binding "
                f"({principal!r} vs {signal.principal_binding!r})",
            )

    # Chronological merge of texts (host-defined aggregation: join unique lines).
    ordered = sorted(soft, key=lambda item: item.effective_at)
    lines: list[str] = []
    for signal in ordered:
        text = (signal.text or "").strip()
        if text and text not in lines:
            lines.append(text)
    if not lines:
        lines = [f"soft control ({ordered[-1].intent})"]

    amendment = SteeringAmendment(
        text="\n".join(lines),
        intent=intent,
        by=principal,
    )
    provenance = promotion_audit_payload(
        promotion="steering",
        signals=tuple(ordered),
        principal=principal,
        result_summary=amendment.text,
    )
    return SoftPromotionResult(
        amendment=amendment,
        provenance=provenance,
        signals=tuple(ordered),
    )


def promotion_audit_payload(
    *,
    promotion: str,
    signals: Sequence[ControlSignal],
    principal: str,
    result_summary: str = "",
    high_risk: bool | None = None,
    second_factor_present: bool | None = None,
) -> dict[str, Any]:
    """Build reducer-ready intent provenance for audit.after / reducer fields."""
    return {
        "profile": HLP_REALTIME_PROFILE,
        "promotion": promotion,
        "principal": principal,
        "result_summary": result_summary,
        "high_risk": high_risk,
        "second_factor_present": second_factor_present,
        "signal_count": len(signals),
        "signals": [
            {
                "strength": s.strength,
                "intent": s.intent,
                "confidence": s.confidence,
                "source_kind": s.source_kind,
                "source_ref": s.source_ref,
                "text": s.text,
                "promotion": s.promotion,
                "run_id": s.run_id,
                "principal_binding": s.principal_binding,
                "effective_at": s.effective_at.isoformat(),
                "interaction": asdict(s.interaction) if s.interaction else None,
            }
            for s in signals
        ],
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def control_signal_to_wire(signal: ControlSignal) -> dict[str, Any]:
    """JSON-friendly dict for host storage / audit (not a first-class schema)."""
    data = asdict(signal)
    data["effective_at"] = signal.effective_at.isoformat()
    data["recorded_at"] = signal.recorded_at.isoformat()
    return data
