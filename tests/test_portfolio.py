"""Offline tests for the generic media portfolio, rights, and release contracts (ADR 0007)."""

from dataclasses import replace

import pytest

from stigdev.portfolio import (
    MAX_SCALE_CHANNELS,
    REVENUE_KINDS,
    STAGE_TRANSITIONS,
    ChannelPlan,
    FormatHypothesis,
    GateDecision,
    PortfolioError,
    ProfitSnapshot,
    PublishCandidate,
    ReleaseUnit,
    RevenueEvent,
    RightsManifest,
    ScaleEvidence,
    advance_stage,
    can_publish,
    cash_revenue,
    contribution_margin,
    floor_deficit,
    gross_revenue,
    publish_gate,
    release_gate,
    revenue_by_kind,
    rights_gate,
    sla_breached,
    view_policy_era,
)

NOW = "2026-09-27T00:00:00+00:00"


def plan(**kw) -> ChannelPlan:
    base = dict(
        channel_id="synthetic-stories",
        business_role="cash_engine",
        stage="public_pilot",
        audience_contract="synthetic_history_for_sleep",
        weekly_publish_cap={"long": 1, "short": 3},
    )
    base.update(kw)
    return ChannelPlan(**base)


def rights(**kw) -> RightsManifest:
    base = dict(
        artifact_id="asset-1",
        owner="creator",
        rights_basis="original",
        commercial_use=True,
        exclusivity="exclusive",
    )
    base.update(kw)
    return RightsManifest(**base)


def scale_evidence(**kw) -> ScaleEvidence:
    base = dict(
        weeks_public=8,
        public_artifacts=30,
        recent_median_improved=True,
        strikes=0,
        repeated_content_id_claims=0,
        short_review_minutes=40.0,
        long_review_minutes=200.0,
        revenue_attributable=True,
        shadow_double_volume_passed=True,
        approved_by="operator",
    )
    base.update(kw)
    return ScaleEvidence(**base)


def candidate(**kw) -> PublishCandidate:
    base = dict(
        content_id="item-1",
        channel_id="synthetic-stories",
        format="short",
        payload_hash="abc",
        approved_payload_hash="abc",
        upload_visibility="private",
        content_id_result="clear",
        ai_disclosure=True,
        rights=(rights(),),
    )
    base.update(kw)
    return PublishCandidate(**base)


# --- records -----------------------------------------------------------------


@pytest.mark.parametrize(
    "record",
    [
        plan(),
        rights(contributors=("a", "b"), expires_at=NOW),
        ReleaseUnit("rel-1", "asset-1", stems=("s1",), splits=(("a", 0.5), ("b", 0.5)), isrc="X"),
        ProfitSnapshot("synthetic-stories", NOW, "7d", {"raw_views": 10.0}, {"paid": 1.0}),
        FormatHypothesis("h1", "synthetic-stories", "hook", "retention_30s", 10, NOW),
        RevenueEvent("synthetic-stories", "paid", 100.0, NOW, "platform"),
    ],
)
def test_records_round_trip_through_dict(record):
    assert type(record).from_dict(record.to_dict()) == record


@pytest.mark.parametrize(
    "build",
    [
        lambda: plan(stage="pilot"),
        lambda: plan(business_role="clip_farm"),
        lambda: plan(weekly_publish_cap={"reel": 1}),
        lambda: plan(owned_ip_ratio_min=1.5),
        lambda: plan(channel_id="../secret"),
        lambda: rights(rights_basis="scraped"),
        lambda: rights(exclusivity="maybe"),
        lambda: ReleaseUnit("rel-1", "asset-1", distributor_delivery="shipped"),
        lambda: ProfitSnapshot("c", NOW, "2h", {}, {}),
        lambda: ProfitSnapshot("c", NOW, "7d", {"raw_views": float("nan")}, {}),
        # v3.2 §13 P0.13: a bare view count is ambiguous after 2026-08-24; raw/engaged/qualified only
        lambda: ProfitSnapshot("c", NOW, "7d", {"views": 1.0}, {}),
        lambda: ProfitSnapshot("c", NOW, "7d", {"shorts_views": 1.0}, {}),
        lambda: ProfitSnapshot("c", NOW, "7d", {}, {"claimed": 1.0, "finalized": float("inf")}),
        # v3.2 §13 P0.17: a commerce lab channel must record its linked owner
        lambda: plan(business_role="commerce_lab"),
        lambda: plan(business_role="commerce_lab", owner_ref=""),
        lambda: ProfitSnapshot("c", NOW, "7d", {}, {"guessed": 1.0}),
        lambda: FormatHypothesis("h1", "c", "hook", "m", 10, NOW, status="won"),
        lambda: RevenueEvent("c", "projected", 1.0, NOW, "platform"),
        lambda: RevenueEvent("c", "paid", -1.0, NOW, "platform"),
    ],
)
def test_invalid_records_are_rejected(build):
    with pytest.raises(PortfolioError):
        build()


# --- rights gate -------------------------------------------------------------


def test_rights_gate_passes_clean_original_manifest():
    decision = rights_gate([rights()], NOW)
    assert decision == GateDecision("rights-gate/v1", True, ())


def test_rights_gate_fails_closed_on_empty_manifest_set():
    decision = rights_gate([], NOW)
    assert not decision.passed and decision.reasons == ("no rights manifest",)


@pytest.mark.parametrize(
    "manifest,reason",
    [
        (rights(rights_basis="unknown"), "asset-1: rights_basis unknown"),
        (rights(commercial_use=False), "asset-1: commercial use not granted"),
        (rights(owner=""), "asset-1: owner missing"),
        (rights(rights_basis="licensed"), "asset-1: licensed without license receipt"),
        (rights(expires_at=NOW), f"asset-1: rights expired at {NOW}"),
        (
            rights(exclusivity="non_exclusive", content_id_eligible=True),
            "asset-1: content_id_eligible requires exclusive original rights",
        ),
    ],
)
def test_rights_gate_reports_each_blocker(manifest, reason):
    decision = rights_gate([manifest], NOW)
    assert not decision.passed and reason in decision.reasons


def test_rights_gate_licensed_with_receipt_and_future_expiry_passes():
    manifest = rights(
        rights_basis="licensed",
        exclusivity="non_exclusive",
        license_receipt_hash="sha256:deadbeef",
        expires_at="2027-01-01T00:00:00+00:00",
    )
    assert rights_gate([manifest], NOW).passed


def test_rights_gate_collects_reasons_across_manifests():
    decision = rights_gate([rights(rights_basis="unknown"), rights(artifact_id="asset-2", owner="")], NOW)
    assert decision.reasons == ("asset-1: rights_basis unknown", "asset-2: owner missing")


# --- release gate ------------------------------------------------------------


def test_release_gate_passes_complete_unit():
    unit = ReleaseUnit(
        "rel-1",
        "asset-1",
        splits=(("creator", 0.7), ("vocalist", 0.3)),
        isrc="KRA012600001",
        derivatives=("official_visualizer", "hook_short_a"),
    )
    assert release_gate(unit, rights(), NOW).passed


def test_release_gate_lists_every_missing_requirement():
    unit = ReleaseUnit("rel-1", "asset-9", splits=(("creator", 0.6),))
    decision = release_gate(unit, rights(rights_basis="unknown"), NOW)
    assert decision.gate_id == "release-gate/v1"
    assert decision.reasons == (
        "asset-1: rights_basis unknown",
        "rights manifest does not cover master asset-9",
        "isrc pending",
        "splits do not sum to 1",
        "missing derivative official_visualizer",
    )


# --- weekly cap and publish gate ---------------------------------------------


def test_can_publish_respects_weekly_cap_per_format():
    assert can_publish(plan(), "short", {"short": 2})
    assert not can_publish(plan(), "short", {"short": 3})
    assert not can_publish(plan(), "long", {"long": 1, "short": 0})


def test_can_publish_rejects_unknown_format():
    with pytest.raises(PortfolioError):
        can_publish(plan(), "reel", {})


@pytest.mark.parametrize("stage", ["hypothesis", "private_pilot", "retire"])
def test_can_publish_refuses_non_public_stages(stage):
    assert not can_publish(plan(stage=stage), "short", {})


def test_publish_gate_passes_private_clear_disclosed_approved_candidate():
    assert publish_gate(candidate(), plan(), {}, NOW) == GateDecision("publish-gate/v1", True, ())


@pytest.mark.parametrize(
    "kw,reason",
    [
        ({"channel_id": "other"}, "candidate channel other does not match synthetic-stories"),
        ({"upload_visibility": "public"}, "upload must be private before public approval"),
        ({"content_id_result": "claimed"}, "content id result claimed"),
        ({"ai_disclosure": None}, "ai disclosure undecided"),
        ({"approved_payload_hash": "old"}, "approved payload hash mismatch"),
        ({"rights": (rights(commercial_use=False),)}, "asset-1: commercial use not granted"),
        ({"rights": ()}, "no rights manifest"),
    ],
)
def test_publish_gate_reports_each_blocker(kw, reason):
    decision = publish_gate(candidate(**kw), plan(), {}, NOW)
    assert not decision.passed and reason in decision.reasons


def test_publish_gate_blocks_on_weekly_cap_and_stage():
    capped = publish_gate(candidate(), plan(), {"short": 3}, NOW)
    assert "weekly cap reached for short" in capped.reasons
    private = publish_gate(candidate(), plan(stage="private_pilot"), {}, NOW)
    assert "channel stage private_pilot cannot publish publicly" in private.reasons


# --- stage machine and portfolio controller ----------------------------------


def test_stage_transitions_match_v3_state_diagram_plus_pause():
    assert STAGE_TRANSITIONS == {
        "hypothesis": ("private_pilot",),
        "private_pilot": ("public_pilot",),
        "public_pilot": ("scale", "retire", "pause"),
        "scale": ("maintain", "pause"),
        "maintain": ("scale", "retire", "pause"),
        "pause": ("maintain",),
        "retire": (),
    }


def test_pause_is_reversible_and_not_publishable():
    paused = advance_stage(plan(stage="scale"), "pause", [])
    assert not can_publish(paused, "short", {})
    assert advance_stage(paused, "maintain", []).stage == "maintain"


def test_advance_stage_follows_valid_edges_and_refuses_others():
    assert advance_stage(plan(stage="hypothesis"), "private_pilot", []).stage == "private_pilot"
    assert advance_stage(plan(), "retire", []).stage == "retire"
    with pytest.raises(PortfolioError, match="invalid transition"):
        advance_stage(plan(stage="hypothesis"), "scale", [], scale_evidence())


def test_advance_to_scale_requires_all_seven_conditions():
    promoted = advance_stage(plan(), "scale", [], scale_evidence())
    assert promoted == replace(plan(), stage="scale")
    with pytest.raises(PortfolioError, match="scale evidence required"):
        advance_stage(plan(), "scale", [])
    failing = scale_evidence(
        weeks_public=3,
        public_artifacts=12,
        recent_median_improved=False,
        strikes=1,
        repeated_content_id_claims=2,
        short_review_minutes=50.0,
        long_review_minutes=241.0,
        revenue_attributable=False,
        shadow_double_volume_passed=False,
        approved_by=None,
    )
    with pytest.raises(PortfolioError) as info:
        advance_stage(plan(), "scale", [], failing)
    assert info.value.reasons == (
        "fewer than 8 public weeks and fewer than 30 public artifacts",
        "recent median did not improve",
        "strikes present",
        "repeated content id claims present",
        "short review over 45 minutes",
        "long review over 240 minutes",
        "revenue not attributable per channel",
        "double-volume shadow test not passed",
        "operator approval missing",
    )


def test_advance_to_scale_enforces_two_channel_limit():
    others = [plan(channel_id=f"scale-{i}", stage="scale") for i in range(MAX_SCALE_CHANNELS)]
    with pytest.raises(PortfolioError, match="scale limit"):
        advance_stage(plan(), "scale", others, scale_evidence())
    # the channel being promoted does not count against itself
    itself = [replace(plan(), stage="scale"), others[0]]
    assert advance_stage(plan(), "scale", itself, scale_evidence()).stage == "scale"


# --- revenue ledger ----------------------------------------------------------


def events():
    return [
        RevenueEvent("c", "claimed", 5000.0, NOW, "external_video_title"),
        RevenueEvent("c", "estimated", 900.0, NOW, "studio_estimate"),
        RevenueEvent("c", "attributed", 50.0, NOW, "utm_checkout"),
        RevenueEvent("c", "finalized", 120.0, NOW, "affiliate_after_refund_window"),
        RevenueEvent("c", "paid", 300.0, NOW, "adsense"),
        RevenueEvent("c", "influenced", 1000.0, NOW, "survey"),
    ]


def test_revenue_by_kind_keeps_kinds_separate():
    assert revenue_by_kind(events()) == {
        "claimed": 5000.0,
        "estimated": 900.0,
        "attributed": 50.0,
        "finalized": 120.0,
        "paid": 300.0,
        "influenced": 1000.0,
    }
    assert revenue_by_kind([]) == {kind: 0.0 for kind in REVENUE_KINDS}


def test_gross_revenue_counts_only_finalized_and_paid():
    # v3.2 §11.2: finalized -> contribution margin, paid -> cash; attributed is sales analysis only
    assert gross_revenue(events()) == 420.0
    assert gross_revenue(events(), kinds=("paid",)) == 300.0
    for kind in ("claimed", "estimated", "attributed", "influenced"):
        with pytest.raises(PortfolioError):
            gross_revenue(events(), kinds=("paid", kind))


def test_cash_revenue_is_paid_only():
    assert cash_revenue(events()) == 300.0


def test_contribution_margin_subtracts_direct_costs():
    assert contribution_margin(events(), direct_costs=125.0) == 295.0


def test_view_policy_era_splits_cohorts_at_first_frame_counting():
    assert view_policy_era("2026-08-23T23:59:59+00:00") == "pre_2026_08_24"
    assert view_policy_era("2026-08-24T00:00:00+00:00") == "first_frame_2026_08_24"
    assert ProfitSnapshot("c", NOW, "7d", {"engaged_views": 3.0}, {}).view_policy_era == "first_frame_2026_08_24"


def test_commerce_lab_channel_records_linked_owner():
    lab = plan(business_role="commerce_lab", owner_ref="operator-1", stage="private_pilot")
    assert lab.owner_ref == "operator-1"
    assert ChannelPlan.from_dict(lab.to_dict()) == lab


def test_naive_timestamps_are_rejected_not_compared():
    with pytest.raises(PortfolioError, match="timezone"):
        rights(expires_at="2026-09-27T00:00:00")
    with pytest.raises(PortfolioError, match="timezone"):
        rights_gate([rights(expires_at=NOW)], "2026-09-27T00:00:00")


# --- mandatory channels (v3.1 §4.2, §13 P0.4) ---------------------------------


def signal_plan(**kw) -> ChannelPlan:
    base = dict(
        channel_id="signal-synthetic",
        business_role="product_funnel",
        stage="maintain",
        weekly_publish_cap={"long": 2, "short": 4},
        existence_floor={"long": 1, "short": 2},
        time_sensitivity_hours=48.0,
    )
    base.update(kw)
    return plan(**base)


def test_existence_floor_must_fit_under_cap():
    with pytest.raises(PortfolioError, match="existence_floor"):
        signal_plan(existence_floor={"long": 3})
    with pytest.raises(PortfolioError, match="existence_floor"):
        signal_plan(existence_floor={"reel": 1})


def test_mandatory_channel_cannot_retire_only_pause_or_maintain():
    with pytest.raises(PortfolioError, match="mandatory channel cannot retire"):
        advance_stage(signal_plan(), "retire", [])
    assert advance_stage(signal_plan(), "pause", []).stage == "pause"
    assert advance_stage(plan(stage="maintain"), "retire", []).stage == "retire"


def test_floor_deficit_counts_missing_minimum_per_format():
    assert floor_deficit(signal_plan(), {"long": 0, "short": 1}) == {"long": 1, "short": 1}
    assert floor_deficit(signal_plan(), {"long": 1, "short": 5}) == {"long": 0, "short": 0}
    assert floor_deficit(plan(), {}) == {}


def test_sla_breached_only_with_time_sensitivity():
    detected = "2026-09-24T00:00:00+00:00"
    assert sla_breached(signal_plan(), detected, NOW)
    assert not sla_breached(signal_plan(time_sensitivity_hours=72.0), detected, NOW)
    assert not sla_breached(plan(), detected, NOW)


def test_records_carry_optional_concept_id():
    for record in (
        rights(concept_id="c1"),
        ReleaseUnit("rel-1", "asset-1", concept_id="c1"),
        ProfitSnapshot("c", NOW, "7d", {}, {}, concept_id="c1"),
        FormatHypothesis("h1", "c", "hook", "m", 1, NOW, concept_id="c1"),
        RevenueEvent("c", "paid", 1.0, NOW, "adsense", concept_id="c1"),
    ):
        assert type(record).from_dict(record.to_dict()) == record and record.concept_id == "c1"
    with pytest.raises(PortfolioError):
        rights(concept_id="../c")


# --- portfolio policy and channel registration (capacity analysis 2026-09-27) --


from stigdev.portfolio import DEFAULT_POLICY, PortfolioEvidence, PortfolioPolicy, register_channel  # noqa: E402


def portfolio_evidence(**kw) -> PortfolioEvidence:
    base = dict(review_hours_per_week=10.0, policy_incidents=0)
    base.update(kw)
    return PortfolioEvidence(**base)


def test_default_policy_matches_capacity_analysis():
    assert DEFAULT_POLICY == PortfolioPolicy(max_scale=2, max_active=12, max_pilot=4, max_review_hours_per_week=15.0)
    assert MAX_SCALE_CHANNELS == DEFAULT_POLICY.max_scale


@pytest.mark.parametrize(
    "kw",
    [dict(max_scale=0), dict(max_active=1, max_scale=2), dict(max_pilot=-1), dict(max_review_hours_per_week=0.0)],
)
def test_policy_rejects_incoherent_limits(kw):
    with pytest.raises(PortfolioError):
        PortfolioPolicy(**{**DEFAULT_POLICY.to_dict(), **kw})


def test_commerce_lab_role_registers_with_owner_ref():
    lab = plan(business_role="commerce_lab", channel_id="commerce-lab", owner_ref="owner-1")
    assert register_channel(lab, [], portfolio_evidence()).passed


def test_register_channel_passes_within_limits():
    portfolio = [plan(channel_id=f"ch-{i}", stage="maintain") for i in range(5)]
    decision = register_channel(plan(channel_id="new", stage="hypothesis"), portfolio, portfolio_evidence())
    assert decision == GateDecision("register-gate/v1", True, ())


def test_register_channel_reports_each_blocker():
    portfolio = [plan(channel_id=f"ch-{i}", stage="maintain") for i in range(10)] + [
        plan(channel_id=f"pilot-{i}", stage="public_pilot") for i in range(4)
    ]
    decision = register_channel(
        plan(channel_id="pilot-0", stage="hypothesis"),
        portfolio,
        portfolio_evidence(review_hours_per_week=16.0, policy_incidents=1),
    )
    assert decision.reasons == (
        "channel_id pilot-0 already registered",
        "active channel limit 12 reached",
        "pilot channel limit 4 reached",
        "review hours 16.0 over weekly cap 15.0",
        "policy incidents present",
    )


def test_register_channel_ignores_retired_channels_and_honours_custom_policy():
    portfolio = [plan(channel_id=f"ch-{i}", stage="retire") for i in range(12)]
    assert register_channel(plan(channel_id="new", stage="hypothesis"), portfolio, portfolio_evidence()).passed
    tight = PortfolioPolicy(max_scale=1, max_active=1, max_pilot=1, max_review_hours_per_week=5.0)
    decision = register_channel(plan(channel_id="new", stage="hypothesis"), [plan(channel_id="only")], portfolio_evidence(), tight)
    assert "active channel limit 1 reached" in decision.reasons


def test_advance_to_scale_uses_policy_max_scale():
    loose = PortfolioPolicy(max_scale=3, max_active=12, max_pilot=4, max_review_hours_per_week=15.0)
    others = [plan(channel_id=f"scale-{i}", stage="scale") for i in range(2)]
    assert advance_stage(plan(), "scale", others, scale_evidence(), loose).stage == "scale"
