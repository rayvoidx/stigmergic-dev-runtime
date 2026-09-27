"""Payout reconciliation ladder (ADR 0011, v3.3 §5.16.1, v2.1 §14.5).

Money is tracked through six states because the same money appears in several
screens at once: an estimate, a pending payout, and an account balance can all
be the same revenue. They are therefore never summed. Business promotion reads
``platform_finalized`` at the earliest; a monthly cash target reads ``paid`` or
``bank_reconciled`` only.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Any

from .workspace import valid_identifier

# Ordered ladder: each state is a strictly later, better-evidenced view of the
# same money, never an additional amount.
PAYOUT_STATES = (
    "observed",
    "platform_estimated",
    "platform_finalized",
    "paid",
    "bank_reconciled",
    "net",
)
DECISION_FLOOR = "platform_finalized"  # lowest state a scale/forecast decision may read
CASH_STATES = ("paid", "bank_reconciled")  # the only states a cash target may read


class PayoutError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PayoutError(message)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _amount(value: object, name: str) -> float:
    _require(_finite(value) and float(value) >= 0, f"{name} must be a finite non-negative number")
    return float(value)


def _timestamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise PayoutError(f"invalid timestamp {value!r}") from exc
    _require(parsed.tzinfo is not None, f"timestamp {value!r} must be timezone-aware")
    return parsed


@dataclass(frozen=True)
class PayoutReconciliation:
    """One source and period walked up the ladder (v2.1 §5.2 `payout_reconciliations`)."""

    source: str
    period_start: str
    period_end: str
    state: str = "observed"
    amounts: dict[str, float] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        _require(valid_identifier(self.source), "invalid source")
        _require(_timestamp(self.period_start) < _timestamp(self.period_end), "period_end must follow period_start")
        _require(self.state in PAYOUT_STATES, f"unknown state {self.state!r}")
        object.__setattr__(self, "amounts", dict(self.amounts or {}))
        for name, value in self.amounts.items():
            _require(name in PAYOUT_STATES, f"unknown payout state {name!r}")
            _amount(value, name)
        reached = PAYOUT_STATES.index(self.state)
        for name in PAYOUT_STATES[: reached + 1]:
            _require(name in self.amounts, f"state {self.state} requires an amount for {name}")
        for name in PAYOUT_STATES[reached + 1 :]:
            _require(name not in self.amounts, f"amount for {name} recorded before reaching that state")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "PayoutReconciliation":
        return PayoutReconciliation(**raw)

    def amount(self, state: str) -> float:
        _require(state in PAYOUT_STATES, f"unknown payout state {state!r}")
        _require(state in self.amounts, f"{state} not reached for {self.source}")
        return self.amounts[state]

    @property
    def decision_ready(self) -> bool:
        return PAYOUT_STATES.index(self.state) >= PAYOUT_STATES.index(DECISION_FLOOR)

    def cash(self) -> float:
        """Money that actually arrived; raises until the ladder reaches `paid`."""
        _require(self.state in CASH_STATES or PAYOUT_STATES.index(self.state) >= PAYOUT_STATES.index("paid"),
                 f"{self.source} has not reached a cash state (currently {self.state})")
        return self.amounts["bank_reconciled" if "bank_reconciled" in self.amounts else "paid"]


def advance_payout(record: PayoutReconciliation, to: str, amount: float) -> PayoutReconciliation:
    """Move exactly one rung up the ladder and record that rung's amount."""
    _require(to in PAYOUT_STATES, f"unknown payout state {to!r}")
    expected = PAYOUT_STATES.index(record.state) + 1
    _require(expected < len(PAYOUT_STATES), f"{record.source} is already at {record.state}")
    _require(PAYOUT_STATES[expected] == to, f"payout ladder skips no rung: {record.state} -> {to}")
    amounts = dict(record.amounts)
    amounts[to] = _amount(amount, to)
    return replace(record, state=to, amounts=amounts)


def total_across(records: list[PayoutReconciliation], state: str) -> float:
    """Sum one ladder rung across records. Mixing rungs is refused, not coerced."""
    _require(state in PAYOUT_STATES, f"unknown payout state {state!r}")
    missing = [r.source for r in records if state not in r.amounts]
    _require(not missing, f"cannot total {state}: not reached by {', '.join(sorted(missing))}")
    return round(sum(r.amounts[state] for r in records), 6)


def risk_adjusted_contribution_margin(
    *,
    platform_finalized_revenue: float,
    human_labor: float = 0.0,
    rights_and_asset_cost: float = 0.0,
    compute_and_tool_cost: float = 0.0,
    operator_payout: float = 0.0,
    refund_and_adjustment: float = 0.0,
    expected_policy_loss_reserve: float = 0.0,
) -> float:
    """v2.1 §14.5. Revenue must already be finalized; estimates never enter here."""
    revenue = _amount(platform_finalized_revenue, "platform_finalized_revenue")
    costs = (
        _amount(human_labor, "human_labor")
        + _amount(rights_and_asset_cost, "rights_and_asset_cost")
        + _amount(compute_and_tool_cost, "compute_and_tool_cost")
        + _amount(operator_payout, "operator_payout")
        + _amount(refund_and_adjustment, "refund_and_adjustment")
        + _amount(expected_policy_loss_reserve, "expected_policy_loss_reserve")
    )
    return round(revenue - costs, 6)
