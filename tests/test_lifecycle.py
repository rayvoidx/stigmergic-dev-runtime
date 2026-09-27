"""Offline tests for the channel lifecycle, audience contracts, and scale gate (ADR 0011)."""

import pytest

from stigdev.lifecycle import (
    COUNTED_STATES,
    REUSE_GATE_ID,
    LIFECYCLE_STATES,
    LIFECYCLE_TRANSITIONS,
    PORTFOLIO_STAGE,
    AudienceContract,
    ChannelSlot,
    FormatFingerprint,
    LifecycleError,
    ScaleEvidence,
    advance_lifecycle,
    counts,
    cross_channel_reuse_gate,
    scale_gate,
    set_incident_state,
)
from stigdev.portfolio import DEFAULT_POLICY, PILOT_STAGES, STAGES, GateDecision, PortfolioPolicy


def slot(**kw) -> ChannelSlot:
    base = dict(channel_id="synthetic-a", family_id="archive-tales")
    base.update(kw)
    return ChannelSlot(**base)


def evidence(**kw) -> ScaleEvidence:
    base = dict(
        independent_audience_contract=True,
        rights_originality_disclosure_pass=True,
        positive_margin_cohorts=3,
        holds_without_top_video=True,
        overlap_review_passed=True,
        policy_strikes=0,
        unresolved_rights_incidents=0,
        capacity_available=True,
        approved_by="operator",
    )
    base.update(kw)
    return ScaleEvidence(**base)


@pytest.mark.parametrize(
    "record",
    [
        slot(),
        AudienceContract("synthetic-a", "adults", "understand a record", "records first"),
        FormatFingerprint("synthetic-a", ("h1",), ("h2",), (0.5,)),
        evidence(),
    ],
)
def test_records_round_trip_through_dict(record):
    assert type(record).from_dict(record.to_dict()) == record


def test_every_lifecycle_state_maps_onto_a_real_portfolio_stage():
    assert set(PORTFOLIO_STAGE) == set(LIFECYCLE_STATES)
    # Exactly one coarse stage is unreachable from the fine machine: `pause`,
    # whose job the orthogonal incident overlay does better. Asserting the image
    # rather than a subset means a fourth coarse state cannot appear unnoticed.
    assert set(PORTFOLIO_STAGE.values()) == set(STAGES) - {"pause"}
    # the mapping is monotonic: it never sends a later state to an earlier stage
    ranks = [STAGES.index(PORTFOLIO_STAGE[s]) for s in LIFECYCLE_STATES]
    assert ranks == sorted(ranks)


def test_counting_agrees_with_the_coarse_portfolio_rule():
    """Both layers must count the same channels until `register_channel` is the only counter."""
    assert set(COUNTED_STATES) == {s for s in LIFECYCLE_STATES if PORTFOLIO_STAGE[s] != "retire"}
    fine_pilots = {s for s in LIFECYCLE_STATES if PORTFOLIO_STAGE[s] in PILOT_STAGES}
    assert fine_pilots == {"proposed", "unlisted_canary", "pilot", "monetization_gating"}


def test_retire_is_terminal_and_not_counted_active():
    assert LIFECYCLE_TRANSITIONS["retire"] == ()
    assert "retire" not in COUNTED_STATES
    with pytest.raises(LifecycleError, match="invalid transition"):
        advance_lifecycle(slot(lifecycle_state="retire"), "maintain")


def test_lifecycle_walks_the_documented_path():
    s = slot()
    for step in ("unlisted_canary", "pilot", "monetization_gating"):
        s = advance_lifecycle(s, step)
        assert s.lifecycle_state == step
    s = advance_lifecycle(s, "scale", [], evidence())
    assert s.lifecycle_state == "scale" and s.portfolio_stage == "scale"


def test_pilot_cannot_skip_monetization_gating():
    with pytest.raises(LifecycleError, match="invalid transition"):
        advance_lifecycle(slot(lifecycle_state="pilot"), "scale", [], evidence())


def test_scale_needs_evidence_and_reports_every_unmet_condition():
    gated = slot(lifecycle_state="monetization_gating")
    with pytest.raises(LifecycleError, match="scale evidence required"):
        advance_lifecycle(gated, "scale")
    bad = evidence(
        independent_audience_contract=False,
        positive_margin_cohorts=2,
        policy_strikes=1,
        approved_by="",
    )
    decision = scale_gate(bad)
    assert decision == GateDecision(
        "channel-scale-gate/v1",
        False,
        (
            "audience contract is not independent",
            "fewer than 3 cohorts with positive margin including human time",
            "policy strikes present",
            "operator approval missing",
        ),
    )
    with pytest.raises(LifecycleError) as excinfo:
        advance_lifecycle(gated, "scale", [], bad)
    assert excinfo.value.reasons == decision.reasons


def test_scale_gate_passes_when_all_seven_conditions_hold():
    assert scale_gate(evidence()) == GateDecision("channel-scale-gate/v1", True, ())


def test_only_two_channels_may_be_in_scale_at_once():
    others = [slot(channel_id=f"synthetic-{i}", lifecycle_state="scale") for i in range(2)]
    gated = slot(lifecycle_state="monetization_gating")
    with pytest.raises(LifecycleError, match="scale limit: 2"):
        advance_lifecycle(gated, "scale", others, evidence())
    loose = PortfolioPolicy(max_scale=3, max_active=12, max_pilot=4, max_review_hours_per_week=15.0)
    assert advance_lifecycle(gated, "scale", others, evidence(), loose).lifecycle_state == "scale"
    assert DEFAULT_POLICY.max_scale == 2


def test_a_channel_already_in_scale_may_re_enter_its_own_slot():
    already = slot(lifecycle_state="scale")
    portfolio = [already, slot(channel_id="synthetic-b", lifecycle_state="scale")]
    moved = advance_lifecycle(already, "maintain", portfolio)
    assert advance_lifecycle(moved, "scale", portfolio, evidence()).lifecycle_state == "scale"


def test_an_open_incident_blocks_promotion_and_publishing():
    watched = slot(lifecycle_state="monetization_gating", incident_state="quarantined")
    with pytest.raises(LifecycleError, match="resolve the incident first"):
        advance_lifecycle(watched, "scale", [], evidence())
    assert not slot(lifecycle_state="scale", incident_state="watch").may_publish
    assert slot(lifecycle_state="scale").may_publish
    assert not slot(lifecycle_state="unlisted_canary").may_publish


def test_incident_de_escalation_needs_a_named_resolver():
    frozen = set_incident_state(slot(), "frozen")
    assert frozen.incident_state == "frozen"
    with pytest.raises(LifecycleError, match="named resolver"):
        set_incident_state(frozen, "clear")
    assert set_incident_state(frozen, "clear", resolved_by="operator").incident_state == "clear"


def test_counts_ignore_retired_channels():
    portfolio = [
        slot(channel_id="synthetic-a", lifecycle_state="scale"),
        slot(channel_id="synthetic-b", lifecycle_state="maintain"),
        slot(channel_id="synthetic-c", lifecycle_state="retire"),
    ]
    assert counts(portfolio) == {"active": 2, "scale": 1, "publishing": 2}


def test_fingerprint_finds_exact_cross_channel_reuse():
    left = FormatFingerprint("synthetic-a", ("s1",), ("a1", "shared"))
    right = FormatFingerprint("synthetic-b", ("s2",), ("a2", "shared"))
    assert left.shared_assets(right) == frozenset({"shared"})
    assert left.shared_scripts(right) == frozenset()


@pytest.mark.parametrize(
    "build",
    [
        lambda: slot(lifecycle_state="growing"),
        lambda: slot(incident_state="on_fire"),
        lambda: slot(channel_id="../escape"),
        lambda: AudienceContract("synthetic-a", " ", "job", "promise"),
        lambda: FormatFingerprint("synthetic-a", ("",)),
        lambda: FormatFingerprint("synthetic-a", visual_voice_vector=(float("inf"),)),
        lambda: evidence(positive_margin_cohorts=-1),
    ],
)
def test_invalid_records_are_rejected(build):
    with pytest.raises(LifecycleError):
        build()


def test_reuse_gate_passes_when_nothing_is_shared():
    a = FormatFingerprint("synthetic-a", ("s1",), ("a1",))
    b = FormatFingerprint("synthetic-b", ("s2",), ("a2",))
    assert cross_channel_reuse_gate(a, [b]) == GateDecision(REUSE_GATE_ID, True, ())


def test_reuse_gate_hard_fails_on_an_exact_asset_or_script_match():
    a = FormatFingerprint("synthetic-a", ("shared-script",), ("shared-asset",))
    b = FormatFingerprint("synthetic-b", ("shared-script",), ("shared-asset",))
    decision = cross_channel_reuse_gate(a, [b])
    assert not decision.passed
    assert decision.reasons == (
        "asset shared-asset already published by synthetic-b",
        "script shared-script already published by synthetic-b",
    )


def test_reuse_gate_ignores_the_channel_s_own_earlier_fingerprint():
    own = FormatFingerprint("synthetic-a", ("s1",), ("a1",))
    later = FormatFingerprint("synthetic-a", ("s1",), ("a1",), version=2)
    assert cross_channel_reuse_gate(later, [own]).passed
