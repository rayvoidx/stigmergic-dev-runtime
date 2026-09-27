"""Concept lineage, ecosystem events, and the Truth Firewall (ADR 0008).

Pure records and functions for the v3.1 organic loop: one ``concept_id`` ties
canon versions, platform derivatives, audience signals, and adaptation
decisions together. Attention, utility, economic, and risk signals may change
packaging, cadence, CTA, budget, or review level; they can never write canon.
Canon changes only via EvidenceUpdated -> CanonReview -> CanonApproved.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Any, Iterable, Sequence

from .workspace import valid_identifier

EVENT_TYPES = (
    "TrendDetected",
    "EvidenceUpdated",
    "BenchmarkCompleted",
    "CanonReview",
    "CanonApproved",
    "DerivativeRendered",
    "PublicationApproved",
    "VideoWatched",
    "QuestionAsked",
    "TopicSaved",
    "ToolExecuted",
    "AppRetentionObserved",
    "RevenueAttributed",
    "CorrectionIssued",
    "RightsRiskRaised",
    "AdaptationDecided",
)
CANON_WRITE_PATH = ("EvidenceUpdated", "CanonReview", "CanonApproved")
# Which logical role may leave which trace. Attention/revenue roles never touch canon.
ROLE_EVENT_TYPES: dict[str, tuple[str, ...]] = {
    "sensor": ("TrendDetected", "BenchmarkCompleted", "RightsRiskRaised"),
    "evidence": ("EvidenceUpdated", "BenchmarkCompleted", "CorrectionIssued", "RightsRiskRaised"),
    "canon_reviewer": ("CanonReview", "CanonApproved", "CorrectionIssued"),
    "format_adapter": ("DerivativeRendered",),
    "publisher": ("PublicationApproved",),
    "analytics": (
        "VideoWatched",
        "QuestionAsked",
        "TopicSaved",
        "ToolExecuted",
        "AppRetentionObserved",
        "RevenueAttributed",
    ),
    "controller": ("AdaptationDecided",),
}
PLATFORMS = ("youtube", "web", "app", "sns", "product", "music")
LOOP_SURFACES = ("youtube", "web", "app")  # v3.1 §11.3: a concept closes the loop only across these three
DERIVATIVE_KINDS = (
    "signal_short",
    "signal_explainer",
    "weekly_brief",
    "canon_report",
    "watchlist_alert",
    "archive_episode",
    "archive_short",
    "compilation",
    "official_visualizer",
    "lyric_video",
    "hook_short",
    "production_note",
    "session_mix",
    "card",
    "thread",
    "clip",
    "report",
    "brief",
)
SIGNAL_GROUPS = ("epistemic", "attention", "utility", "economic", "risk")
ADAPTATION_TARGETS = ("packaging", "cta", "cadence", "budget", "review_level", "source_block")
LOOPS = ("fast", "slow")
DECISION_STATES = ("proposed", "approved", "rejected")
PRIVACY_CLASSES = ("public", "aggregate", "private")
_TTL = re.compile(r"P(?:\d+W|\d+D|T\d+H|T\d+M)")


class EcosystemError(ValueError):
    def __init__(self, message: str, reasons: tuple[str, ...] = ()):
        super().__init__(message)
        self.reasons = reasons


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EcosystemError(message)


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
        raise EcosystemError(f"invalid timestamp {value!r}") from exc
    _require(parsed.tzinfo is not None, f"timestamp {value!r} must be timezone-aware")
    return parsed


class _Record:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[call-overload]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]):
        data = dict(raw)
        for key in ("source_ids",):
            if key in data:
                data[key] = tuple(data[key])
        return cls(**data)


@dataclass(frozen=True)
class Concept(_Record):
    concept_id: str
    title: str
    created_at: str

    def __post_init__(self) -> None:
        _identifier(self.concept_id, "concept_id")
        _timestamp(self.created_at)


@dataclass(frozen=True)
class EvidenceBundle(_Record):
    bundle_id: str
    concept_id: str
    source_ids: tuple[str, ...]
    captured_at: str
    expires_at: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.bundle_id, "bundle_id")
        _identifier(self.concept_id, "concept_id")
        _require(all(valid_identifier(s) for s in self.source_ids), "invalid source_ids")
        _timestamp(self.captured_at)
        if self.expires_at is not None:
            _timestamp(self.expires_at)


@dataclass(frozen=True)
class CanonArtifact(_Record):
    canon_id: str
    concept_id: str
    version: int
    artifact_hash: str
    evidence_bundle_id: str
    approved_by: str
    approved_at: str
    supersedes: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.canon_id, "canon_id")
        _identifier(self.concept_id, "concept_id")
        _require(isinstance(self.version, int) and self.version >= 1, "version must be a positive int")
        _identifier(self.artifact_hash, "artifact_hash")
        _identifier(self.evidence_bundle_id, "evidence_bundle_id")
        _optional_identifier(self.supersedes, "supersedes")
        _timestamp(self.approved_at)


@dataclass(frozen=True)
class PlatformDerivative(_Record):
    """One surface-specific expression of a canon version; one direct CTA at most (v3.1 §8.3)."""

    derivative_id: str
    concept_id: str
    canon_id: str
    canon_version: int
    platform: str
    kind: str
    cta_target: str | None = None
    channel_id: str | None = None
    published_at: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.derivative_id, "derivative_id")
        _identifier(self.concept_id, "concept_id")
        _identifier(self.canon_id, "canon_id")
        _require(isinstance(self.canon_version, int) and self.canon_version >= 1, "canon_version must be a positive int")
        _require(self.platform in PLATFORMS, f"unknown platform {self.platform!r}")
        _require(self.kind in DERIVATIVE_KINDS, f"unknown derivative kind {self.kind!r}")
        _optional_identifier(self.cta_target, "cta_target")
        _optional_identifier(self.channel_id, "channel_id")
        if self.published_at is not None:
            _timestamp(self.published_at)


@dataclass(frozen=True)
class EcosystemEvent(_Record):
    """v3.1 §5.3 envelope. An observation, never a command."""

    event_id: str
    event_type: str
    occurred_at: str
    concept_id: str
    canon_artifact_id: str | None = None
    derivative_id: str | None = None
    platform: str | None = None
    audience_segment: str | None = None
    experiment_id: str | None = None
    payload_ref: str | None = None
    confidence: float | None = None
    privacy_class: str = "aggregate"
    ttl: str = "P30D"

    def __post_init__(self) -> None:
        _identifier(self.event_id, "event_id")
        _require(self.event_type in EVENT_TYPES, f"unknown event_type {self.event_type!r}")
        _timestamp(self.occurred_at)
        _identifier(self.concept_id, "concept_id")
        for value, name in (
            (self.canon_artifact_id, "canon_artifact_id"),
            (self.derivative_id, "derivative_id"),
            (self.audience_segment, "audience_segment"),
            (self.experiment_id, "experiment_id"),
        ):
            _optional_identifier(value, name)
        _require(self.platform is None or self.platform in PLATFORMS, f"unknown platform {self.platform!r}")
        _require(self.payload_ref is None or isinstance(self.payload_ref, str), "invalid payload_ref")
        _require(
            self.confidence is None or (_finite(self.confidence) and 0.0 <= self.confidence <= 1.0),
            "confidence must be within [0, 1]",
        )
        _require(self.privacy_class in PRIVACY_CLASSES, f"unknown privacy_class {self.privacy_class!r}")
        _require(_TTL.fullmatch(self.ttl) is not None, f"ttl must be an ISO-8601 duration like P30D, got {self.ttl!r}")


@dataclass(frozen=True)
class AudienceSignal(_Record):
    """One measured feedback value in one of the five separated signal groups (v3.1 §5.4)."""

    signal_id: str
    concept_id: str
    group: str
    metric: str
    value: float
    window: str
    captured_at: str
    derivative_id: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.signal_id, "signal_id")
        _identifier(self.concept_id, "concept_id")
        _require(self.group in SIGNAL_GROUPS, f"unknown signal group {self.group!r}")
        _identifier(self.metric, "metric")
        _require(_finite(self.value), "value must be a finite number")
        _identifier(self.window, "window")
        _timestamp(self.captured_at)
        _optional_identifier(self.derivative_id, "derivative_id")


@dataclass(frozen=True)
class AdaptationDecision(_Record):
    """Fast/slow loop proposal; target vocabulary structurally excludes canon (v3.1 §5.4, §5.5)."""

    decision_id: str
    concept_id: str
    loop: str
    target: str
    proposal: str
    expected_effect: str
    risk: str
    decided_at: str
    status: str = "proposed"
    approved_by: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.decision_id, "decision_id")
        _identifier(self.concept_id, "concept_id")
        _require(self.loop in LOOPS, f"unknown loop {self.loop!r}")
        _require(self.target in ADAPTATION_TARGETS, f"adaptation may not target {self.target!r}")
        _timestamp(self.decided_at)
        _require(self.status in DECISION_STATES, f"unknown status {self.status!r}")
        _require(self.status != "approved" or bool(self.approved_by), "approved decision needs approved_by")


# --- truth firewall ------------------------------------------------------------


def authorize_event(role: str, event: EcosystemEvent) -> EcosystemEvent:
    """Return the event if this role may leave that trace; attention/revenue roles cannot touch canon."""
    allowed = ROLE_EVENT_TYPES.get(role)
    if allowed is None:
        raise EcosystemError(f"unknown role {role!r}")
    if event.event_type not in allowed:
        raise EcosystemError(f"truth firewall: role {role} may not emit {event.event_type}")
    return event


def approve_canon(
    current: CanonArtifact | None,
    candidate: CanonArtifact,
    events: Sequence[EcosystemEvent],
) -> CanonArtifact:
    """Admit a canon version only through EvidenceUpdated -> CanonReview -> approval (v3.1 §5.4)."""
    reasons: list[str] = []
    if not candidate.approved_by.strip():
        reasons.append("approver missing")
    expected_version = 1 if current is None else current.version + 1
    if candidate.version != expected_version:
        reasons.append(f"version must be {expected_version}")
    if current is None:
        if candidate.supersedes is not None:
            reasons.append("first version cannot supersede")
    else:
        if candidate.concept_id != current.concept_id:
            reasons.append("concept mismatch")
        if candidate.supersedes != current.canon_id:
            reasons.append(f"must supersede {current.canon_id}")
    since = _timestamp(current.approved_at) if current is not None else None
    concept_events = [e for e in events if e.concept_id == candidate.concept_id]
    evidence_times = [
        _timestamp(e.occurred_at)
        for e in concept_events
        if e.event_type == "EvidenceUpdated" and (since is None or _timestamp(e.occurred_at) > since)
    ]
    if not evidence_times:
        suffix = f" after current canon {current.canon_id}" if current is not None else ""
        reasons.append(f"no EvidenceUpdated{suffix}")
    reviews = [
        _timestamp(e.occurred_at)
        for e in concept_events
        if e.event_type == "CanonReview" and e.canon_artifact_id == candidate.canon_id
    ]
    if not reviews:
        reasons.append(f"no CanonReview for {candidate.canon_id}")
    elif evidence_times and max(reviews) < max(evidence_times):
        reasons.append("CanonReview must follow EvidenceUpdated")
    if reasons:
        raise EcosystemError("canon approval blocked: " + "; ".join(reasons), tuple(reasons))
    return candidate


# --- lineage -------------------------------------------------------------------


def lineage(
    concept_id: str,
    canons: Iterable[CanonArtifact],
    derivatives: Iterable[PlatformDerivative],
    events: Iterable[EcosystemEvent],
) -> dict[str, Any]:
    """Reference implementation of `/v1/concepts/{id}/lineage` as a pure projection."""
    chain = sorted((c for c in canons if c.concept_id == concept_id), key=lambda c: c.version)
    for index, canon in enumerate(chain):
        previous = chain[index - 1] if index else None
        expected = (previous.version + 1, previous.canon_id) if previous else (1, None)
        if (canon.version, canon.supersedes) != expected:
            raise EcosystemError(f"broken canon chain at {canon.canon_id}")
    known = {c.canon_id: c.version for c in chain}
    latest = chain[-1].version if chain else None
    by_version: dict[int, list[str]] = {}
    stale: list[str] = []
    orphans: list[str] = []
    platforms: set[str] = set()
    for d in derivatives:
        if d.concept_id != concept_id:
            continue
        if known.get(d.canon_id) != d.canon_version:
            orphans.append(d.derivative_id)
            continue
        by_version.setdefault(d.canon_version, []).append(d.derivative_id)
        platforms.add(d.platform)
        if latest is not None and d.canon_version < latest:
            stale.append(d.derivative_id)
    decided = any(e.concept_id == concept_id and e.event_type == "AdaptationDecided" for e in events)
    return {
        "concept_id": concept_id,
        "canon_versions": [c.canon_id for c in chain],
        "latest_version": latest,
        "derivatives": by_version,
        "stale": stale,
        "orphans": orphans,
        "platforms": sorted(platforms),
        "closed": all(s in platforms for s in LOOP_SURFACES) and decided,
    }


# --- feedback aggregation and adaptation --------------------------------------


def aggregate_signals(signals: Iterable[AudienceSignal]) -> dict[str, dict[str, dict[str, float]]]:
    """Mean per concept -> group -> metric; groups stay separate so no single score exists (v3.1 §11.3)."""
    sums: dict[str, dict[str, dict[str, list[float]]]] = {}
    for s in signals:
        sums.setdefault(s.concept_id, {}).setdefault(s.group, {}).setdefault(s.metric, []).append(s.value)
    return {
        concept: {group: {metric: sum(v) / len(v) for metric, v in metrics.items()} for group, metrics in groups.items()}
        for concept, groups in sums.items()
    }


def adaptive_priority(
    *,
    existence_floor: float,
    evidence_quality: float,
    demand: float,
    utility: float,
    monetization_fit: float,
    learning_value: float,
    rights_risk: float,
    human_time: float,
    compute_cost: float,
    concentration_risk: float,
) -> float:
    """v3.1 §5.6 homeostatic objective; the floor is additive so a mandatory channel never scores zero."""
    terms = locals()
    _require(all(_finite(v) for v in terms.values()), "all priority terms must be finite numbers")
    return (
        existence_floor
        + evidence_quality * demand * utility * monetization_fit * learning_value
        - rights_risk
        - human_time
        - compute_cost
        - concentration_risk
    )


def approve_adaptation(decision: AdaptationDecision, approved_by: str) -> AdaptationDecision:
    """Adaptation Engine proposes; a named person approves (v3.1 §5.9)."""
    _require(bool(approved_by.strip()), "approver missing")
    _require(decision.status == "proposed", f"only proposed decisions can be approved, got {decision.status}")
    return replace(decision, status="approved", approved_by=approved_by)
