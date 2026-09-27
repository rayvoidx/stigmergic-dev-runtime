"""The synthetic 27-channel portfolio fixture exercises the governance rules end to end.

Everything here is generated data: no real channel IDs, audiences, revenue, accounts,
or prompts. The fixture is the regression surface for v3.3 §5.16 and v2.1 §18.2.
"""

import json
from pathlib import Path

import pytest

from stigdev.incident import PolicyIncident, PortfolioGraph, action_allowed, halted_channels
from stigdev.lifecycle import (
    AudienceContract,
    ChannelSlot,
    FormatFingerprint,
    LifecycleError,
    ScaleEvidence,
    advance_lifecycle,
    counts,
)
from stigdev.overlap import ChannelOverlap, review_queue
from stigdev.payout import PayoutReconciliation, total_across
from stigdev.portfolio import DEFAULT_POLICY
from stigdev.revenue import RevenueClaim, classify_claim, modeled_amount

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "synthetic_27_channel_portfolio" / "portfolio.json"


@pytest.fixture(scope="module")
def data() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def slots(data) -> list[ChannelSlot]:
    return [ChannelSlot.from_dict(s) for s in data["channel_slots"]]


def test_fixture_holds_twenty_seven_synthetic_channels(data, slots):
    assert len(slots) == 27
    assert len({s.channel_id for s in slots}) == 27
    assert all(s.channel_id.startswith("synthetic-channel-") for s in slots)


def test_no_real_identifiers_leak_into_the_public_fixture(data):
    blob = json.dumps(data).lower()
    for forbidden in ("youtube.com", "adsense", "oauth", "@gmail", "rayv", "archive stories", "signal stories"):
        assert forbidden not in blob, forbidden
    # the only URL in the fixture is a reserved-for-testing hostname
    assert data["external_revenue_claim"]["source_url"] == "https://example.invalid/synthetic-claim"


def test_portfolio_respects_the_scale_and_active_limits(slots):
    tally = counts(slots)
    assert tally["scale"] == 2 <= DEFAULT_POLICY.max_scale
    assert tally["active"] == 24  # 27 minus three retired


def test_a_third_channel_cannot_join_scale(slots):
    gated = next(s for s in slots if s.lifecycle_state == "monetization_gating")
    evidence = ScaleEvidence(
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
    with pytest.raises(LifecycleError, match="scale limit: 2"):
        advance_lifecycle(gated, "scale", slots, evidence)


def test_every_channel_has_its_own_audience_contract(data, slots):
    contracts = [AudienceContract.from_dict(c) for c in data["audience_contracts"]]
    assert {c.channel_id for c in contracts} == {s.channel_id for s in slots}
    assert len({c.audience for c in contracts}) == 27


def test_the_duplicated_asset_pair_is_caught_by_fingerprints(data):
    prints = {f["channel_id"]: FormatFingerprint.from_dict(f) for f in data["format_fingerprints"]}
    left, right = prints["synthetic-channel-08"], prints["synthetic-channel-20"]
    assert left.shared_assets(right)  # the deliberate cross-channel reuse case
    clean = prints["synthetic-channel-01"]
    assert not clean.shared_assets(prints["synthetic-channel-02"])


def test_the_overlapping_pair_tops_the_review_queue(data):
    overlaps = [ChannelOverlap.from_dict(o) for o in data["channel_overlaps"]]
    queue = review_queue(overlaps)
    assert len(queue) == 1
    assert (queue[0].left_channel_id, queue[0].right_channel_id) == (
        "synthetic-channel-08",
        "synthetic-channel-20",
    )
    assert queue[0].score == 0.8475


def test_month_end_reconciliation_refuses_to_mix_ladder_rungs(data):
    payouts = [PayoutReconciliation.from_dict(p) for p in data["payout_reconciliations"]]
    assert total_across(payouts, "platform_estimated") == 1440.0
    with pytest.raises(Exception, match="cannot total platform_finalized"):
        total_across(payouts, "platform_finalized")
    settled = next(p for p in payouts if p.state == "bank_reconciled")
    assert settled.cash() == 898.5 and settled.decision_ready


def test_the_external_27_channel_claim_never_reaches_a_forecast(data):
    claim = RevenueClaim.from_dict(data["external_revenue_claim"])
    assert claim.evidence_grade == "C"
    assert classify_claim(claim) == "sandbox_only"
    assert modeled_amount(claim) == 0.0
    assert claim.content_ownership is None


def test_the_quarantined_family_stops_publishing_but_the_rest_continues(data, slots):
    incident = PolicyIncident.from_dict(data["policy_incident"])
    graph = PortfolioGraph(channel_family={s.channel_id: s.family_id for s in slots})
    halted = halted_channels(incident, graph)
    assert halted == {s.channel_id for s in slots if s.family_id == "archive-tales"}
    assert halted
    for channel in halted:
        assert not action_allowed("publish", channel_id=channel, incidents=[incident], graph=graph)
        assert action_allowed("read", channel_id=channel, incidents=[incident], graph=graph)
    untouched = next(s for s in slots if s.family_id != "archive-tales")
    assert action_allowed("publish", channel_id=untouched.channel_id, incidents=[incident], graph=graph)
