"""Offline tests for the monthly capacity envelope and revenue sensitivity (ADR 0013)."""

import pytest

from stigdev.capacity import (
    HOURS_PER_MONTH,
    PLANNING_COSTS,
    SHORTS_POOL_SHARE,
    WATCH_PAGE_SHARE,
    ArtifactCost,
    CapacityBudget,
    CapacityError,
    ChannelDemand,
    budget_from,
    capacity_gate,
    capacity_report,
    months_until_archive_full,
    project_revenue,
    review_hours_per_week,
    shorts_pool_floor,
)
from stigdev.node import MOBILE_M4, STUDIO_M5_ULTRA
from stigdev.portfolio import PortfolioEvidence, gross_revenue, register_channel, revenue_by_kind
from stigdev.revenue import PolicySnapshot

NOW = "2026-09-29T00:00:00+00:00"

# The 12-channel composition from the capacity analysis: 2 Shorts winners,
# 5 hybrids, 2 long-form IP channels, 3 pilot/maintenance slots.
CADENCE = {
    "shorts_winner": {"short": 30},
    "hybrid": {"short": 12, "long": 2},
    "longform_ip": {"short": 4, "long": 3},
    "pilot": {"short": 4},
}
COMPOSITIONS = {
    8: ("shorts_winner", "shorts_winner", "hybrid", "hybrid", "hybrid", "longform_ip", "longform_ip", "pilot"),
    10: (
        "shorts_winner", "shorts_winner", "hybrid", "hybrid", "hybrid", "hybrid",
        "longform_ip", "longform_ip", "pilot", "pilot",
    ),
    12: (
        "shorts_winner", "shorts_winner", "hybrid", "hybrid", "hybrid", "hybrid", "hybrid",
        "longform_ip", "longform_ip", "pilot", "pilot", "pilot",
    ),
}


def portfolio(size: int) -> tuple[ChannelDemand, ...]:
    return tuple(
        ChannelDemand(channel_id=f"synthetic-{i}", monthly=dict(CADENCE[kind]))
        for i, kind in enumerate(COMPOSITIONS[size])
    )


def budget(**kw) -> CapacityBudget:
    base = dict(
        profile=STUDIO_M5_ULTRA,
        utilization=0.70,
        operator_review_hours_per_week=15.0,
        disk_gb=1000.0,
        retention_days=14,
    )
    base.update(kw)
    return budget_from(**base)


# --- records ------------------------------------------------------------------


def test_records_round_trip_through_dict():
    for record in (PLANNING_COSTS["short"], budget(), portfolio(8)[0]):
        assert type(record).from_dict(record.to_dict()) == record


@pytest.mark.parametrize(
    "build",
    [
        lambda: ArtifactCost(gpu_hours=-1.0, review_hours=0.25, working_gb=3.0, archive_gb=0.5),
        lambda: ArtifactCost(gpu_hours=float("inf"), review_hours=0.25, working_gb=3.0, archive_gb=0.5),
        lambda: ChannelDemand(channel_id="../secret", monthly={"short": 1}),
        lambda: ChannelDemand(channel_id="c", monthly={"reel": 1}),
        lambda: ChannelDemand(channel_id="c", monthly={"short": -1}),
        lambda: budget(utilization=0.0),
        lambda: budget(utilization=1.5),
        lambda: budget(retention_days=0),
        lambda: budget(operator_review_hours_per_week=0.0),
        lambda: budget(disk_gb=-5.0),
    ],
)
def test_invalid_inputs_are_rejected_at_construction(build):
    with pytest.raises(CapacityError):
        build()


# --- budget derivation ---------------------------------------------------------


def test_seventy_percent_of_a_month_is_the_gpu_budget():
    # 24h x 30d x 0.70 = 504 GPU hours/month
    assert HOURS_PER_MONTH == 720
    assert budget().gpu_hours == pytest.approx(504.0)
    assert budget(utilization=0.5).gpu_hours == pytest.approx(360.0)


def test_memory_ceiling_takes_the_tighter_of_node_reserve_and_utilization():
    # ADR 0012 reserves 20GB of 96 (76 usable); the capacity analysis caps at 70% (67.2). Plan on the smaller.
    assert budget().memory_ceiling_gb == pytest.approx(67.2)
    assert budget(utilization=0.95).memory_ceiling_gb == pytest.approx(76.0)


def test_budget_carries_the_node_it_was_derived_from():
    assert budget().node_id == "studio-m5-ultra"
    assert budget_from(profile=MOBILE_M4, utilization=0.70, operator_review_hours_per_week=15.0,
                       disk_gb=500.0, retention_days=14).node_id == "mobile-m4"


def test_operator_hours_convert_weekly_to_monthly():
    assert budget().review_hours == pytest.approx(15.0 * 30 / 7)


# --- the analysis envelope reproduced from the shipped planning costs ----------


def test_ten_channels_land_inside_the_stated_monthly_production_envelope():
    report = capacity_report(portfolio(10), budget())
    assert 120 <= report["artifacts"]["short"] <= 180
    assert 12 <= report["artifacts"]["long"] <= 24
    assert 60 <= report["review_hours"]["used"] <= 100


def test_the_machine_is_not_the_constraint_at_twelve_channels():
    report = capacity_report(portfolio(12), budget())
    assert report["gpu_hours"]["used"] < report["gpu_hours"]["available"]
    assert report["gpu_hours"]["deficit"] == 0.0


def test_human_review_is_what_breaks_first_past_ten_channels():
    assert capacity_gate(portfolio(8), budget()).passed
    twelve = capacity_gate(portfolio(12), budget())
    assert not twelve.passed
    assert any("review" in reason for reason in twelve.reasons)
    assert not any("gpu" in reason for reason in twelve.reasons)


def test_twelve_channels_fit_once_the_operator_buys_more_review_capacity():
    assert capacity_gate(portfolio(12), budget(operator_review_hours_per_week=20.0)).passed


def test_gate_reports_every_exhausted_resource_at_once():
    starved = capacity_gate(portfolio(12), budget(operator_review_hours_per_week=1.0, disk_gb=50.0, utilization=0.05))
    assert not starved.passed
    assert len(starved.reasons) == 3


# --- feeding the existing portfolio gate ---------------------------------------


def _plan(channel_id: str):
    from stigdev.portfolio import ChannelPlan

    return ChannelPlan(
        channel_id=channel_id,
        business_role="cash_engine",
        stage="hypothesis",
        audience_contract="synthetic",
        weekly_publish_cap={"long": 1, "short": 3},
    )


def test_review_hours_per_week_feeds_the_portfolio_register_gate():
    # portfolio.register_channel takes this number on faith; here it is derived from the publish plan.
    weekly = review_hours_per_week(portfolio(12))
    assert weekly > 15.0
    decision = register_channel(
        plan=_plan("new-channel"),
        portfolio=[],
        evidence=PortfolioEvidence(review_hours_per_week=weekly, policy_incidents=0),
    )
    assert not decision.passed
    assert any("review hours" in reason for reason in decision.reasons)


# --- storage -------------------------------------------------------------------


def test_fourteen_day_cleanup_is_what_keeps_the_working_set_on_the_internal_disk():
    kept = capacity_report(portfolio(12), budget(retention_days=14))
    assert kept["working_gb"]["deficit"] == 0.0
    hoarded = capacity_report(portfolio(12), budget(retention_days=30))
    assert hoarded["working_gb"]["deficit"] > 0.0


def test_archive_growth_predicts_when_external_storage_is_needed():
    months = months_until_archive_full(portfolio(12), budget())
    assert 3.0 <= months <= 8.0
    assert months_until_archive_full(portfolio(8), budget()) > months
    assert months_until_archive_full((), budget()) is None


# --- 2027 Shorts pool retention floor ------------------------------------------


def floor_policy(**kw) -> PolicySnapshot:
    base = dict(
        policy_id="shorts-pool-2027",
        feature="shorts_pool",
        applies_to="all",
        effective_from="2027-02-01T00:00:00+00:00",
        captured_at=NOW,
        source_url="https://example.invalid/policy",
        thresholds={"qualified_shorts_views_90d": 10_000_000},
    )
    base.update(kw)
    return PolicySnapshot(**base)


def test_below_floor_channels_are_named_and_the_aggregate_requirement_is_reported():
    projected = {f"synthetic-{i}": 9_000_000 for i in range(12)}
    projected["synthetic-0"] = 40_000_000
    result = shorts_pool_floor(projected, floor_policy(), at="2027-03-01T00:00:00+00:00")
    assert result["below_floor"] == sorted(f"synthetic-{i}" for i in range(1, 12))
    assert "synthetic-0" not in result["below_floor"]
    # 12 channels x 10M per 90 days is about 40M qualified Shorts views every month
    assert result["monthly_views_required"] == pytest.approx(40_000_000, rel=0.01)
    assert result["in_effect"] is True


def test_the_floor_does_not_bind_before_its_effective_date():
    result = shorts_pool_floor({"synthetic-0": 1}, floor_policy(), at="2026-12-01T00:00:00+00:00")
    assert result["in_effect"] is False
    assert result["below_floor"] == []


def test_missing_the_shorts_floor_never_removes_long_form_revenue():
    result = shorts_pool_floor({"c": 0}, floor_policy(), at="2027-03-01T00:00:00+00:00")
    assert result["below_floor"] == ["c"]
    assert result["long_form_revenue_at_risk"] is False


# --- revenue sensitivity --------------------------------------------------------


@pytest.mark.parametrize(
    "short_views, long_views, short_rpm, long_rpm, expected_krw",
    [
        (8_000_000, 400_000, 0.07, 2.0, 1_849_600),
        (20_000_000, 1_200_000, 0.10, 2.7, 7_126_400),
        (35_000_000, 2_200_000, 0.13, 3.2, 15_762_400),
        (60_000_000, 4_000_000, 0.18, 4.0, 36_448_000),
    ],
)
def test_the_four_sensitivity_stages_reproduce_the_analysis_arithmetic(
    short_views, long_views, short_rpm, long_rpm, expected_krw
):
    events = project_revenue(
        channel_id="portfolio",
        views={"short": short_views, "long": long_views},
        rpm_usd={"short": short_rpm, "long": long_rpm},
        usd_krw=1360.0,
        occurred_at=NOW,
    )
    assert sum(e.amount for e in events) == pytest.approx(expected_krw, rel=1e-6)


def test_a_projection_is_structurally_barred_from_counting_as_money():
    events = project_revenue(
        channel_id="portfolio",
        views={"short": 20_000_000, "long": 1_200_000},
        rpm_usd={"short": 0.10, "long": 2.7},
        usd_krw=1360.0,
        occurred_at=NOW,
    )
    assert {e.kind for e in events} == {"estimated"}
    assert gross_revenue(events) == 0.0
    assert revenue_by_kind(events)["estimated"] == pytest.approx(7_126_400, rel=1e-6)


def test_platform_shares_are_documentation_and_are_never_applied_twice():
    # RPM inputs are already creator-side (post-split), so the constants exist to be read, not multiplied.
    assert WATCH_PAGE_SHARE == 0.55
    assert SHORTS_POOL_SHARE == 0.45
    plain = project_revenue(
        channel_id="c", views={"short": 1_000_000}, rpm_usd={"short": 0.10}, usd_krw=1000.0, occurred_at=NOW
    )
    assert plain[0].amount == pytest.approx(100_000.0)


def test_projection_refuses_a_format_it_has_no_rpm_for():
    with pytest.raises(CapacityError):
        project_revenue(
            channel_id="c", views={"short": 1, "long": 1}, rpm_usd={"short": 0.10}, usd_krw=1360.0, occurred_at=NOW
        )


# --- the seam into the lifecycle scale gate (gap 11) ---------------------------


def scale_evidence(capacity: bool):
    from stigdev.lifecycle import ScaleEvidence

    return ScaleEvidence(
        independent_audience_contract=True,
        rights_originality_disclosure_pass=True,
        positive_margin_cohorts=3,
        holds_without_top_video=True,
        overlap_review_passed=True,
        policy_strikes=0,
        unresolved_rights_incidents=0,
        capacity_available=capacity,
        approved_by="operator",
    )


def test_capacity_available_is_derived_not_asserted():
    from stigdev.capacity import capacity_available

    assert capacity_available(portfolio(8), budget()) is True
    assert capacity_available(portfolio(12), budget()) is False


def test_an_over_committed_plan_cannot_scale_another_channel():
    from stigdev.capacity import capacity_available
    from stigdev.lifecycle import scale_gate

    fits = scale_gate(scale_evidence(capacity_available(portfolio(8), budget())))
    assert fits.passed
    starved = scale_gate(scale_evidence(capacity_available(portfolio(12), budget())))
    assert not starved.passed
    assert any("capacity" in reason for reason in starved.reasons)
