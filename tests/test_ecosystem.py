"""Offline tests for concept lineage, ecosystem events, and the Truth Firewall (ADR 0008)."""

import pytest

from stigdev.ecosystem import (
    ADAPTATION_TARGETS,
    CANON_WRITE_PATH,
    AdaptationDecision,
    AudienceSignal,
    CanonArtifact,
    Concept,
    EcosystemError,
    EcosystemEvent,
    EvidenceBundle,
    PlatformDerivative,
    adaptive_priority,
    aggregate_signals,
    approve_adaptation,
    approve_canon,
    authorize_event,
    lineage,
)

T0 = "2026-09-27T00:00:00+00:00"
T1 = "2026-09-27T01:00:00+00:00"
T2 = "2026-09-27T02:00:00+00:00"
T3 = "2026-09-27T03:00:00+00:00"


def event(event_type, occurred_at=T0, **kw) -> EcosystemEvent:
    base = dict(event_id=f"evt-{event_type}-{occurred_at[11:13]}", event_type=event_type, occurred_at=occurred_at, concept_id="c1")
    base.update(kw)
    return EcosystemEvent(**base)


def canon(version=1, canon_id="canon-1", supersedes=None, approved_by="reviewer", approved_at=T1) -> CanonArtifact:
    return CanonArtifact(canon_id, "c1", version, "sha256:abc", "bundle-1", approved_by, approved_at, supersedes)


def derivative(derivative_id, platform, kind, canon_version=1, canon_id="canon-1", **kw) -> PlatformDerivative:
    return PlatformDerivative(derivative_id, "c1", canon_id, canon_version, platform, kind, **kw)


# --- records -----------------------------------------------------------------


@pytest.mark.parametrize(
    "record",
    [
        Concept("c1", "synthetic model release", T0),
        EvidenceBundle("bundle-1", "c1", ("src-1", "src-2"), T0, expires_at=T3),
        canon(),
        derivative("d1", "youtube", "signal_short", cta_target="web:report-1", channel_id="signal-synthetic"),
        event("QuestionAsked", confidence=0.82, payload_ref="artifact://q1", audience_segment="creator_local_ai"),
        AudienceSignal("s1", "c1", "attention", "retention_30s", 0.42, "24h", T1, derivative_id="d1"),
        AdaptationDecision("a1", "c1", "fast", "packaging", "shorter hook", "+5% retention", "low", T2),
    ],
)
def test_records_round_trip_through_dict(record):
    assert type(record).from_dict(record.to_dict()) == record


@pytest.mark.parametrize(
    "build",
    [
        lambda: event("ViewsSpiked"),
        lambda: event("VideoWatched", confidence=1.5),
        lambda: event("VideoWatched", privacy_class="raw"),
        lambda: event("VideoWatched", platform="tiktok"),
        lambda: event("VideoWatched", ttl="30 days"),
        lambda: event("VideoWatched", occurred_at="2026-09-27T00:00:00"),
        lambda: derivative("d1", "youtube", "reaction_clip"),
        lambda: derivative("d1", "youtube", "signal_short", canon_version=0),
        lambda: canon(version=0),
        lambda: AudienceSignal("s1", "c1", "vibes", "m", 1.0, "24h", T1),
        lambda: AudienceSignal("s1", "c1", "attention", "m", float("inf"), "24h", T1),
        lambda: AdaptationDecision("a1", "c1", "fast", "canon", "edit claim", "", "low", T2),
        lambda: AdaptationDecision("a1", "c1", "medium", "packaging", "p", "", "low", T2),
        lambda: AdaptationDecision("a1", "c1", "fast", "packaging", "p", "", "low", T2, status="approved"),
    ],
)
def test_invalid_records_are_rejected(build):
    with pytest.raises(EcosystemError):
        build()


def test_adaptation_targets_never_include_canon():
    assert "canon" not in ADAPTATION_TARGETS and CANON_WRITE_PATH == ("EvidenceUpdated", "CanonReview", "CanonApproved")


# --- truth firewall ------------------------------------------------------------


@pytest.mark.parametrize(
    "role,event_type",
    [
        ("sensor", "TrendDetected"),
        ("evidence", "EvidenceUpdated"),
        ("canon_reviewer", "CanonApproved"),
        ("format_adapter", "DerivativeRendered"),
        ("analytics", "VideoWatched"),
        ("controller", "AdaptationDecided"),
    ],
)
def test_authorize_event_allows_role_owned_types(role, event_type):
    e = event(event_type)
    assert authorize_event(role, e) is e


@pytest.mark.parametrize(
    "role,event_type",
    [
        ("format_adapter", "EvidenceUpdated"),
        ("analytics", "CanonApproved"),
        ("analytics", "CorrectionIssued"),
        ("publisher", "CanonReview"),
        ("sensor", "CanonApproved"),
    ],
)
def test_authorize_event_blocks_attention_and_revenue_roles_from_canon(role, event_type):
    with pytest.raises(EcosystemError, match="truth firewall"):
        authorize_event(role, event(event_type))


def test_authorize_event_rejects_unknown_role():
    with pytest.raises(EcosystemError, match="unknown role"):
        authorize_event("growth_hacker", event("VideoWatched"))


def test_approve_canon_first_version_needs_review_path():
    events = [event("EvidenceUpdated", T0), event("CanonReview", T1, canon_artifact_id="canon-1")]
    assert approve_canon(None, canon(approved_at=T2), events) == canon(approved_at=T2)


def test_approve_canon_next_version_supersedes_and_needs_fresh_evidence():
    current = canon(approved_at=T1)
    candidate = canon(version=2, canon_id="canon-2", supersedes="canon-1", approved_at=T3)
    stale = [event("EvidenceUpdated", T0), event("CanonReview", T2, canon_artifact_id="canon-2")]
    with pytest.raises(EcosystemError) as info:
        approve_canon(current, candidate, stale)
    assert info.value.reasons == ("no EvidenceUpdated after current canon canon-1",)
    fresh = [event("EvidenceUpdated", T2), event("CanonReview", T2, canon_artifact_id="canon-2")]
    assert approve_canon(current, candidate, fresh) == candidate


def test_approve_canon_collects_every_blocker():
    current = canon(approved_at=T1)
    candidate = canon(version=3, canon_id="canon-3", supersedes="canon-9", approved_by="", approved_at=T3)
    with pytest.raises(EcosystemError) as info:
        approve_canon(current, candidate, [])
    assert info.value.reasons == (
        "approver missing",
        "version must be 2",
        "must supersede canon-1",
        "no EvidenceUpdated after current canon canon-1",
        "no CanonReview for canon-3",
    )


def test_approve_canon_requires_review_after_evidence():
    events = [event("CanonReview", T0, canon_artifact_id="canon-1"), event("EvidenceUpdated", T1)]
    with pytest.raises(EcosystemError, match="CanonReview"):
        approve_canon(None, canon(approved_at=T2), events)


# --- lineage -------------------------------------------------------------------


def test_lineage_groups_derivatives_and_flags_stale_and_orphans():
    canons = [canon(), canon(version=2, canon_id="canon-2", supersedes="canon-1", approved_at=T2)]
    derivatives = [
        derivative("short-v1", "youtube", "signal_short", canon_version=1),
        derivative("report-v2", "web", "canon_report", canon_version=2, canon_id="canon-2"),
        derivative("alert-v2", "app", "watchlist_alert", canon_version=2, canon_id="canon-2"),
        derivative("ghost", "sns", "card", canon_version=1, canon_id="canon-0"),
    ]
    events = [event("AdaptationDecided", T3)]
    result = lineage("c1", canons, derivatives, events)
    assert result == {
        "concept_id": "c1",
        "canon_versions": ["canon-1", "canon-2"],
        "latest_version": 2,
        "derivatives": {1: ["short-v1"], 2: ["report-v2", "alert-v2"]},
        "stale": ["short-v1"],
        "orphans": ["ghost"],
        "platforms": ["app", "web", "youtube"],
        "closed": True,
    }


def test_lineage_is_open_without_all_three_surfaces_or_decision():
    canons = [canon()]
    derivatives = [derivative("short-v1", "youtube", "signal_short"), derivative("report", "web", "canon_report")]
    assert lineage("c1", canons, derivatives, [event("AdaptationDecided", T3)])["closed"] is False
    derivatives.append(derivative("alert", "app", "watchlist_alert"))
    assert lineage("c1", canons, derivatives, [])["closed"] is False


def test_lineage_rejects_broken_canon_chain():
    canons = [canon(), canon(version=3, canon_id="canon-3", supersedes="canon-1")]
    with pytest.raises(EcosystemError, match="broken canon chain"):
        lineage("c1", canons, [], [])


def test_lineage_ignores_other_concepts():
    other = CanonArtifact("canon-x", "c2", 1, "sha256:x", "bundle-x", "reviewer", T1)
    result = lineage("c1", [canon(), other], [], [])
    assert result["canon_versions"] == ["canon-1"]


# --- feedback aggregation and adaptation --------------------------------------


def test_aggregate_signals_means_per_concept_group_metric():
    signals = [
        AudienceSignal("s1", "c1", "attention", "retention_30s", 0.4, "24h", T1),
        AudienceSignal("s2", "c1", "attention", "retention_30s", 0.6, "24h", T2),
        AudienceSignal("s3", "c1", "utility", "topic_saved", 12.0, "7d", T2),
        AudienceSignal("s4", "c2", "economic", "attributed_krw", 5000.0, "7d", T2),
    ]
    assert aggregate_signals(signals) == {
        "c1": {"attention": {"retention_30s": 0.5}, "utility": {"topic_saved": 12.0}},
        "c2": {"economic": {"attributed_krw": 5000.0}},
    }


def test_adaptive_priority_keeps_floor_additive_and_costs_subtractive():
    floor_only = adaptive_priority(existence_floor=1.0, evidence_quality=0.0, demand=0.0, utility=0.0, monetization_fit=0.0, learning_value=0.0, rights_risk=0.0, human_time=0.0, compute_cost=0.0, concentration_risk=0.0)
    assert floor_only == 1.0
    scored = adaptive_priority(existence_floor=0.0, evidence_quality=0.5, demand=2.0, utility=1.0, monetization_fit=1.0, learning_value=1.0, rights_risk=0.2, human_time=0.1, compute_cost=0.1, concentration_risk=0.1)
    assert scored == pytest.approx(0.5)
    with pytest.raises(EcosystemError):
        adaptive_priority(existence_floor=float("nan"), evidence_quality=0.0, demand=0.0, utility=0.0, monetization_fit=0.0, learning_value=0.0, rights_risk=0.0, human_time=0.0, compute_cost=0.0, concentration_risk=0.0)


def test_approve_adaptation_requires_named_approver_and_proposed_state():
    proposed = AdaptationDecision("a1", "c1", "slow", "budget", "shift 10% to signal", "+lead quality", "medium", T2)
    approved = approve_adaptation(proposed, "operator")
    assert approved.status == "approved" and approved.approved_by == "operator"
    with pytest.raises(EcosystemError, match="approver"):
        approve_adaptation(proposed, "")
    with pytest.raises(EcosystemError, match="proposed"):
        approve_adaptation(approved, "operator")


def test_approve_canon_rejects_review_older_than_newest_evidence():
    events = [
        event("EvidenceUpdated", T0),
        event("CanonReview", T1, canon_artifact_id="canon-1"),
        event("EvidenceUpdated", T2),
    ]
    with pytest.raises(EcosystemError, match="CanonReview must follow"):
        approve_canon(None, canon(approved_at=T3), events)
