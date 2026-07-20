"""HLP-realtime reference helpers (appendix C decisions D1–D3)."""

from __future__ import annotations

import asyncio

import pytest

from loops.hlp import (
    HLP_REALTIME_PROFILE,
    HLP_REALTIME_SPEC_VERSION,
    ControlSignal,
    HLPClient,
    InteractionRef,
    ProtocolError,
    assert_soft_does_not_change_task_state,
    may_resolve_hard_checkpoint_with_signal,
    merge_soft_control_signals,
    require_hard_resolve_allowed,
)


def run(coro):
    return asyncio.run(coro)


def test_realtime_profile_constants():
    assert HLP_REALTIME_PROFILE == "HLP-realtime"
    assert HLP_REALTIME_SPEC_VERSION == "0.3.0-draft"


def test_merge_soft_signals_produces_one_amendment_without_state_semantics():
    signals = (
        ControlSignal(
            strength="soft",
            intent="constrain",
            principal_binding="user_alice",
            confidence=0.9,
            source_kind="speech",
            text="往左一点",
        ),
        ControlSignal(
            strength="soft",
            intent="constrain",
            principal_binding="user_alice",
            confidence=0.95,
            source_kind="speech",
            text="再往左 2px",
            interaction=InteractionRef(channel="voice", session_id="sess_1"),
        ),
    )
    result = merge_soft_control_signals(signals, by="user_alice", intent="constrain")
    assert "往左一点" in result.amendment.text
    assert "再往左 2px" in result.amendment.text
    assert result.amendment.by == "user_alice"
    assert result.provenance["profile"] == "HLP-realtime"
    assert result.provenance["promotion"] == "steering"
    assert result.provenance["signal_count"] == 2


def test_merge_rejects_hard_signals_and_low_confidence():
    with pytest.raises(ProtocolError) as hard_err:
        merge_soft_control_signals(
            (
                ControlSignal(
                    strength="hard",
                    intent="halt",
                    principal_binding="user_alice",
                    text="停",
                ),
            ),
        )
    assert hard_err.value.code == "INVALID_SPEC"

    with pytest.raises(ProtocolError) as low_err:
        merge_soft_control_signals(
            (
                ControlSignal(
                    strength="soft",
                    intent="clarify",
                    principal_binding="user_alice",
                    confidence=0.1,
                    text="maybe",
                ),
            ),
        )
    assert low_err.value.code == "PRECONDITION_FAILED"


def test_d1_soft_must_not_change_task_state():
    assert_soft_does_not_change_task_state("in_progress", "in_progress")
    with pytest.raises(ProtocolError) as err:
        assert_soft_does_not_change_task_state("in_progress", "blocked")
    assert err.value.code == "PRECONDITION_FAILED"
    assert "D1" in err.value.message


def test_d3_bci_alone_cannot_resolve_high_risk_hard_checkpoint():
    bci = ControlSignal(
        strength="hard",
        intent="affirm",
        principal_binding="user_alice",
        confidence=0.99,
        source_kind="bci",
        text="同意",
    )
    assert (
        may_resolve_hard_checkpoint_with_signal(
            bci,
            high_risk=True,
            second_factor_present=False,
        )
        is False
    )
    assert (
        may_resolve_hard_checkpoint_with_signal(
            bci,
            high_risk=True,
            second_factor_present=True,
        )
        is True
    )
    assert (
        may_resolve_hard_checkpoint_with_signal(
            bci,
            high_risk=False,
            second_factor_present=False,
        )
        is True
    )

    with pytest.raises(ProtocolError) as err:
        require_hard_resolve_allowed(
            bci,
            high_risk=True,
            second_factor_present=False,
        )
    assert err.value.code == "UNAUTHORIZED"
    assert "D3" in err.value.message


def test_realtime_promotion_demo_runs_offline():
    from examples.hlp_realtime_promotion_demo import run_demo

    result = run(run_demo())
    assert result["profile"] == "HLP-realtime"
    assert result["task_state_after_soft"] == "in_progress"
    assert "先别动 production 配置" in result["steering_text"]
    assert "重点看 token 过期路径" in result["steering_text"]
    assert "嗯嗯" not in result["steering_text"]
    assert result["soft_signals_in"] == 3
    assert result["soft_signals_promoted"] == 2
    assert result["promotion_profile"] == "HLP-realtime"
    assert result["promotion_signal_count"] == 2
    assert result["bci_alone_high_risk_allowed"] is False
    assert result["bci_alone_error"] and "D3" in result["bci_alone_error"]
    assert result["checkpoint_resolution"] == "reject"
    assert result["decisions"]["D1_soft_no_state_change"] is True
    assert result["decisions"]["D3_bci_alone_denied"] is True


def test_task_amend_preserves_state_and_records_promotion_provenance():
    client = HLPClient()
    task = run(client.create_task(principal="user_alice", goal="ship safely"))
    run(client.delegate(task.id, "agent_x", capability="code"))
    started = run(client.start(task.id))
    assert started.state == "in_progress"

    soft = (
        ControlSignal(
            strength="soft",
            intent="constrain",
            principal_binding="user_alice",
            confidence=0.9,
            source_kind="ui",
            text="focus on auth",
        ),
    )
    promoted = merge_soft_control_signals(soft, by="user_alice")
    amended = run(
        client.amend(
            task.id,
            by="user_alice",
            text=promoted.amendment.text,
            intent="constrain",
            promotion_provenance=promoted.provenance,
        )
    )
    assert amended.state == "in_progress"
    assert amended.steering_log[-1].text == "focus on auth"
    assert_soft_does_not_change_task_state(started.state, amended.state)

    events = run(client.replay_audit(task.id))
    amended_events = [e for e in events if e.action == "task.amended"]
    assert amended_events
    after = amended_events[-1].after
    assert after["state"] == "in_progress"
    assert after["promotion"]["profile"] == "HLP-realtime"
    assert after["promotion"]["signal_count"] == 1
