"""Offline BCI (brainwave) channel demo for HLP (appendix C).

Shows that brain-computer-interface human input is compatible with HLP with
zero protocol changes: a BCI decoder is a channel/sensor-plane producer of
``ControlSignal`` values, and HLP receives only promoted responsibility
events (D2). No first-class media objects, no vendor EEG schema (C.10).

Paths demonstrated:
1. High-confidence soft BCI stream → host merge → one ``task.amend``
   (D1: Task.state unchanged; audit carries BCI promotion provenance).
2. High-confidence hard BCI affirm + LOW-risk checkpoint → resolve succeeds.
3. High-confidence hard BCI affirm + HIGH-risk checkpoint without a second
   factor → ``UNAUTHORIZED`` (D3 fail-closed).
4. Same signal with a second factor present → resolve succeeds.

No BCI hardware, no decoding stack, no live model.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from loops.hlp import (
    Checkpoint,
    ControlSignal,
    HLPClient,
    InteractionRef,
    ProtocolError,
    assert_soft_does_not_change_task_state,
    merge_soft_control_signals,
    require_hard_resolve_allowed,
)
from loops.hlp.types import ControlIntent, ControlStrength

# Example channel-side risk vocabulary (hosts define their own policy).
_HIGH_RISK_KEYWORDS = ("production", "prod ", "secret", "credential", "payment", "funds")
_HIGH_RISK_OPTION_FLAGS = {"high", "critical"}


@dataclass(frozen=True)
class SyntheticBCIDecoder:
    """Deterministic stand-in for an EEG intent decoder (channel plane only).

    A real decoder (OpenBCI / Muse / vendor SDK) would implement this same tiny
    surface inside the host — never inside HLP core (appendix C.10). Episodes
    stand in for decoded motor-imagery / attention epochs.
    """

    principal: str
    interaction: InteractionRef

    def decode(
        self,
        episode: str,
        *,
        strength: ControlStrength,
        intent: ControlIntent,
        confidence: float,
        text: str,
        run_id: str | None = None,
    ) -> ControlSignal:
        return ControlSignal(
            strength=strength,
            intent=intent,
            principal_binding=self.principal,
            confidence=confidence,
            source_kind="bci",
            source_ref=f"synthetic-eeg:{episode}",
            text=text,
            run_id=run_id,
            interaction=self.interaction,
        )


def checkpoint_is_high_risk(checkpoint: Checkpoint) -> bool:
    """Example risk policy: a high-flagged option, or a risky prompt keyword."""
    for option in checkpoint.options:
        if str(option.risk).lower() in _HIGH_RISK_OPTION_FLAGS:
            return True
    prompt = checkpoint.prompt.lower()
    return any(keyword in prompt for keyword in _HIGH_RISK_KEYWORDS)


async def run_demo() -> dict[str, Any]:
    client = HLPClient()
    decoder = SyntheticBCIDecoder(
        principal="user_alice",
        interaction=InteractionRef(
            channel="bci",
            session_id="eeg_sess_demo",
            episode_id="epoch_1",
        ),
    )

    task = await client.create_task(
        principal="user_alice",
        goal="Refactor auth middleware carefully",
        type="bci-channel-demo",
        acceptance_criteria=("No production push without hard approval",),
    )
    await client.delegate(task.id, "agent_demo", capability="code-edit")
    started = await client.start(task.id)
    state_before = started.state

    # ── Path 1: soft BCI stream → one merged task.amend (D1 + D2) ──
    soft_stream = (
        decoder.decode(
            "ep_001",
            strength="soft",
            intent="constrain",
            confidence=0.91,
            text="先别动 production 配置",
            run_id=client.store.run_of_task(task.id),
        ),
        decoder.decode(
            "ep_002",
            strength="soft",
            intent="constrain",
            confidence=0.87,
            text="重点看 token 过期路径",
            run_id=client.store.run_of_task(task.id),
        ),
        decoder.decode(
            "ep_003",
            strength="soft",
            intent="clarify",
            confidence=0.2,  # below merge threshold → dropped
            text="嗯",
        ),
    )
    promoted = merge_soft_control_signals(soft_stream, by="user_alice", intent="constrain")
    amended = await client.amend(
        task.id,
        by="user_alice",
        text=promoted.amendment.text,
        intent="constrain",
        promotion_provenance=promoted.provenance,
    )
    assert_soft_does_not_change_task_state(state_before, amended.state)

    # ── Path 2: hard BCI affirm + low-risk checkpoint → resolve succeeds ──
    low_risk_checkpoint = await client.raise_checkpoint(
        task_id=task.id,
        kind="approval",
        prompt="Apply README wording tweak?",
        raised_by="agent_demo",
    )
    low_risk = checkpoint_is_high_risk(low_risk_checkpoint)
    affirm = decoder.decode(
        "ep_004",
        strength="hard",
        intent="affirm",
        confidence=0.97,
        text="同意",
    )
    require_hard_resolve_allowed(affirm, high_risk=low_risk)
    low_risk_resolved = await client.resolve_checkpoint(
        low_risk_checkpoint.id,
        by="user_alice",
        action="approve",
        comment="BCI affirm, low risk, confidence 0.97",
    )

    # ── Path 3: hard BCI affirm + high-risk checkpoint, no 2nd factor → deny ──
    high_risk_checkpoint = await client.raise_checkpoint(
        task_id=task.id,
        kind="approval",
        prompt="Push auth refactor to production?",
        raised_by="agent_demo",
    )
    high_risk = checkpoint_is_high_risk(high_risk_checkpoint)
    bci_alone_allowed = True
    bci_alone_error: str | None = None
    try:
        require_hard_resolve_allowed(
            affirm,
            high_risk=high_risk,
            second_factor_present=False,
        )
    except ProtocolError as exc:
        bci_alone_allowed = False
        bci_alone_error = f"{exc.code}: {exc.message}"

    # ── Path 4: same signal + second factor → resolve succeeds ──
    require_hard_resolve_allowed(
        affirm,
        high_risk=high_risk,
        second_factor_present=True,
    )
    high_risk_resolved = await client.resolve_checkpoint(
        high_risk_checkpoint.id,
        by="user_alice",
        action="approve",
        comment="BCI affirm + explicit second factor (simulated UI confirm)",
    )

    # ── Audit evidence: BCI provenance must be replayable (C.3 MUST 5) ──
    audit = await client.replay_audit(task.id)
    amended_events = [event for event in audit if event.action == "task.amended"]
    promotion = (
        amended_events[-1].after.get("promotion")
        if amended_events and isinstance(amended_events[-1].after, dict)
        else None
    )
    promotion_source_kinds = sorted(
        {signal.get("source_kind") for signal in (promotion or {}).get("signals", [])}
    )

    return {
        "profile": "HLP-realtime",
        "channel": "bci",
        "task_id": task.id,
        "soft_signals_in": len(soft_stream),
        "soft_signals_promoted": len(promoted.signals),
        "d1_state_unchanged": (state_before == "in_progress" and amended.state == "in_progress"),
        "steering_text": amended.steering_log[-1].text if amended.steering_log else "",
        "promotion_profile": (promotion or {}).get("profile"),
        "promotion_source_kinds": promotion_source_kinds,
        "low_risk_checkpoint": {
            "id": low_risk_checkpoint.id,
            "policy_high_risk": low_risk,
            "resolution": (
                low_risk_resolved.resolution.action if low_risk_resolved.resolution else None
            ),
        },
        "high_risk_checkpoint": {
            "id": high_risk_checkpoint.id,
            "policy_high_risk": high_risk,
            "bci_alone_allowed": bci_alone_allowed,
            "bci_alone_error": bci_alone_error,
            "resolution_with_second_factor": (
                high_risk_resolved.resolution.action if high_risk_resolved.resolution else None
            ),
        },
        "decisions": {
            "D1_soft_no_state_change": True,
            "D2_host_merge_only": True,
            "D3_bci_alone_high_risk_denied": not bci_alone_allowed,
        },
    }


def main() -> None:
    print(json.dumps(asyncio.run(run_demo()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
