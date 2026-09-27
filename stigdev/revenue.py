"""Revenue intelligence contracts (ADR 0009).

Pure records and functions for the v3.2 amendment: external revenue claims
are graded evidence, never model inputs; platform policy thresholds carry
their effective date and audience; experiments are registered before data;
commerce money moves through attributed -> cancelled/returned/finalized ->
paid and only finalized reaches contribution margin, only paid reaches cash.
Real claims, offers, orders, and cohorts stay private; fixtures are synthetic.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable

from .portfolio import GateDecision
from .workspace import valid_identifier

EVIDENCE_GRADES = ("A", "B", "C", "D")
# v3.2 §5.15.1 table: what each grade may be used for. Ordered strongest -> weakest.
CLAIM_DECISIONS = ("policy_rule", "hypothesis", "sandbox_only", "observe_only")
GRADE_DECISION: dict[str, str] = dict(zip(EVIDENCE_GRADES, CLAIM_DECISIONS))
CLAIM_SCOPES = ("single_video", "channel", "portfolio", "company", "lifetime", "unknown")
ACCOUNTING_BASES = ("gross_sales", "estimated", "finalized", "paid", "net", "unknown")
SETTLED_BASES = ("finalized", "paid", "net")
REVENUE_STREAMS = ("ads", "premium", "affiliate", "sponsor", "course", "product")

POLICY_FEATURES = ("ads_premium", "shorts_pool", "fan_funding", "shopping", "view_counting", "reused_content")
APPLIES_TO = ("new_entrant", "existing", "all")

# v3.2 §5.15.7: revenue events added to the OS. Disjoint from ecosystem.EVENT_TYPES by construction.
COMMERCE_EVENT_TYPES = (
    "RawViewObserved",
    "EngagedViewObserved",
    "QualifiedViewObserved",
    "ProductTagged",
    "AffiliateLinkClicked",
    "OrderAttributed",
    "OrderCancelled",
    "ProductReturned",
    "CommissionEstimated",
    "CommissionFinalized",
    "CommissionPaid",
    "SponsorBooked",
    "CourseLeadCaptured",
    "PolicyThresholdChanged",
    "ChannelPolicyWarning",
)
ORDER_EVENT_TYPES = COMMERCE_EVENT_TYPES[5:11]
MONEY_EVENT_TYPES = ("CommissionEstimated", "CommissionFinalized", "CommissionPaid")
# v3.2 §13 P0.14 state machine: state -> {event_type: next_state}. Estimates never move the state.
ORDER_TRANSITIONS: dict[str | None, dict[str, str]] = {
    None: {"OrderAttributed": "attributed"},
    "attributed": {
        "CommissionEstimated": "attributed",
        "OrderCancelled": "cancelled",
        "ProductReturned": "returned",
        "CommissionFinalized": "finalized",
    },
    "finalized": {"CommissionPaid": "paid"},
    "paid": {},
    "cancelled": {},
    "returned": {},
}
# v3.2 §13 P0.17: commerce and policy workers hold their own permissions; none can emit canon events.
ROLE_EVENT_TYPES: dict[str, tuple[str, ...]] = {
    "commerce_analytics": COMMERCE_EVENT_TYPES[:11],
    "partnerships": ("SponsorBooked", "CourseLeadCaptured"),
    "policy_watch": ("PolicyThresholdChanged", "ChannelPolicyWarning"),
}

COMMERCE_LAB_GATE_ID = "commerce-lab-gate/v1"
MIN_LAB_ARTIFACTS = 30
MIN_LAB_PILOT_DAYS = 30
MIN_LAB_POSITIVE_COHORTS = 3


class RevenueError(ValueError):
    def __init__(self, message: str, reasons: tuple[str, ...] = ()):
        super().__init__(message)
        self.reasons = reasons


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RevenueError(message)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _identifier(value: object, name: str) -> None:
    _require(valid_identifier(value), f"invalid {name}")


def _optional_identifier(value: object, name: str) -> None:
    _require(value is None or valid_identifier(value), f"invalid {name}")


def _timestamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise RevenueError(f"invalid timestamp {value!r}") from exc
    _require(parsed.tzinfo is not None, f"timestamp {value!r} must be timezone-aware")
    return parsed


class _Record:
    _tuple_fields: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[call-overload]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]):
        data = dict(raw)
        for key in cls._tuple_fields:
            if key in data:
                data[key] = tuple(data[key])
        return cls(**data)


@dataclass(frozen=True)
class RevenueClaim(_Record):
    """An external success story normalised into checkable parts (v3.2 §5.15.4)."""

    _tuple_fields = ("revenue_streams",)

    claim_id: str
    source_url: str
    captured_at: str
    subject: str
    scope: str
    amount: float
    currency: str
    evidence_grade: str
    period_start: str | None = None
    period_end: str | None = None
    revenue_streams: tuple[str, ...] = ()
    accounting_basis: str = "unknown"
    platform_policy_era: str | None = None
    geography: str | None = None
    content_ownership: str | None = None
    direct_costs_known: bool = False
    refunds_known: bool = False
    human_hours_known: bool = False
    linked_offer_or_course: bool | None = None

    def __post_init__(self) -> None:
        _identifier(self.claim_id, "claim_id")
        _require(bool(self.source_url.strip()), "source_url missing")
        _timestamp(self.captured_at)
        _require(self.scope in CLAIM_SCOPES, f"unknown scope {self.scope!r}")
        _require(_finite(self.amount) and self.amount >= 0, "amount must be a finite non-negative number")
        _require(self.evidence_grade in EVIDENCE_GRADES, f"unknown evidence_grade {self.evidence_grade!r}")
        _require(self.accounting_basis in ACCOUNTING_BASES, f"unknown accounting_basis {self.accounting_basis!r}")
        _require(all(s in REVENUE_STREAMS for s in self.revenue_streams), "unknown revenue stream")
        if self.period_start is not None and self.period_end is not None:
            _require(_timestamp(self.period_start) <= _timestamp(self.period_end), "period_end before period_start")
        else:
            for value in (self.period_start, self.period_end):
                if value is not None:
                    _timestamp(value)


def classify_claim(claim: RevenueClaim) -> str:
    """Grade decides use; a missing scope, period, or sales-interest answer demotes to sandbox (§13 P0.15)."""
    decision = GRADE_DECISION[claim.evidence_grade]
    incomplete = (
        claim.scope == "unknown"
        or claim.period_start is None
        or claim.period_end is None
        or not claim.revenue_streams
        or claim.linked_offer_or_course is None
    )
    if incomplete:
        decision = max(decision, "sandbox_only", key=CLAIM_DECISIONS.index)
    return decision


def modeled_amount(claim: RevenueClaim) -> float:
    """The only claim amount a model may consume: grade A, settled basis, complete; otherwise 0 (§5.15.4)."""
    usable = classify_claim(claim) == "policy_rule" and claim.accounting_basis in SETTLED_BASES
    return claim.amount if usable else 0.0


@dataclass(frozen=True)
class PolicySnapshot(_Record):
    """One platform rule as of a date, with the audience it binds (v3.2 §5.15.3, §13 P0.16)."""

    policy_id: str
    feature: str
    applies_to: str
    effective_from: str
    captured_at: str
    source_url: str
    thresholds: dict[str, float]

    def __post_init__(self) -> None:
        _identifier(self.policy_id, "policy_id")
        _require(self.feature in POLICY_FEATURES, f"unknown feature {self.feature!r}")
        _require(self.applies_to in APPLIES_TO, f"unknown applies_to {self.applies_to!r}")
        _timestamp(self.effective_from)
        _timestamp(self.captured_at)
        _require(bool(self.source_url.strip()), "source_url missing")
        _require(all(_finite(v) for v in self.thresholds.values()), "thresholds must be finite numbers")


def policy_in_effect(
    snapshots: Iterable[PolicySnapshot],
    feature: str,
    channel_status: str,
    at: str,
) -> PolicySnapshot | None:
    """Latest snapshot for this feature that binds this channel status at `at`; None when none does."""
    _require(channel_status in APPLIES_TO[:2], f"unknown channel_status {channel_status!r}")
    moment = _timestamp(at)
    binding = [
        s
        for s in snapshots
        if s.feature == feature and s.applies_to in (channel_status, "all") and _timestamp(s.effective_from) <= moment
    ]
    return max(binding, key=lambda s: _timestamp(s.effective_from), default=None)


@dataclass(frozen=True)
class ExperimentCard(_Record):
    """Pre-registered experiment: hypothesis, metrics, guardrails, and stop rule fixed before data (§5.15.6)."""

    _tuple_fields = ("leading_metrics", "guardrails", "variants")

    experiment_id: str
    hypothesis: str
    channel_id: str
    cohort: str
    primary_metric: str
    leading_metrics: tuple[str, ...]
    guardrails: tuple[str, ...]
    variants: tuple[str, ...]
    holdout: bool
    registered_at: str
    start_at: str
    decision_at: str
    stop_rule: str

    def __post_init__(self) -> None:
        _identifier(self.experiment_id, "experiment_id")
        _require(bool(self.hypothesis.strip()), "hypothesis missing")
        _identifier(self.channel_id, "channel_id")
        _identifier(self.cohort, "cohort")
        _identifier(self.primary_metric, "primary_metric")
        _require(all(valid_identifier(m) for m in self.leading_metrics), "invalid leading_metrics")
        _require(bool(self.guardrails) and all(valid_identifier(g) for g in self.guardrails), "at least one guardrail")
        _require(len(self.variants) >= 2 and all(valid_identifier(v) for v in self.variants), "at least two variants")
        registered, start, decision = (_timestamp(t) for t in (self.registered_at, self.start_at, self.decision_at))
        _require(registered <= start, "experiment must be registered before it starts")
        _require(start < decision, "decision_at must follow start_at")
        _require(bool(self.stop_rule.strip()), "stop_rule missing")


@dataclass(frozen=True)
class CommerceEvent(_Record):
    """One revenue observation (v3.2 §5.15.7). Amounts are synthetic here; real orders stay private."""

    event_id: str
    event_type: str
    occurred_at: str
    channel_id: str
    order_id: str | None = None
    amount: float | None = None
    concept_id: str | None = None
    derivative_id: str | None = None
    experiment_id: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.event_id, "event_id")
        _require(self.event_type in COMMERCE_EVENT_TYPES, f"unknown event_type {self.event_type!r}")
        _timestamp(self.occurred_at)
        _identifier(self.channel_id, "channel_id")
        for value, name in (
            (self.order_id, "order_id"),
            (self.concept_id, "concept_id"),
            (self.derivative_id, "derivative_id"),
            (self.experiment_id, "experiment_id"),
        ):
            _optional_identifier(value, name)
        _require(self.event_type not in ORDER_EVENT_TYPES or self.order_id is not None, "order event needs order_id")
        _require(
            self.amount is None or (_finite(self.amount) and self.amount >= 0),
            "amount must be a finite non-negative number",
        )
        _require(self.event_type not in MONEY_EVENT_TYPES or self.amount is not None, "commission event needs amount")


def authorize_commerce_event(role: str, event: CommerceEvent) -> CommerceEvent:
    """Return the event if this role may leave that trace (§13 P0.17); canon roles are not listed here."""
    allowed = ROLE_EVENT_TYPES.get(role)
    if allowed is None:
        raise RevenueError(f"unknown commerce role {role!r}")
    if event.event_type not in allowed:
        raise RevenueError(f"role {role} may not emit {event.event_type}")
    return event


def _fold_order(events: Iterable[CommerceEvent]) -> tuple[str | None, dict[str, float]]:
    """Fold one order's events in time order; returns (state, latest amount per money event type)."""
    state: str | None = None
    amounts: dict[str, float] = {}
    for e in sorted(events, key=lambda e: _timestamp(e.occurred_at)):
        nxt = ORDER_TRANSITIONS[state].get(e.event_type)
        if nxt is None:
            raise RevenueError(f"order {e.order_id}: {e.event_type} not allowed in state {state}")
        if e.event_type in MONEY_EVENT_TYPES:
            amounts[e.event_type] = float(e.amount)  # type: ignore[arg-type]
        state = nxt
    return state, amounts


def order_state(events: Iterable[CommerceEvent]) -> str:
    """State of one order after its events (§13 P0.14); raises on any step outside the chain."""
    state, _ = _fold_order(events)
    _require(state is not None, "no OrderAttributed event")
    return state  # type: ignore[return-value]


def commerce_ledger(events: Iterable[CommerceEvent]) -> dict[str, Any]:
    """Per-order states plus three sums that are never added together (§5.15.7, §11.2).

    estimated: open orders' latest estimate (never a target input);
    finalized: contribution-margin base; paid: owner cash.
    """
    by_order: dict[str, list[CommerceEvent]] = {}
    for e in events:
        if e.event_type in ORDER_EVENT_TYPES:
            by_order.setdefault(e.order_id, []).append(e)  # type: ignore[arg-type]
    orders: dict[str, str] = {}
    totals = {"estimated": 0.0, "finalized": 0.0, "paid": 0.0}
    for order_id, order_events in by_order.items():
        state, amounts = _fold_order(order_events)
        orders[order_id] = state  # type: ignore[assignment]
        if state == "attributed":
            totals["estimated"] += amounts.get("CommissionEstimated", 0.0)
        if state in ("finalized", "paid"):
            totals["finalized"] += amounts.get("CommissionFinalized", 0.0)
        if state == "paid":
            totals["paid"] += amounts.get("CommissionPaid", 0.0)
    return {"orders": orders, **totals}


# --- integrity ratios (v3.2 §11.2); undefined -> None, never 0 ------------------


def _ratio(numerator: float, denominator: float) -> float | None:
    _require(_finite(numerator) and _finite(denominator), "ratio terms must be finite numbers")
    return None if denominator == 0 else numerator / denominator


def finalization_ratio(*, finalized: float, estimated: float) -> float | None:
    return _ratio(finalized, estimated)


def net_epc(*, finalized: float, direct_variable_cost: float, qualified_clicks: float) -> float | None:
    return _ratio(finalized - direct_variable_cost, qualified_clicks)


def margin_per_human_hour(*, contribution_margin: float, human_hours: float) -> float | None:
    return _ratio(contribution_margin, human_hours)


def survivorship_ratio(*, winners: int, attempts: int) -> float | None:
    _require(0 <= winners and winners <= attempts, "winners must be within [0, attempts]")
    return _ratio(winners, attempts)


# --- commerce lab promotion (v3.2 §5.15.5) ----------------------------------------


@dataclass(frozen=True)
class CommerceLabEvidence:
    """Inputs for the seven promotion conditions; the caller measures them."""

    original_ratio: float
    qa_passed_artifacts: int
    claims_sourced: bool
    public_pilot_days: int
    attribution_chain_complete: bool
    positive_margin_cohorts: int
    education_sales_separated: bool
    independent_brand: bool


def commerce_lab_promotion_gate(evidence: CommerceLabEvidence) -> GateDecision:
    """A commerce lab becomes an independent public channel only with all seven conditions met."""
    checks = (
        (evidence.original_ratio >= 1.0, "original or documented licensed UGC ratio below 100%"),
        (evidence.qa_passed_artifacts >= MIN_LAB_ARTIFACTS, f"fewer than {MIN_LAB_ARTIFACTS} QA-passed private artifacts"),
        (evidence.claims_sourced, "product claims lack source or as_of"),
        (evidence.public_pilot_days >= MIN_LAB_PILOT_DAYS, f"public pilot shorter than {MIN_LAB_PILOT_DAYS} days"),
        (evidence.attribution_chain_complete, "click -> order -> cancel/refund -> finalized chain incomplete"),
        (evidence.positive_margin_cohorts >= MIN_LAB_POSITIVE_COHORTS,
         f"fewer than {MIN_LAB_POSITIVE_COHORTS} consecutive cohorts with positive contribution margin"),
        (evidence.education_sales_separated, "course/community/lead sales not separated from the experiment ledger"),
        (evidence.independent_brand, "audience contract overlaps an existing channel"),
    )
    reasons = tuple(reason for ok, reason in checks if not ok)
    return GateDecision(COMMERCE_LAB_GATE_ID, not reasons, reasons)
