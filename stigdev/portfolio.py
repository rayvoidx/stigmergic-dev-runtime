"""Generic media portfolio, rights, and release contracts (ADR 0007).

Pure records and fail-closed gates; nothing here stores, schedules, or
publishes. ``now`` is caller-supplied ISO-8601. Real channel IDs, revenue,
masters, prompts, and scoring weights stay in private consumers; this module
ships with synthetic fixtures only.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Iterable, Sequence

from .workspace import valid_identifier

STAGES = ("hypothesis", "private_pilot", "public_pilot", "scale", "maintain", "pause", "retire")
# v3 §5.4 diagram plus the reversible `pause` row from v3.1 §4.2 (incident hold, never a verdict).
STAGE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "hypothesis": ("private_pilot",),
    "private_pilot": ("public_pilot",),
    "public_pilot": ("scale", "retire", "pause"),
    "scale": ("maintain", "pause"),
    "maintain": ("scale", "retire", "pause"),
    "pause": ("maintain",),
    "retire": (),
}
PUBLISHABLE_STAGES = ("public_pilot", "scale", "maintain")
PILOT_STAGES = ("hypothesis", "private_pilot", "public_pilot")
ROLES = ("cash_engine", "ip_engine", "product_funnel", "commerce_lab")
FORMATS = ("long", "short")
RIGHTS_BASES = ("original", "licensed", "public_domain", "unknown")
EXCLUSIVITIES = ("exclusive", "non_exclusive", "none")
DELIVERY_STATES = ("pending", "delivered")
SNAPSHOT_WINDOWS = ("1h", "6h", "24h", "3d", "7d", "28d", "90d")
HYPOTHESIS_STATES = ("open", "supported", "rejected", "inconclusive")
# v3.2 §11.2: one row per revenue item at its current status. claimed = someone else's number,
# estimated = platform screen, attributed = sales analysis only, finalized = contribution margin,
# paid = owner cash, influenced = side metric. Only finalized/paid ever reach gross.
REVENUE_KINDS = ("claimed", "estimated", "attributed", "finalized", "paid", "influenced")
GROSS_KINDS = ("finalized", "paid")
# v3.2 §13 P0.13: a bare view count is ambiguous since public counts start at the first frame
# (2026-08-24, taken at the UTC date boundary); metrics must say which count they carry.
VIEW_METRICS = ("raw_views", "engaged_views", "qualified_views")
VIEW_COUNT_POLICY_CHANGE = "2026-08-24T00:00:00+00:00"
VISIBILITIES = ("private", "unlisted", "public")
CONTENT_ID_RESULTS = ("pending", "clear", "claimed", "blocked")
REQUIRED_DERIVATIVES = ("official_visualizer",)
SHORT_REVIEW_MAX_MINUTES = 45.0
LONG_REVIEW_MAX_MINUTES = 240.0

RIGHTS_GATE_ID = "rights-gate/v1"
REGISTER_GATE_ID = "register-gate/v1"
RELEASE_GATE_ID = "release-gate/v1"
PUBLISH_GATE_ID = "publish-gate/v1"


class PortfolioError(ValueError):
    def __init__(self, message: str, reasons: tuple[str, ...] = ()):
        super().__init__(message)
        self.reasons = reasons


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PortfolioError(message)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _optional_identifier(value: object, name: str) -> None:
    _require(value is None or valid_identifier(value), f"invalid {name}")


def _timestamp(value: object) -> datetime:
    """Timestamps are stored timezone-aware (UTC); naive values cannot be compared safely."""
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise PortfolioError(f"invalid timestamp {value!r}") from exc
    _require(parsed.tzinfo is not None, f"timestamp {value!r} must be timezone-aware")
    return parsed


@dataclass(frozen=True)
class GateDecision:
    gate_id: str
    passed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PortfolioPolicy:
    """Portfolio-wide limits; numbers are data so a private instance overrides them."""

    max_scale: int
    max_active: int
    max_pilot: int
    max_review_hours_per_week: float

    def __post_init__(self) -> None:
        _require(isinstance(self.max_scale, int) and self.max_scale >= 1, "max_scale must be >= 1")
        _require(isinstance(self.max_active, int) and self.max_active >= self.max_scale, "max_active must be >= max_scale")
        _require(isinstance(self.max_pilot, int) and self.max_pilot >= 0, "max_pilot must be >= 0")
        _require(
            _finite(self.max_review_hours_per_week) and self.max_review_hours_per_week > 0,
            "max_review_hours_per_week must be positive",
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "PortfolioPolicy":
        return PortfolioPolicy(**raw)


# Defaults from the operator capacity analysis of 2026-09-27: 2 scale winners,
# 12 active channels max, 2-4 pilots, 15 review hours/week before expanding.
DEFAULT_POLICY = PortfolioPolicy(max_scale=2, max_active=12, max_pilot=4, max_review_hours_per_week=15.0)
MAX_SCALE_CHANNELS = DEFAULT_POLICY.max_scale


@dataclass(frozen=True)
class PortfolioEvidence:
    """Portfolio-level measurements a private instance supplies before adding a channel."""

    review_hours_per_week: float
    policy_incidents: int

    def __post_init__(self) -> None:
        _require(_finite(self.review_hours_per_week) and self.review_hours_per_week >= 0, "review_hours_per_week must be >= 0")
        _require(isinstance(self.policy_incidents, int) and self.policy_incidents >= 0, "policy_incidents must be >= 0")


@dataclass(frozen=True)
class ChannelPlan:
    channel_id: str
    business_role: str
    stage: str
    audience_contract: str
    weekly_publish_cap: dict[str, int]
    owned_ip_ratio_min: float = 0.9
    human_review_required: bool = True
    kill_gate_ref: str | None = None
    # v3.1 §5.6: weekly minimum per format that keeps a mandatory channel alive.
    existence_floor: dict[str, int] = field(default_factory=dict)
    # v3.1 §13 P0.4: hours from TrendDetected within which a derivative must publish.
    time_sensitivity_hours: float | None = None
    # v3.2 §13 P0.17: a commerce lab runs under its own config, but its linked owner is on record.
    owner_ref: str | None = None

    def __post_init__(self) -> None:
        _require(valid_identifier(self.channel_id), "invalid channel_id")
        _require(self.business_role in ROLES, f"unknown business_role {self.business_role!r}")
        _optional_identifier(self.owner_ref, "owner_ref")
        _require(self.business_role != "commerce_lab" or bool(self.owner_ref), "commerce_lab requires owner_ref")
        _require(self.stage in STAGES, f"unknown stage {self.stage!r}")
        _require(
            all(k in FORMATS and isinstance(v, int) and v >= 0 for k, v in self.weekly_publish_cap.items()),
            "weekly_publish_cap must map long/short to non-negative ints",
        )
        _require(_finite(self.owned_ip_ratio_min) and 0 <= self.owned_ip_ratio_min <= 1, "owned_ip_ratio_min out of range")
        _require(
            all(
                k in FORMATS and isinstance(v, int) and 0 <= v <= self.weekly_publish_cap.get(k, 0)
                for k, v in self.existence_floor.items()
            ),
            "existence_floor must map long/short to ints within weekly_publish_cap",
        )
        _require(
            self.time_sensitivity_hours is None or (_finite(self.time_sensitivity_hours) and self.time_sensitivity_hours > 0),
            "time_sensitivity_hours must be a positive number",
        )

    @property
    def mandatory(self) -> bool:
        return any(v > 0 for v in self.existence_floor.values())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "ChannelPlan":
        return ChannelPlan(**raw)


@dataclass(frozen=True)
class RightsManifest:
    artifact_id: str
    owner: str
    rights_basis: str
    commercial_use: bool
    exclusivity: str
    origin_url: str | None = None
    contributors: tuple[str, ...] = ()
    license_receipt_hash: str | None = None
    expires_at: str | None = None
    content_id_eligible: bool = False
    concept_id: str | None = None

    def __post_init__(self) -> None:
        _require(valid_identifier(self.artifact_id), "invalid artifact_id")
        _optional_identifier(self.concept_id, "concept_id")
        _require(self.rights_basis in RIGHTS_BASES, f"unknown rights_basis {self.rights_basis!r}")
        _require(self.exclusivity in EXCLUSIVITIES, f"unknown exclusivity {self.exclusivity!r}")
        if self.expires_at is not None:
            _timestamp(self.expires_at)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "RightsManifest":
        data = dict(raw)
        data["contributors"] = tuple(data.get("contributors", ()))
        return RightsManifest(**data)


@dataclass(frozen=True)
class ReleaseUnit:
    release_id: str
    master_artifact_id: str
    stems: tuple[str, ...] = ()
    splits: tuple[tuple[str, float], ...] = ()
    isrc: str | None = None
    distributor_delivery: str = "pending"
    derivatives: tuple[str, ...] = ()
    concept_id: str | None = None

    def __post_init__(self) -> None:
        _require(valid_identifier(self.release_id), "invalid release_id")
        _optional_identifier(self.concept_id, "concept_id")
        _require(valid_identifier(self.master_artifact_id), "invalid master_artifact_id")
        _require(self.distributor_delivery in DELIVERY_STATES, f"unknown distributor_delivery {self.distributor_delivery!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "ReleaseUnit":
        data = dict(raw)
        data["stems"] = tuple(data.get("stems", ()))
        data["derivatives"] = tuple(data.get("derivatives", ()))
        data["splits"] = tuple((str(name), float(share)) for name, share in data.get("splits", ()))
        return ReleaseUnit(**data)


@dataclass(frozen=True)
class ProfitSnapshot:
    """Missing metrics are omitted, never written as 0 (Blueprint §14.1)."""

    channel_id: str
    captured_at: str
    window: str
    metrics: dict[str, float]
    revenue: dict[str, float]
    concept_id: str | None = None

    def __post_init__(self) -> None:
        _require(valid_identifier(self.channel_id), "invalid channel_id")
        _optional_identifier(self.concept_id, "concept_id")
        _timestamp(self.captured_at)
        _require(self.window in SNAPSHOT_WINDOWS, f"unknown window {self.window!r}")
        _require(all(_finite(v) for v in self.metrics.values()), "metrics must be finite numbers")
        _require(
            all(k in VIEW_METRICS for k in self.metrics if "view" in k),
            "view metrics must be one of raw_views/engaged_views/qualified_views",
        )
        _require(
            all(k in REVENUE_KINDS and _finite(v) for k, v in self.revenue.items()),
            f"revenue keys must be one of {'/'.join(REVENUE_KINDS)}",
        )

    @property
    def view_policy_era(self) -> str:
        return view_policy_era(self.captured_at)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "ProfitSnapshot":
        return ProfitSnapshot(**raw)


@dataclass(frozen=True)
class FormatHypothesis:
    hypothesis_id: str
    channel_id: str
    variable: str
    primary_metric: str
    cohort_size: int
    started_at: str
    ended_at: str | None = None
    status: str = "open"
    concept_id: str | None = None

    def __post_init__(self) -> None:
        _require(valid_identifier(self.hypothesis_id), "invalid hypothesis_id")
        _require(valid_identifier(self.channel_id), "invalid channel_id")
        _optional_identifier(self.concept_id, "concept_id")
        _require(isinstance(self.cohort_size, int) and self.cohort_size >= 0, "cohort_size must be a non-negative int")
        _timestamp(self.started_at)
        if self.ended_at is not None:
            _timestamp(self.ended_at)
        _require(self.status in HYPOTHESIS_STATES, f"unknown status {self.status!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "FormatHypothesis":
        return FormatHypothesis(**raw)


@dataclass(frozen=True)
class RevenueEvent:
    channel_id: str
    kind: str
    amount: float
    occurred_at: str
    source: str
    currency: str = "KRW"
    concept_id: str | None = None

    def __post_init__(self) -> None:
        _require(valid_identifier(self.channel_id), "invalid channel_id")
        _optional_identifier(self.concept_id, "concept_id")
        _require(self.kind in REVENUE_KINDS, f"unknown revenue kind {self.kind!r}")
        _require(_finite(self.amount) and self.amount >= 0, "amount must be a finite non-negative number")
        _timestamp(self.occurred_at)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "RevenueEvent":
        return RevenueEvent(**raw)


@dataclass(frozen=True)
class ScaleEvidence:
    """Inputs for the seven v3 §5.4 scale conditions; the caller measures them."""

    weeks_public: int
    public_artifacts: int
    recent_median_improved: bool
    strikes: int
    repeated_content_id_claims: int
    short_review_minutes: float
    long_review_minutes: float
    revenue_attributable: bool
    shadow_double_volume_passed: bool
    approved_by: str | None = None


@dataclass(frozen=True)
class PublishCandidate:
    content_id: str
    channel_id: str
    format: str
    payload_hash: str
    approved_payload_hash: str | None
    upload_visibility: str
    content_id_result: str
    ai_disclosure: bool | None
    rights: tuple[RightsManifest, ...] = field(default=())

    def __post_init__(self) -> None:
        _require(valid_identifier(self.content_id), "invalid content_id")
        _require(valid_identifier(self.channel_id), "invalid channel_id")
        _require(self.format in FORMATS, f"unknown format {self.format!r}")
        _require(self.upload_visibility in VISIBILITIES, f"unknown upload_visibility {self.upload_visibility!r}")
        _require(self.content_id_result in CONTENT_ID_RESULTS, f"unknown content_id_result {self.content_id_result!r}")


# --- gates -------------------------------------------------------------------


def _rights_reasons(manifests: Iterable[RightsManifest], now: str) -> tuple[str, ...]:
    current = _timestamp(now)
    reasons: list[str] = []
    seen = False
    for m in manifests:
        seen = True
        if m.rights_basis == "unknown":
            reasons.append(f"{m.artifact_id}: rights_basis unknown")
        if not m.commercial_use:
            reasons.append(f"{m.artifact_id}: commercial use not granted")
        if not m.owner.strip():
            reasons.append(f"{m.artifact_id}: owner missing")
        if m.rights_basis == "licensed" and not m.license_receipt_hash:
            reasons.append(f"{m.artifact_id}: licensed without license receipt")
        if m.expires_at is not None and _timestamp(m.expires_at) <= current:
            reasons.append(f"{m.artifact_id}: rights expired at {m.expires_at}")
        if m.content_id_eligible and not (m.rights_basis == "original" and m.exclusivity == "exclusive"):
            reasons.append(f"{m.artifact_id}: content_id_eligible requires exclusive original rights")
    if not seen:
        reasons.append("no rights manifest")
    return tuple(reasons)


def rights_gate(manifests: Iterable[RightsManifest], now: str) -> GateDecision:
    """Fail closed unless every asset has commercial, unexpired, documented rights (v3 §5.5, §6.6)."""
    reasons = _rights_reasons(manifests, now)
    return GateDecision(RIGHTS_GATE_ID, not reasons, reasons)


def release_gate(unit: ReleaseUnit, master_rights: RightsManifest, now: str) -> GateDecision:
    """One master may become a release only with rights, ISRC, settled splits, and a visualizer (v3 §6.4)."""
    reasons = list(_rights_reasons([master_rights], now))
    if master_rights.artifact_id != unit.master_artifact_id:
        reasons.append(f"rights manifest does not cover master {unit.master_artifact_id}")
    if not unit.isrc:
        reasons.append("isrc pending")
    if unit.splits and not math.isclose(sum(share for _, share in unit.splits), 1.0, abs_tol=1e-9):
        reasons.append("splits do not sum to 1")
    for derivative in REQUIRED_DERIVATIVES:
        if derivative not in unit.derivatives:
            reasons.append(f"missing derivative {derivative}")
    return GateDecision(RELEASE_GATE_ID, not reasons, tuple(reasons))


def _cap_reached(plan: ChannelPlan, fmt: str, published_this_week: dict[str, int]) -> bool:
    _require(fmt in FORMATS, f"unknown format {fmt!r}")
    return published_this_week.get(fmt, 0) >= plan.weekly_publish_cap.get(fmt, 0)


def can_publish(plan: ChannelPlan, fmt: str, published_this_week: dict[str, int]) -> bool:
    """Weekly per-format cap on a channel in a publicly publishable stage (v3 §13 P0.4)."""
    return plan.stage in PUBLISHABLE_STAGES and not _cap_reached(plan, fmt, published_this_week)


def floor_deficit(plan: ChannelPlan, published_this_week: dict[str, int]) -> dict[str, int]:
    """Per-format shortfall against the existence floor; the scheduler protects exactly this (v3.1 §10.3)."""
    return {fmt: max(0, floor - published_this_week.get(fmt, 0)) for fmt, floor in plan.existence_floor.items()}


def sla_breached(plan: ChannelPlan, detected_at: str, now: str) -> bool:
    """True when a time-sensitive channel has not published within its window since detection."""
    if plan.time_sensitivity_hours is None:
        return False
    return _timestamp(now) - _timestamp(detected_at) > timedelta(hours=plan.time_sensitivity_hours)


def publish_gate(
    candidate: PublishCandidate,
    plan: ChannelPlan,
    published_this_week: dict[str, int],
    now: str,
) -> GateDecision:
    """Pre-publish check: private upload, Content ID clear, disclosure set, approved hash, rights (v3 §13 P0.6)."""
    reasons: list[str] = []
    if candidate.channel_id != plan.channel_id:
        reasons.append(f"candidate channel {candidate.channel_id} does not match {plan.channel_id}")
    if plan.stage not in PUBLISHABLE_STAGES:
        reasons.append(f"channel stage {plan.stage} cannot publish publicly")
    if _cap_reached(plan, candidate.format, published_this_week):
        reasons.append(f"weekly cap reached for {candidate.format}")
    if candidate.upload_visibility != "private":
        reasons.append("upload must be private before public approval")
    if candidate.content_id_result != "clear":
        reasons.append(f"content id result {candidate.content_id_result}")
    if candidate.ai_disclosure is None:
        reasons.append("ai disclosure undecided")
    if candidate.approved_payload_hash != candidate.payload_hash:
        reasons.append("approved payload hash mismatch")
    reasons.extend(_rights_reasons(candidate.rights, now))
    return GateDecision(PUBLISH_GATE_ID, not reasons, tuple(reasons))


# --- portfolio controller ----------------------------------------------------


def _scale_reasons(evidence: ScaleEvidence) -> tuple[str, ...]:
    checks = (
        (evidence.weeks_public >= 8 or evidence.public_artifacts >= 30,
         "fewer than 8 public weeks and fewer than 30 public artifacts"),
        (evidence.recent_median_improved, "recent median did not improve"),
        (evidence.strikes == 0, "strikes present"),
        (evidence.repeated_content_id_claims == 0, "repeated content id claims present"),
        (evidence.short_review_minutes <= SHORT_REVIEW_MAX_MINUTES, "short review over 45 minutes"),
        (evidence.long_review_minutes <= LONG_REVIEW_MAX_MINUTES, "long review over 240 minutes"),
        (evidence.revenue_attributable, "revenue not attributable per channel"),
        (evidence.shadow_double_volume_passed, "double-volume shadow test not passed"),
        (bool(evidence.approved_by), "operator approval missing"),
    )
    return tuple(reason for ok, reason in checks if not ok)


def register_channel(
    plan: ChannelPlan,
    portfolio: Sequence[ChannelPlan],
    evidence: PortfolioEvidence,
    policy: PortfolioPolicy = DEFAULT_POLICY,
) -> GateDecision:
    """Adding a channel never fixes a failing format: caps on active/pilot counts, review time, incidents."""
    reasons: list[str] = []
    if any(p.channel_id == plan.channel_id for p in portfolio):
        reasons.append(f"channel_id {plan.channel_id} already registered")
    active = [p for p in portfolio if p.stage != "retire"]
    if len(active) >= policy.max_active:
        reasons.append(f"active channel limit {policy.max_active} reached")
    pilots = [p for p in active if p.stage in PILOT_STAGES]
    if len(pilots) >= policy.max_pilot:
        reasons.append(f"pilot channel limit {policy.max_pilot} reached")
    if evidence.review_hours_per_week > policy.max_review_hours_per_week:
        reasons.append(
            f"review hours {evidence.review_hours_per_week:.1f} over weekly cap {policy.max_review_hours_per_week:.1f}"
        )
    if evidence.policy_incidents > 0:
        reasons.append("policy incidents present")
    return GateDecision(REGISTER_GATE_ID, not reasons, tuple(reasons))


def advance_stage(
    plan: ChannelPlan,
    to: str,
    portfolio: Sequence[ChannelPlan],
    evidence: ScaleEvidence | None = None,
    policy: PortfolioPolicy = DEFAULT_POLICY,
) -> ChannelPlan:
    """Move along the v3 §5.4 state diagram; `scale` needs evidence and a free scale slot."""
    if to not in STAGE_TRANSITIONS.get(plan.stage, ()):
        raise PortfolioError(f"invalid transition {plan.stage} -> {to}")
    if to == "retire" and plan.mandatory:
        raise PortfolioError("mandatory channel cannot retire; lower to maintain or pause instead")
    if to == "scale":
        if evidence is None:
            raise PortfolioError("scale evidence required")
        reasons = _scale_reasons(evidence)
        if reasons:
            raise PortfolioError("scale conditions unmet: " + "; ".join(reasons), reasons)
        others = [p for p in portfolio if p.stage == "scale" and p.channel_id != plan.channel_id]
        if len(others) >= policy.max_scale:
            raise PortfolioError(f"scale limit: {policy.max_scale} channels already in scale")
    return replace(plan, stage=to)


# --- revenue ledger ----------------------------------------------------------


def revenue_by_kind(events: Iterable[RevenueEvent]) -> dict[str, float]:
    """Totals per kind; kinds are never summed together here (v3 §13 P0.5)."""
    totals = {kind: 0.0 for kind in REVENUE_KINDS}
    for event in events:
        totals[event.kind] += event.amount
    return totals


def gross_revenue(events: Iterable[RevenueEvent], kinds: tuple[str, ...] = GROSS_KINDS) -> float:
    """Gross counts only settled money (v3.2 §11.2); claims, estimates, attribution, influence never qualify."""
    _require(all(k in GROSS_KINDS for k in kinds), "gross revenue may include only finalized/paid kinds")
    totals = revenue_by_kind(events)
    return sum(totals[k] for k in kinds)


def cash_revenue(events: Iterable[RevenueEvent]) -> float:
    """Owner cash: only money that reached an account (v3.2 §5.15.7)."""
    return revenue_by_kind(events)["paid"]


def view_policy_era(at: str) -> str:
    """Cohort label so pre- and post-first-frame view counts are never pooled (v3.2 §13 P0.13)."""
    return "pre_2026_08_24" if _timestamp(at) < _timestamp(VIEW_COUNT_POLICY_CHANGE) else "first_frame_2026_08_24"


def contribution_margin(events: Iterable[RevenueEvent], direct_costs: float) -> float:
    """Gross minus direct costs (v3 §7.1); taxes and shared overhead are the caller's layer."""
    _require(_finite(direct_costs) and direct_costs >= 0, "direct_costs must be a finite non-negative number")
    return gross_revenue(events) - direct_costs
