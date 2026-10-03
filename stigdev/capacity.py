"""Monthly capacity envelope and revenue sensitivity (ADR 0013).

ADR 0012 decides whether one job may start right now. This module answers the
month-scale question the portfolio gates currently take on faith: does a
planned publish cadence fit the GPU hours, the reviewer's hours, and the disk?

Two rules keep it honest. Reviewer hours are a first-class resource, because
on this hardware they run out before the GPU does. And a revenue projection is
emitted as ``estimated`` revenue events, which :func:`stigdev.portfolio.gross_revenue`
already refuses to count, so a sensitivity calculation can never be mistaken
for money.

Pure policy: nothing here measures a host, reads a file, or calls a platform.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable

from .node import NodeProfile
from .portfolio import FORMATS, GateDecision, RevenueEvent
from .revenue import PolicySnapshot
from .workspace import valid_identifier

CAPACITY_GATE_ID = "capacity-gate/v1"
HOURS_PER_MONTH = 24 * 30
DAYS_PER_MONTH = 30
DAYS_PER_WEEK = 7
# Platform-side splits, recorded so a reader does not have to look them up.
# RPM figures are already creator-side, so these are never multiplied in.
WATCH_PAGE_SHARE = 0.55
SHORTS_POOL_SHARE = 0.45
SHORTS_FLOOR_METRIC = "qualified_shorts_views_90d"
FLOOR_WINDOW_DAYS = 90


class CapacityError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CapacityError(message)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _non_negative(value: object, name: str) -> float:
    _require(_finite(value) and float(value) >= 0, f"{name} must be a finite non-negative number")
    return float(value)


def _positive(value: object, name: str) -> float:
    _require(_finite(value) and float(value) > 0, f"{name} must be a finite positive number")
    return float(value)


def _timestamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise CapacityError(f"invalid timestamp {value!r}") from exc
    _require(parsed.tzinfo is not None, f"timestamp {value!r} must be timezone-aware")
    return parsed


@dataclass(frozen=True)
class ArtifactCost:
    """What one finished artifact costs. `working_gb` is freed by retention; `archive_gb` is kept forever."""

    gpu_hours: float
    review_hours: float
    working_gb: float
    archive_gb: float

    def __post_init__(self) -> None:
        for name in ("gpu_hours", "review_hours", "working_gb", "archive_gb"):
            _non_negative(getattr(self, name), name)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "ArtifactCost":
        return ArtifactCost(**raw)


# Planning assumptions from the 2026-09 capacity analysis, not measurements.
# Replace each entry the first time a real render is profiled (same rule as
# the resource classes in ADR 0012).
PLANNING_COSTS: dict[str, ArtifactCost] = {
    "short": ArtifactCost(gpu_hours=1.2, review_hours=0.25, working_gb=3.0, archive_gb=0.5),
    "long": ArtifactCost(gpu_hours=12.0, review_hours=2.5, working_gb=25.0, archive_gb=4.0),
}


@dataclass(frozen=True)
class ChannelDemand:
    """One channel's planned monthly output, per format."""

    channel_id: str
    monthly: dict[str, int]

    def __post_init__(self) -> None:
        _require(valid_identifier(self.channel_id), "invalid channel_id")
        _require(
            all(
                fmt in FORMATS and isinstance(count, int) and not isinstance(count, bool) and count >= 0
                for fmt, count in self.monthly.items()
            ),
            f"monthly must map {'/'.join(FORMATS)} to non-negative ints",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "ChannelDemand":
        return ChannelDemand(**raw)


@dataclass(frozen=True)
class CapacityBudget:
    """One month of headroom on one node, with one operator behind it."""

    node_id: str
    gpu_hours: float
    review_hours: float
    memory_ceiling_gb: float
    working_gb: float
    archive_headroom_gb: float
    retention_days: int

    def __post_init__(self) -> None:
        _require(bool(self.node_id.strip()), "node_id must be a non-empty string")
        _positive(self.gpu_hours, "gpu_hours")
        _positive(self.review_hours, "review_hours")
        _positive(self.memory_ceiling_gb, "memory_ceiling_gb")
        _non_negative(self.working_gb, "working_gb")
        _non_negative(self.archive_headroom_gb, "archive_headroom_gb")
        _require(
            isinstance(self.retention_days, int) and not isinstance(self.retention_days, bool)
            and 1 <= self.retention_days <= DAYS_PER_MONTH,
            f"retention_days must be an int within 1..{DAYS_PER_MONTH}",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "CapacityBudget":
        return CapacityBudget(**raw)


def budget_from(
    *,
    profile: NodeProfile,
    utilization: float,
    operator_review_hours_per_week: float,
    disk_gb: float,
    retention_days: int,
    working_share: float = 0.5,
) -> CapacityBudget:
    """Derive a month of headroom from a node profile and the operator's own week.

    ``utilization`` is the share of wall-clock the media work may take. Memory
    takes the tighter of the node's reserve (ADR 0012) and that share, because
    the two ceilings disagree and planning on the smaller one fails closed.
    """
    _require(_finite(utilization) and 0 < utilization <= 1, "utilization must be within (0, 1]")
    _positive(operator_review_hours_per_week, "operator_review_hours_per_week")
    _non_negative(disk_gb, "disk_gb")
    _require(_finite(working_share) and 0 < working_share < 1, "working_share must be within (0, 1)")
    return CapacityBudget(
        node_id=profile.node_id,
        gpu_hours=HOURS_PER_MONTH * utilization,
        review_hours=operator_review_hours_per_week * DAYS_PER_MONTH / DAYS_PER_WEEK,
        memory_ceiling_gb=min(profile.usable_memory_gb, profile.total_memory_gb * utilization),
        working_gb=disk_gb * working_share,
        archive_headroom_gb=disk_gb * (1 - working_share),
        retention_days=retention_days,
    )


def artifact_counts(demands: Iterable[ChannelDemand]) -> dict[str, int]:
    """Monthly artifacts per format across the whole portfolio."""
    totals = {fmt: 0 for fmt in FORMATS}
    for demand in demands:
        for fmt, count in demand.monthly.items():
            totals[fmt] += count
    return totals


def _demanded(
    demands: Iterable[ChannelDemand],
    costs: dict[str, ArtifactCost],
) -> tuple[dict[str, int], dict[str, float]]:
    counts = artifact_counts(demands)
    missing = [fmt for fmt, count in counts.items() if count and fmt not in costs]
    _require(not missing, f"no artifact cost for {', '.join(sorted(missing))}")
    used = {"gpu_hours": 0.0, "review_hours": 0.0, "working_gb": 0.0, "archive_gb": 0.0}
    for fmt, count in counts.items():
        if not count:
            continue
        cost = costs[fmt]
        used["gpu_hours"] += cost.gpu_hours * count
        used["review_hours"] += cost.review_hours * count
        used["working_gb"] += cost.working_gb * count
        used["archive_gb"] += cost.archive_gb * count
    return counts, used


def review_hours_per_week(
    demands: Iterable[ChannelDemand],
    costs: dict[str, ArtifactCost] = PLANNING_COSTS,
) -> float:
    """Reviewer hours a plan actually demands, for `portfolio.PortfolioEvidence`."""
    _, used = _demanded(demands, costs)
    return used["review_hours"] * DAYS_PER_WEEK / DAYS_PER_MONTH


def capacity_report(
    demands: Iterable[ChannelDemand],
    budget: CapacityBudget,
    costs: dict[str, ArtifactCost] = PLANNING_COSTS,
) -> dict[str, Any]:
    """Used, available, and deficit per resource. The working set is what survives retention."""
    counts, used = _demanded(demands, costs)
    retained = used["working_gb"] * budget.retention_days / DAYS_PER_MONTH
    rows = {
        "gpu_hours": (used["gpu_hours"], budget.gpu_hours),
        "review_hours": (used["review_hours"], budget.review_hours),
        "working_gb": (retained, budget.working_gb),
    }
    report: dict[str, Any] = {
        "node_id": budget.node_id,
        "artifacts": counts,
        "archive_growth_gb_per_month": used["archive_gb"],
    }
    for name, (spent, available) in rows.items():
        report[name] = {
            "used": spent,
            "available": available,
            "deficit": max(0.0, spent - available),
        }
    return report


def capacity_gate(
    demands: Iterable[ChannelDemand],
    budget: CapacityBudget,
    costs: dict[str, ArtifactCost] = PLANNING_COSTS,
) -> GateDecision:
    """Fail closed on every exhausted resource at once; this is what `capacity_available` means."""
    report = capacity_report(demands, budget, costs)
    reasons = tuple(
        f"{name} short by {report[name]['deficit']:.1f} "
        f"({report[name]['used']:.1f} needed, {report[name]['available']:.1f} available)"
        for name in ("gpu_hours", "review_hours", "working_gb")
        if report[name]["deficit"] > 0
    )
    return GateDecision(CAPACITY_GATE_ID, not reasons, reasons)


def capacity_available(
    demands: Iterable[ChannelDemand],
    budget: CapacityBudget,
    costs: dict[str, ArtifactCost] = PLANNING_COSTS,
) -> bool:
    """The bool `lifecycle.ScaleEvidence` asks for, derived from a plan instead of asserted.

    Every other field on that record is caller-measured, so this stays a
    function rather than a change to the record: a control plane computes it
    here and hands the answer over, and the reasons stay readable through
    :func:`capacity_gate`.
    """
    return capacity_gate(demands, budget, costs).passed


def months_until_archive_full(
    demands: Iterable[ChannelDemand],
    budget: CapacityBudget,
    costs: dict[str, ArtifactCost] = PLANNING_COSTS,
) -> float | None:
    """When originals fill the disk at this cadence; `None` when nothing is being archived."""
    report = capacity_report(demands, budget, costs)
    growth = report["archive_growth_gb_per_month"]
    return None if growth == 0 else budget.archive_headroom_gb / growth


def shorts_pool_floor(
    projected_qualified_views_90d: dict[str, float],
    snapshot: PolicySnapshot,
    at: str,
) -> dict[str, Any]:
    """Which channels fall under the Shorts pool retention floor, and what the portfolio needs in total.

    Missing the floor stops Shorts pool payments for that channel. It does not
    remove the channel from the programme and does not touch long-form revenue.
    """
    _require(snapshot.feature == "shorts_pool", f"expected a shorts_pool policy, got {snapshot.feature!r}")
    threshold = snapshot.thresholds.get(SHORTS_FLOOR_METRIC)
    _require(threshold is not None, f"policy {snapshot.policy_id} has no {SHORTS_FLOOR_METRIC} threshold")
    for channel_id, views in projected_qualified_views_90d.items():
        _require(valid_identifier(channel_id), f"invalid channel_id {channel_id!r}")
        _non_negative(views, f"projected views for {channel_id}")
    in_effect = _timestamp(at) >= _timestamp(snapshot.effective_from)
    below = (
        sorted(c for c, views in projected_qualified_views_90d.items() if views < threshold) if in_effect else []
    )
    channels = len(projected_qualified_views_90d)
    return {
        "in_effect": in_effect,
        "threshold_per_channel_90d": float(threshold),
        "below_floor": below,
        "monthly_views_required": channels * float(threshold) * DAYS_PER_MONTH / FLOOR_WINDOW_DAYS,
        "long_form_revenue_at_risk": False,
    }


def project_revenue(
    *,
    channel_id: str,
    views: dict[str, float],
    rpm_usd: dict[str, float],
    usd_krw: float,
    occurred_at: str,
    source: str = "rpm_sensitivity",
) -> tuple[RevenueEvent, ...]:
    """A sensitivity calculation, emitted as `estimated` rows so it can never be counted as money.

    ``rpm_usd`` is revenue per 1,000 views on the creator's side of the split,
    so :data:`WATCH_PAGE_SHARE` and :data:`SHORTS_POOL_SHARE` are documentation
    here and must not be applied again.
    """
    _positive(usd_krw, "usd_krw")
    missing = sorted(fmt for fmt in views if fmt not in rpm_usd)
    _require(not missing, f"no rpm assumption for {', '.join(missing)}")
    events = []
    for fmt in sorted(views):
        _non_negative(views[fmt], f"views for {fmt}")
        _non_negative(rpm_usd[fmt], f"rpm for {fmt}")
        amount = views[fmt] / 1000 * rpm_usd[fmt] * usd_krw
        events.append(
            RevenueEvent(
                channel_id=channel_id,
                kind="estimated",
                amount=amount,
                occurred_at=occurred_at,
                source=f"{source}:{fmt}",
            )
        )
    return tuple(events)
