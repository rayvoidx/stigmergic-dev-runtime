"""Channel lifecycle, audience contracts, and the scale gate (ADR 0011).

v3.3 §5.16.4 names an operational channel lifecycle finer than the v3 §5.4
stages already in :mod:`stigdev.portfolio`: it separates the unlisted canary
from the public pilot and adds an explicit monetization-gating step. This
module holds the finer machine and :data:`PORTFOLIO_STAGE` maps it onto the
coarse one, so the two views cannot drift silently.

Pure records and fail-closed transitions. Nothing here stores, schedules, or
publishes; ``now`` is caller-supplied. Real channel IDs, audiences, and
fingerprint vectors belong to private consumers.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Any, Iterable, Sequence

from .portfolio import DEFAULT_POLICY, GateDecision, PortfolioPolicy
from .workspace import valid_identifier

LIFECYCLE_STATES = (
    "proposed",
    "unlisted_canary",
    "pilot",
    "monetization_gating",
    "scale",
    "maintain",
    "retire",
)
LIFECYCLE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "proposed": ("unlisted_canary", "retire"),
    "unlisted_canary": ("pilot", "retire"),
    "pilot": ("monetization_gating", "retire"),
    "monetization_gating": ("scale", "maintain", "retire"),
    "scale": ("maintain",),
    "maintain": ("scale", "retire"),
    "retire": (),
}
# The coarse v3 §5.4 view kept in stigdev.portfolio. Two names collapse onto
# `public_pilot`: a channel is publicly piloting both before and during the
# monetization check, which is why the finer machine is canonical here.
PORTFOLIO_STAGE: dict[str, str] = {
    "proposed": "hypothesis",
    "unlisted_canary": "private_pilot",
    "pilot": "public_pilot",
    "monetization_gating": "public_pilot",
    "scale": "scale",
    "maintain": "maintain",
    "retire": "retire",
}
PUBLISHING_STATES = ("pilot", "monetization_gating", "scale", "maintain")
COUNTED_STATES = tuple(s for s in LIFECYCLE_STATES if s != "retire")

# Incident overlay (v3.3 §5.16.4). Orthogonal to the lifecycle: a channel keeps
# its lifecycle state while an incident restricts what may act on it.
INCIDENT_STATES = ("clear", "watch", "quarantined", "frozen")
MIN_POSITIVE_COHORTS = 3
SCALE_GATE_ID = "channel-scale-gate/v1"


class LifecycleError(ValueError):
    def __init__(self, message: str, reasons: tuple[str, ...] = ()):
        super().__init__(message)
        self.reasons = reasons


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LifecycleError(message)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


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
class AudienceContract(_Record):
    """Who the channel is for and what it promises them (v3.3 §4.1, §5.16.2)."""

    _tuple_fields = ("exclusions",)

    channel_id: str
    audience: str
    viewer_job: str
    promise: str
    exclusions: tuple[str, ...] = ()
    version: int = 1

    def __post_init__(self) -> None:
        _require(valid_identifier(self.channel_id), "invalid channel_id")
        for name in ("audience", "viewer_job", "promise"):
            _require(bool(getattr(self, name).strip()), f"{name} must be a non-empty string")
        _require(isinstance(self.version, int) and self.version >= 1, "version must be >= 1")


@dataclass(frozen=True)
class FormatFingerprint(_Record):
    """Hashes that make cross-channel reuse detectable (v3.3 §5.16.5)."""

    _tuple_fields = ("script_hashes", "asset_hashes", "visual_voice_vector")

    channel_id: str
    script_hashes: tuple[str, ...] = ()
    asset_hashes: tuple[str, ...] = ()
    visual_voice_vector: tuple[float, ...] = ()
    version: int = 1

    def __post_init__(self) -> None:
        _require(valid_identifier(self.channel_id), "invalid channel_id")
        for group in (self.script_hashes, self.asset_hashes):
            _require(all(isinstance(h, str) and h.strip() for h in group), "hashes must be non-empty strings")
        _require(all(_finite(v) for v in self.visual_voice_vector), "visual_voice_vector must be finite numbers")
        _require(isinstance(self.version, int) and self.version >= 1, "version must be >= 1")

    def shared_assets(self, other: "FormatFingerprint") -> frozenset[str]:
        """Exact asset reuse across two channels; a non-empty set is a hard publish failure."""
        return frozenset(self.asset_hashes) & frozenset(other.asset_hashes)

    def shared_scripts(self, other: "FormatFingerprint") -> frozenset[str]:
        return frozenset(self.script_hashes) & frozenset(other.script_hashes)


@dataclass(frozen=True)
class ChannelSlot(_Record):
    """One channel's position in the portfolio (v2.1 §5.2 `channel_slots`)."""

    _tuple_fields = ("reason_codes",)

    channel_id: str
    family_id: str
    lifecycle_state: str = "proposed"
    incident_state: str = "clear"
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require(valid_identifier(self.channel_id), "invalid channel_id")
        _require(valid_identifier(self.family_id), "invalid family_id")
        _require(self.lifecycle_state in LIFECYCLE_STATES, f"unknown lifecycle_state {self.lifecycle_state!r}")
        _require(self.incident_state in INCIDENT_STATES, f"unknown incident_state {self.incident_state!r}")

    @property
    def portfolio_stage(self) -> str:
        return PORTFOLIO_STAGE[self.lifecycle_state]

    @property
    def counted_active(self) -> bool:
        return self.lifecycle_state in COUNTED_STATES

    @property
    def may_publish(self) -> bool:
        """An incident of any severity suspends publishing, whatever the lifecycle says."""
        return self.lifecycle_state in PUBLISHING_STATES and self.incident_state == "clear"


@dataclass(frozen=True)
class ScaleEvidence(_Record):
    """The seven v3.3 §5.16.4 conditions; the caller measures them."""

    independent_audience_contract: bool
    rights_originality_disclosure_pass: bool
    positive_margin_cohorts: int
    holds_without_top_video: bool
    overlap_review_passed: bool
    policy_strikes: int
    unresolved_rights_incidents: int
    capacity_available: bool
    approved_by: str | None = None

    def __post_init__(self) -> None:
        for name in ("positive_margin_cohorts", "policy_strikes", "unresolved_rights_incidents"):
            value = getattr(self, name)
            _require(isinstance(value, int) and not isinstance(value, bool) and value >= 0,
                     f"{name} must be a non-negative integer")


def scale_reasons(evidence: ScaleEvidence) -> tuple[str, ...]:
    checks = (
        (evidence.independent_audience_contract, "audience contract is not independent"),
        (evidence.rights_originality_disclosure_pass, "rights, originality or AI disclosure did not hard pass"),
        (evidence.positive_margin_cohorts >= MIN_POSITIVE_COHORTS,
         f"fewer than {MIN_POSITIVE_COHORTS} cohorts with positive margin including human time"),
        (evidence.holds_without_top_video, "signal does not hold with the top video removed"),
        (evidence.overlap_review_passed, "cross-channel overlap review not passed"),
        (evidence.policy_strikes == 0, "policy strikes present"),
        (evidence.unresolved_rights_incidents == 0, "unresolved rights incidents present"),
        (evidence.capacity_available, "no GPU, reviewer or calendar capacity"),
        (bool(evidence.approved_by), "operator approval missing"),
    )
    return tuple(reason for ok, reason in checks if not ok)


def scale_gate(evidence: ScaleEvidence) -> GateDecision:
    reasons = scale_reasons(evidence)
    return GateDecision(SCALE_GATE_ID, not reasons, reasons)


def counts(portfolio: Iterable[ChannelSlot]) -> dict[str, int]:
    slots = list(portfolio)
    return {
        "active": sum(1 for s in slots if s.counted_active),
        "scale": sum(1 for s in slots if s.lifecycle_state == "scale"),
        "publishing": sum(1 for s in slots if s.may_publish),
    }


def advance_lifecycle(
    slot: ChannelSlot,
    to: str,
    portfolio: Sequence[ChannelSlot] = (),
    evidence: ScaleEvidence | None = None,
    policy: PortfolioPolicy = DEFAULT_POLICY,
) -> ChannelSlot:
    """Move one channel along the v3.3 lifecycle; `scale` needs evidence and a free slot."""
    _require(to in LIFECYCLE_STATES, f"unknown lifecycle_state {to!r}")
    if to not in LIFECYCLE_TRANSITIONS[slot.lifecycle_state]:
        raise LifecycleError(f"invalid transition {slot.lifecycle_state} -> {to}")
    if slot.incident_state != "clear":
        raise LifecycleError(f"channel {slot.channel_id} is {slot.incident_state}; resolve the incident first")
    if to == "scale":
        if evidence is None:
            raise LifecycleError("scale evidence required")
        reasons = scale_reasons(evidence)
        if reasons:
            raise LifecycleError("scale conditions unmet: " + "; ".join(reasons), reasons)
        others = sum(
            1 for s in portfolio if s.lifecycle_state == "scale" and s.channel_id != slot.channel_id
        )
        if others >= policy.max_scale:
            raise LifecycleError(f"scale limit: {policy.max_scale} channels already in scale")
    return replace(slot, lifecycle_state=to)


def set_incident_state(slot: ChannelSlot, to: str, *, resolved_by: str | None = None) -> ChannelSlot:
    """Escalate freely; de-escalating towards `clear` needs a named resolver."""
    _require(to in INCIDENT_STATES, f"unknown incident_state {to!r}")
    current, target = INCIDENT_STATES.index(slot.incident_state), INCIDENT_STATES.index(to)
    if target < current and not resolved_by:
        raise LifecycleError("de-escalating an incident requires a named resolver")
    return replace(slot, incident_state=to)
