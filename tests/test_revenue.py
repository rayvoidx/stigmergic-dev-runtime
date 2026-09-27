"""Offline tests for revenue intelligence contracts (ADR 0009): claims, policy, experiments, commerce."""

from dataclasses import replace

import pytest

from stigdev import ecosystem
from stigdev.portfolio import GateDecision
from stigdev.revenue import (
    COMMERCE_EVENT_TYPES,
    COMMERCE_LAB_GATE_ID,
    CommerceEvent,
    CommerceLabEvidence,
    ExperimentCard,
    PolicySnapshot,
    RevenueClaim,
    RevenueError,
    authorize_commerce_event,
    classify_claim,
    commerce_lab_promotion_gate,
    commerce_ledger,
    finalization_ratio,
    margin_per_human_hour,
    modeled_amount,
    net_epc,
    order_state,
    policy_in_effect,
    survivorship_ratio,
)

NOW = "2026-09-27T00:00:00+00:00"


def at(hour: int) -> str:
    return f"2026-09-27T{hour:02d}:00:00+00:00"


def claim(**kw) -> RevenueClaim:
    base = dict(
        claim_id="rc-synthetic-1",
        source_url="https://example.invalid/watch/synthetic",
        captured_at=NOW,
        subject="channel_operator",
        scope="single_video",
        amount=113000000.0,
        currency="KRW",
        evidence_grade="C",
        period_start="2026-01-01T00:00:00+00:00",
        period_end="2026-03-31T00:00:00+00:00",
        revenue_streams=("affiliate",),
        accounting_basis="unknown",
        linked_offer_or_course=True,
    )
    base.update(kw)
    return RevenueClaim(**base)


def policy(**kw) -> PolicySnapshot:
    base = dict(
        policy_id="ypp-ads-2027",
        feature="ads_premium",
        applies_to="new_entrant",
        effective_from="2027-02-01T00:00:00+00:00",
        captured_at=NOW,
        source_url="https://example.invalid/policy",
        thresholds={"subscribers": 1000, "qualified_watch_hours_365d": 8000, "qualified_shorts_views_90d": 20000000},
    )
    base.update(kw)
    return PolicySnapshot(**base)


def card(**kw) -> ExperimentCard:
    base = dict(
        experiment_id="exp-c01",
        hypothesis="original_demo_outperforms_recut_ugc",
        channel_id="commerce-lab-private",
        cohort="2026-q4-c01",
        primary_metric="finalized_contribution_margin_per_human_hour",
        leading_metrics=("engaged_view_rate", "product_click_rate", "order_rate"),
        guardrails=("rights_incidents", "disclosure_errors", "refund_rate", "complaint_rate"),
        variants=("hook_a", "hook_b"),
        holdout=True,
        registered_at="2026-09-27T00:00:00+00:00",
        start_at="2026-10-01T00:00:00+00:00",
        decision_at="2027-01-29T00:00:00+00:00",
        stop_rule="any_rights_incident_or_negative_margin",
    )
    base.update(kw)
    return ExperimentCard(**base)


def event(event_type: str, hour: int, order_id: str | None = "o1", amount: float | None = None, **kw) -> CommerceEvent:
    base = dict(
        event_id=f"evt-{event_type}-{order_id}-{hour}",
        event_type=event_type,
        occurred_at=at(hour),
        channel_id="commerce-lab-private",
        order_id=order_id,
        amount=amount,
    )
    base.update(kw)
    return CommerceEvent(**base)


def lab_evidence(**kw) -> CommerceLabEvidence:
    base = dict(
        original_ratio=1.0,
        qa_passed_artifacts=30,
        claims_sourced=True,
        public_pilot_days=30,
        attribution_chain_complete=True,
        positive_margin_cohorts=3,
        education_sales_separated=True,
        independent_brand=True,
    )
    base.update(kw)
    return CommerceLabEvidence(**base)


# --- records -----------------------------------------------------------------


@pytest.mark.parametrize(
    "record",
    [
        claim(),
        policy(),
        card(),
        event("CommissionFinalized", 3, amount=180.0),
        event("RawViewObserved", 1, order_id=None),
    ],
)
def test_records_round_trip_through_dict(record):
    assert type(record).from_dict(record.to_dict()) == record


@pytest.mark.parametrize(
    "build",
    [
        lambda: claim(evidence_grade="E"),
        lambda: claim(scope="video"),
        lambda: claim(accounting_basis="cash"),
        lambda: claim(amount=-1.0),
        lambda: claim(revenue_streams=("tips",)),
        lambda: claim(period_end="2025-12-31T00:00:00+00:00"),
        lambda: claim(captured_at="2026-09-27T00:00:00"),
        lambda: policy(applies_to="everyone"),
        lambda: policy(feature="vibes"),
        lambda: policy(thresholds={"subscribers": float("nan")}),
        lambda: card(variants=("only_one",)),
        lambda: card(guardrails=()),
        lambda: card(decision_at="2026-10-01T00:00:00+00:00"),
        lambda: card(registered_at="2026-10-02T00:00:00+00:00"),
        lambda: card(stop_rule=" "),
        lambda: event("ViewsHappened", 1),
        lambda: event("OrderAttributed", 1, order_id=None),
        lambda: event("CommissionFinalized", 1),
        lambda: event("CommissionPaid", 1, amount=-5.0),
    ],
)
def test_invalid_records_are_rejected_at_construction(build):
    with pytest.raises(RevenueError):
        build()


# --- revenue claim registry ----------------------------------------------------


@pytest.mark.parametrize(
    "grade, decision",
    [("A", "policy_rule"), ("B", "hypothesis"), ("C", "sandbox_only"), ("D", "observe_only")],
)
def test_complete_claims_classify_by_evidence_grade(grade, decision):
    assert classify_claim(claim(evidence_grade=grade)) == decision


@pytest.mark.parametrize(
    "missing",
    [
        dict(scope="unknown"),
        dict(period_start=None),
        dict(period_end=None),
        dict(revenue_streams=()),
        dict(linked_offer_or_course=None),
    ],
)
def test_missing_scope_period_or_sales_interest_demotes_to_sandbox(missing):
    # v3.2 §13 P0.15
    assert classify_claim(claim(evidence_grade="A", **missing)) == "sandbox_only"
    assert classify_claim(claim(evidence_grade="B", **missing)) == "sandbox_only"
    assert classify_claim(claim(evidence_grade="D", **missing)) == "observe_only"


def test_only_grade_a_settled_amounts_enter_models():
    # v3.2 §5.15.4: a title figure is never a model input; empty evidence is a conservative zero
    settled = claim(evidence_grade="A", accounting_basis="finalized")
    assert modeled_amount(settled) == 113000000.0
    assert modeled_amount(replace(settled, accounting_basis="estimated")) == 0.0
    assert modeled_amount(replace(settled, evidence_grade="C")) == 0.0
    assert modeled_amount(replace(settled, period_start=None)) == 0.0


# --- policy watch --------------------------------------------------------------


def test_policy_in_effect_picks_latest_effective_snapshot_for_channel_status():
    old = policy(policy_id="ypp-ads-2023", effective_from="2023-06-13T00:00:00+00:00", applies_to="all",
                 thresholds={"subscribers": 1000, "watch_hours_365d": 4000})
    new = policy()
    snaps = [new, old]
    assert policy_in_effect(snaps, "ads_premium", "new_entrant", "2026-09-27T00:00:00+00:00") == old
    assert policy_in_effect(snaps, "ads_premium", "new_entrant", "2027-02-01T00:00:00+00:00") == new


def test_new_entrant_policy_does_not_reach_existing_channels():
    # v3.2 §5.15.2 #1: false urgency for already-monetized channels is blocked at the data layer
    assert policy_in_effect([policy()], "ads_premium", "existing", "2027-06-01T00:00:00+00:00") is None
    assert policy_in_effect([policy()], "shopping", "new_entrant", "2027-06-01T00:00:00+00:00") is None


# --- commerce events, order state machine, ledger -------------------------------


def test_commerce_events_are_structurally_outside_the_canon_vocabulary():
    assert len(COMMERCE_EVENT_TYPES) == 15
    assert set(COMMERCE_EVENT_TYPES).isdisjoint(ecosystem.EVENT_TYPES)


@pytest.mark.parametrize(
    "sequence, state",
    [
        (["OrderAttributed"], "attributed"),
        (["OrderAttributed", "CommissionEstimated"], "attributed"),
        (["OrderAttributed", "CommissionEstimated", "CommissionFinalized"], "finalized"),
        (["OrderAttributed", "CommissionFinalized", "CommissionPaid"], "paid"),
        (["OrderAttributed", "OrderCancelled"], "cancelled"),
        (["OrderAttributed", "CommissionEstimated", "ProductReturned"], "returned"),
    ],
)
def test_order_state_follows_attributed_cancelled_returned_finalized_paid(sequence, state):
    events = [event(t, hour, amount=10.0 if t.startswith("Commission") else None) for hour, t in enumerate(sequence, 1)]
    assert order_state(events) == state


@pytest.mark.parametrize(
    "sequence",
    [
        ["CommissionFinalized"],
        ["OrderAttributed", "CommissionPaid"],
        ["OrderAttributed", "OrderCancelled", "CommissionFinalized"],
        ["OrderAttributed", "CommissionFinalized", "ProductReturned"],
        ["OrderAttributed", "OrderAttributed"],
    ],
)
def test_invalid_order_transitions_raise(sequence):
    events = [event(t, hour, amount=10.0 if t.startswith("Commission") else None) for hour, t in enumerate(sequence, 1)]
    with pytest.raises(RevenueError):
        order_state(events)


def test_order_state_ignores_input_order_but_not_time_order():
    events = [
        event("CommissionFinalized", 3, amount=10.0),
        event("OrderAttributed", 1),
        event("CommissionEstimated", 2, amount=12.0),
    ]
    assert order_state(events) == "finalized"


def test_ledger_never_sums_estimates_into_finalized_or_paid():
    # v3.2 §5.15.7: estimated -> nothing, finalized -> contribution margin, paid -> owner cash
    events = [
        event("OrderAttributed", 1, order_id="o1"),
        event("CommissionEstimated", 2, order_id="o1", amount=100.0),
        event("OrderAttributed", 1, order_id="o2"),
        event("CommissionEstimated", 2, order_id="o2", amount=200.0),
        event("CommissionFinalized", 3, order_id="o2", amount=180.0),
        event("CommissionPaid", 4, order_id="o2", amount=180.0),
        event("OrderAttributed", 1, order_id="o3"),
        event("CommissionEstimated", 2, order_id="o3", amount=50.0),
        event("OrderCancelled", 3, order_id="o3"),
        event("AffiliateLinkClicked", 0, order_id=None),
    ]
    ledger = commerce_ledger(events)
    assert ledger["orders"] == {"o1": "attributed", "o2": "paid", "o3": "cancelled"}
    assert ledger["estimated"] == 100.0
    assert ledger["finalized"] == 180.0
    assert ledger["paid"] == 180.0


def test_commerce_roles_are_separated_and_never_write_canon():
    # v3.2 §13 P0.17: commerce workers run under their own permissions
    click = event("AffiliateLinkClicked", 1, order_id=None)
    assert authorize_commerce_event("commerce_analytics", click) == click
    with pytest.raises(RevenueError):
        authorize_commerce_event("policy_watch", click)
    with pytest.raises(RevenueError):
        authorize_commerce_event("canon_reviewer", click)
    warning = event("ChannelPolicyWarning", 1, order_id=None)
    assert authorize_commerce_event("policy_watch", warning) == warning


# --- integrity ratios ------------------------------------------------------------


def test_ratios_omit_undefined_values_instead_of_writing_zero():
    assert finalization_ratio(finalized=180.0, estimated=200.0) == 0.9
    assert finalization_ratio(finalized=0.0, estimated=0.0) is None
    assert net_epc(finalized=180.0, direct_variable_cost=30.0, qualified_clicks=100) == 1.5
    assert net_epc(finalized=180.0, direct_variable_cost=30.0, qualified_clicks=0) is None
    assert margin_per_human_hour(contribution_margin=600.0, human_hours=4.0) == 150.0
    assert margin_per_human_hour(contribution_margin=600.0, human_hours=0.0) is None
    assert survivorship_ratio(winners=3, attempts=30) == 0.1
    assert survivorship_ratio(winners=0, attempts=0) is None
    with pytest.raises(RevenueError):
        survivorship_ratio(winners=4, attempts=3)


# --- commerce lab promotion gate -------------------------------------------------


def test_commerce_lab_promotion_gate_passes_on_all_seven_conditions():
    assert commerce_lab_promotion_gate(lab_evidence()) == GateDecision(COMMERCE_LAB_GATE_ID, True, ())


def test_commerce_lab_promotion_gate_reports_every_failed_condition():
    decision = commerce_lab_promotion_gate(
        lab_evidence(original_ratio=0.9, qa_passed_artifacts=29, public_pilot_days=10, positive_margin_cohorts=2)
    )
    assert not decision.passed
    assert len(decision.reasons) == 4


@pytest.mark.parametrize(
    "broken",
    [
        dict(claims_sourced=False),
        dict(attribution_chain_complete=False),
        dict(education_sales_separated=False),
        dict(independent_brand=False),
    ],
)
def test_commerce_lab_promotion_gate_fails_closed_on_each_boolean_condition(broken):
    decision = commerce_lab_promotion_gate(lab_evidence(**broken))
    assert not decision.passed and len(decision.reasons) == 1
