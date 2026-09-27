"""Offline tests for the payout reconciliation ladder (ADR 0011)."""

import pytest

from stigdev.payout import (
    CASH_STATES,
    DECISION_FLOOR,
    PAYOUT_STATES,
    PayoutError,
    PayoutReconciliation,
    advance_payout,
    risk_adjusted_contribution_margin,
    total_across,
)

START, END = "2026-08-01T00:00:00+00:00", "2026-09-01T00:00:00+00:00"


def record(**kw) -> PayoutReconciliation:
    base = dict(source="synthetic-ads", period_start=START, period_end=END,
                state="observed", amounts={"observed": 1000.0})
    base.update(kw)
    return PayoutReconciliation(**base)


def walk(to: str, amounts=(980.0, 940.0, 900.0, 898.5, 700.0)) -> PayoutReconciliation:
    r = record()
    for state, amount in zip(PAYOUT_STATES[1:], amounts):
        r = advance_payout(r, state, amount)
        if state == to:
            break
    return r


def test_ladder_order_and_floors_are_the_documented_ones():
    assert PAYOUT_STATES == ("observed", "platform_estimated", "platform_finalized",
                             "paid", "bank_reconciled", "net")
    assert DECISION_FLOOR == "platform_finalized"
    assert CASH_STATES == ("paid", "bank_reconciled")


def test_round_trip_through_dict():
    r = walk("paid")
    assert PayoutReconciliation.from_dict(r.to_dict()) == r


def test_ladder_skips_no_rung_and_does_not_run_backwards():
    r = record()
    with pytest.raises(PayoutError, match="skips no rung"):
        advance_payout(r, "paid", 900.0)
    r = advance_payout(r, "platform_estimated", 980.0)
    with pytest.raises(PayoutError, match="skips no rung"):
        advance_payout(r, "observed", 1000.0)
    assert advance_payout(r, "platform_finalized", 940.0).state == "platform_finalized"


def test_top_of_the_ladder_is_terminal():
    with pytest.raises(PayoutError, match="already at net"):
        advance_payout(walk("net"), "net", 1.0)


def test_amounts_may_not_run_ahead_of_the_state():
    with pytest.raises(PayoutError, match="recorded before reaching"):
        record(state="observed", amounts={"observed": 1.0, "paid": 900.0})
    with pytest.raises(PayoutError, match="requires an amount"):
        record(state="platform_estimated", amounts={"observed": 1.0})


def test_estimates_are_not_decision_ready_but_finalized_money_is():
    assert not walk("platform_estimated").decision_ready
    assert walk("platform_finalized").decision_ready


def test_cash_is_refused_until_the_money_actually_arrives():
    with pytest.raises(PayoutError, match="has not reached a cash state"):
        walk("platform_finalized").cash()
    assert walk("paid").cash() == 900.0
    # once reconciled, the bank figure is the one that counts
    assert walk("bank_reconciled").cash() == 898.5


def test_totalling_one_rung_works_and_mixing_rungs_is_refused():
    finalized = walk("platform_finalized")
    estimated = PayoutReconciliation(source="synthetic-affiliate", period_start=START,
                                     period_end=END, state="platform_estimated",
                                     amounts={"observed": 500.0, "platform_estimated": 460.0})
    assert total_across([finalized, estimated], "platform_estimated") == 1440.0
    with pytest.raises(PayoutError, match="cannot total platform_finalized"):
        total_across([finalized, estimated], "platform_finalized")


def test_risk_adjusted_margin_subtracts_every_cost():
    assert risk_adjusted_contribution_margin(
        platform_finalized_revenue=1000.0,
        human_labor=300.0,
        rights_and_asset_cost=50.0,
        compute_and_tool_cost=40.0,
        operator_payout=100.0,
        refund_and_adjustment=10.0,
        expected_policy_loss_reserve=25.0,
    ) == 475.0
    assert risk_adjusted_contribution_margin(platform_finalized_revenue=100.0) == 100.0


@pytest.mark.parametrize(
    "build",
    [
        lambda: record(source="../escape"),
        lambda: record(period_start=END, period_end=START),
        lambda: record(state="settled"),
        lambda: record(amounts={"observed": -1.0}),
        lambda: record(amounts={"observed": float("inf")}),
        lambda: record(amounts={"mystery": 1.0}),
        lambda: advance_payout(record(), "nowhere", 1.0),
        lambda: risk_adjusted_contribution_margin(platform_finalized_revenue=-1.0),
        lambda: walk("paid").amount("net"),
    ],
)
def test_invalid_input_is_rejected(build):
    with pytest.raises(PayoutError):
        build()
