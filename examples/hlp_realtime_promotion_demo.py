"""Offline HLP-realtime promotion demo (appendix C).

Simulates a host channel that:
1. Receives high-frequency soft speech-like signals
2. Merges them into one SteeringAmendment (D2)
3. Calls task.amend with promotion_provenance (audit)
4. Keeps Task.state unchanged (D1)
5. Rejects BCI-alone high-risk hard resolve (D3)

No voice stack, no BCI hardware, no live model.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loops.hlp import (
    ControlSignal,
    HLPClient,
    InteractionRef,
    ProtocolError,
    assert_soft_does_not_change_task_state,
    merge_soft_control_signals,
    require_hard_resolve_allowed,
)


async def run_demo() -> dict[str, Any]:
    client = HLPClient()
    interaction = InteractionRef(
        channel="mock-voice",
        session_id="sess_demo_rt",
        episode_id="ep_1",
    )

    task = await client.create_task(
        principal="user_alice",
        goal="Refactor auth middleware carefully",
        type="realtime-promo-demo",
        acceptance_criteria=("No production push without hard approval",),
    )
    await client.delegate(task.id, "agent_demo", capability="code-edit")
    started = await client.start(task.id)
    state_before = started.state

    # Channel plane: burst of soft corrections (would be speech frames).
    soft_burst = (
        ControlSignal(
            strength="soft",
            intent="constrain",
            principal_binding="user_alice",
            confidence=0.88,
            source_kind="speech",
            text="先别动 production 配置",
            interaction=interaction,
            run_id=client.store.run_of_task(task.id),
        ),
        ControlSignal(
            strength="soft",
            intent="constrain",
            principal_binding="user_alice",
            confidence=0.92,
            source_kind="speech",
            text="重点看 token 过期路径",
            interaction=interaction,
            run_id=client.store.run_of_task(task.id),
        ),
        ControlSignal(
            strength="soft",
            intent="clarify",
            principal_binding="user_alice",
            confidence=0.2,  # dropped by merge threshold
            source_kind="speech",
            text="嗯嗯",
            interaction=interaction,
        ),
    )
    promoted = merge_soft_control_signals(
        soft_burst,
        by="user_alice",
        intent="constrain",
    )
    amended = await client.amend(
        task.id,
        by="user_alice",
        text=promoted.amendment.text,
        intent="constrain",
        promotion_provenance=promoted.provenance,
    )
    assert_soft_does_not_change_task_state(state_before, amended.state)

    # Hard path: agent would raise checkpoint; host tries BCI-only affirm (denied).
    checkpoint = await client.raise_checkpoint(
        task_id=task.id,
        kind="approval",
        prompt="Push auth refactor to production?",
        raised_by="agent_demo",
    )
    bci_affirm = ControlSignal(
        strength="hard",
        intent="affirm",
        principal_binding="user_alice",
        confidence=0.99,
        source_kind="bci",
        text="同意",
        interaction=interaction,
    )
    bci_alone_allowed = True
    bci_error: str | None = None
    try:
        require_hard_resolve_allowed(
            bci_affirm,
            high_risk=True,
            second_factor_present=False,
        )
    except ProtocolError as exc:
        bci_alone_allowed = False
        bci_error = f"{exc.code}: {exc.message}"

    # Second factor present → allowed at policy layer; still resolve via HLP human API.
    require_hard_resolve_allowed(
        bci_affirm,
        high_risk=True,
        second_factor_present=True,
    )
    resolved = await client.resolve_checkpoint(
        checkpoint.id,
        by="user_alice",
        action="reject",
        comment="Need staging soak first (BCI alone insufficient; explicit reject)",
    )

    audit = await client.replay_audit(task.id)
    amended_events = [e for e in audit if e.action == "task.amended"]
    promotion = (
        amended_events[-1].after.get("promotion")
        if amended_events and isinstance(amended_events[-1].after, dict)
        else None
    )

    return {
        "profile": "HLP-realtime",
        "task_id": task.id,
        "task_state_after_soft": amended.state,
        "steering_text": amended.steering_log[-1].text if amended.steering_log else "",
        "soft_signals_in": len(soft_burst),
        "soft_signals_promoted": len(promoted.signals),
        "promotion_profile": (promotion or {}).get("profile"),
        "promotion_signal_count": (promotion or {}).get("signal_count"),
        "d1_state_unchanged": (state_before == "in_progress" and amended.state == "in_progress"),
        "bci_alone_high_risk_allowed": bci_alone_allowed,
        "bci_alone_error": bci_error,
        "checkpoint_id": checkpoint.id,
        "checkpoint_resolution": (resolved.resolution.action if resolved.resolution else None),
        "final_task_state": (await client.get_task(task.id)).state,
        "decisions": {
            "D1_soft_no_state_change": True,
            "D2_host_merge_only": True,
            "D3_bci_alone_denied": not bci_alone_allowed,
        },
    }


def main() -> None:
    print(json.dumps(asyncio.run(run_demo()), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
