"""HLP-realtime reference helpers (appendix C decisions D1–D3)."""

from __future__ import annotations

import asyncio

import pytest

from loops.hlp import (
    HLP_REALTIME_PROFILE,
    HLP_REALTIME_SPEC_VERSION,
    CheckpointOption,
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


def test_bci_channel_demo_runs_offline():
    from examples.hlp_bci_channel_demo import run_demo

    result = run(run_demo())
    assert result["profile"] == "HLP-realtime"
    assert result["channel"] == "bci"

    # Path 1: soft BCI stream merges into one amendment; D1 holds.
    assert result["soft_signals_in"] == 3
    assert result["soft_signals_promoted"] == 2
    assert result["d1_state_unchanged"] is True
    assert "先别动 production 配置" in result["steering_text"]
    assert result["promotion_profile"] == "HLP-realtime"
    assert result["promotion_source_kinds"] == ["bci"]

    # Path 2: low-risk checkpoint resolves on BCI affirm alone.
    assert result["low_risk_checkpoint"]["policy_high_risk"] is False
    assert result["low_risk_checkpoint"]["resolution"] == "approve"

    # Path 3: high-risk checkpoint denies BCI-alone resolve (D3 fail-closed).
    high_risk = result["high_risk_checkpoint"]
    assert high_risk["policy_high_risk"] is True
    assert high_risk["bci_alone_allowed"] is False
    assert high_risk["bci_alone_error"] and "D3" in high_risk["bci_alone_error"]

    # Path 4: second factor unlocks the same signal.
    assert high_risk["resolution_with_second_factor"] == "approve"

    assert result["decisions"]["D3_bci_alone_high_risk_denied"] is True


def test_bci_risk_policy_flags_high_risk_keywords_and_options():
    from examples.hlp_bci_channel_demo import checkpoint_is_high_risk

    client = HLPClient()
    task = run(client.create_task(principal="user_alice", goal="ship safely"))
    run(client.delegate(task.id, "agent_x", capability="code"))
    run(client.start(task.id))

    benign = run(
        client.raise_checkpoint(
            task_id=task.id,
            kind="approval",
            prompt="Apply README wording tweak?",
            raised_by="agent_x",
        )
    )
    assert checkpoint_is_high_risk(benign) is False
    run(client.resolve_checkpoint(benign.id, by="user_alice", action="approve"))

    keyword_risky = run(
        client.raise_checkpoint(
            task_id=task.id,
            kind="approval",
            prompt="Push auth refactor to production?",
            raised_by="agent_x",
        )
    )
    assert checkpoint_is_high_risk(keyword_risky) is True
    run(client.resolve_checkpoint(keyword_risky.id, by="user_alice", action="approve"))

    option_risky = run(
        client.raise_checkpoint(
            task_id=task.id,
            kind="choice",
            prompt="Pick an execution path.",
            options=(CheckpointOption(id="nuke", label="Drop tables", risk="high"),),
            raised_by="agent_x",
        )
    )
    assert checkpoint_is_high_risk(option_risky) is True
    run(client.resolve_checkpoint(option_risky.id, by="user_alice", action="choose", choice="nuke"))


def test_bci_decoder_produces_principal_bound_signals():
    from examples.hlp_bci_channel_demo import SyntheticBCIDecoder

    interaction = InteractionRef(channel="bci", session_id="eeg_sess_test", episode_id="ep_t")
    decoder = SyntheticBCIDecoder(principal="user_alice", interaction=interaction)
    signal = decoder.decode(
        "ep_t1",
        strength="hard",
        intent="affirm",
        confidence=0.93,
        text="同意",
    )
    assert signal.source_kind == "bci"
    assert signal.principal_binding == "user_alice"
    assert signal.confidence == 0.93
    assert signal.source_ref == "synthetic-eeg:ep_t1"
    assert signal.interaction is not None
    assert signal.interaction.channel == "bci"
