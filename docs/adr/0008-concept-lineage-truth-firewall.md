# ADR 0008: Concept lineage, ecosystem events, and the Truth Firewall (public, generic)

Status: proposed (2026-09-27). Implemented offline in `stigdev/ecosystem.py`
plus additions to `stigdev/portfolio.py`; pending user review. No runtime
path, CLI, or external integration depends on it.

## Context

The private strategy document v3.1 ("Organic Ecosystem Amendment"; held in the
private `saeos-private` repository, not here) supersedes v3 on three points
that reach code:

1. Signal Stories becomes a mandatory public channel with an existence floor,
   minimum cadence, and a time-sensitivity SLA (§4.2, §5.6, §13 P0.4).
2. Every derivative on every surface shares one `concept_id` and a canon
   lineage; audience behaviour flows back as events (§5.2, §5.3, §8).
3. A Truth Firewall separates attention/utility/economic/risk signals from
   canon: they may change packaging, CTA, cadence, budget, or review level,
   never a canon claim. Canon changes only via
   `EvidenceUpdated -> CanonReview -> CanonApproved` (§5.4, §8.3).

§12 lists the generic `EcosystemEvent`, `Concept`, `CanonArtifact`,
`PlatformDerivative`, `AdaptationDecision` schemas and the fast/slow loop,
Truth Firewall, and lineage API reference implementation as public.

## Decision

### `stigdev/ecosystem.py`

Records (frozen dataclasses, `to_dict`/`from_dict`): `Concept`,
`EvidenceBundle`, `CanonArtifact` (versioned, `supersedes` chain),
`PlatformDerivative` (one surface, one kind, at most one `cta_target`),
`EcosystemEvent` (§5.3 envelope: 16 event types, confidence in [0, 1],
privacy class, ISO-8601 TTL), `AudienceSignal` (five separated groups),
`AdaptationDecision` (fast/slow loop; `target` vocabulary structurally
excludes canon).

Functions:

- `authorize_event(role, event)`: role -> allowed event types. `analytics`,
  `format_adapter`, `publisher` cannot emit `EvidenceUpdated`, `CanonReview`,
  `CanonApproved`, or `CorrectionIssued`.
- `approve_canon(current, candidate, events)`: version must be
  `current.version + 1` and supersede `current`; needs an `EvidenceUpdated`
  after the current canon's approval and a `CanonReview` for the candidate
  that follows it; approver named. All blockers returned at once.
- `lineage(concept_id, canons, derivatives, events)`: pure projection of the
  §13 P0.5 `/v1/concepts/{id}/lineage` endpoint. Validates the canon chain,
  groups derivatives by canon version, lists `stale` (older than latest
  canon: correction/update candidates) and `orphans` (unknown canon: §11.3
  health metric), and reports `closed` when youtube, web, and app
  derivatives exist and an `AdaptationDecided` event was recorded.
- `aggregate_signals`: mean per concept/group/metric; groups never merge
  into one score.
- `adaptive_priority`: §5.6 formula; the floor is additive.
- `approve_adaptation`: proposals become approved only with a named person.

### `stigdev/portfolio.py` additions

- `pause` stage: reversible from `public_pilot`, `scale`, `maintain`; resumes
  to `maintain`; not publishable.
- `ChannelPlan.existence_floor` (per-format weekly minimum, must fit under
  the cap) and `time_sensitivity_hours`. `mandatory` is derived from the
  floor. A mandatory channel cannot `retire`; `floor_deficit` and
  `sla_breached` feed the scheduler's P2 protection (v3.1 §10.3).
- Optional `concept_id` on `RightsManifest`, `ReleaseUnit`,
  `ProfitSnapshot`, `FormatHypothesis`, `RevenueEvent` (§13 P0.2).
  `ChannelPlan` stays concept-free: a channel is a container, not a concept.

## Conflicts recorded, not resolved (AGENTS.md)

1. v3.1 §4.2 adds a `pause` row and says mandatory channels are never
   retired; §5.12 keeps the v3 state diagram with `Retire` edges and no
   `Pause`. Implemented: diagram plus `pause`, retire blocked only when
   `existence_floor > 0`.
2. v3.1 §13.1 names the public kernel `stigmergic-agentic-engineering-os`
   with `packages/{event-schema, canon-lineage, truth-firewall,
   platform-adapters}`. ADR 0005 keeps `stigmergic-dev-runtime` / `stigdev`.
   Implemented inside `stigdev`; renaming or splitting is a separate
   decision.
3. §13 P0.5 asks for HTTP endpoints. The public kernel is stdlib-only with
   no web framework (Blueprint v2 §3 puts `api` in the private control
   plane). Implemented as pure functions the private API can wrap.
4. Two strategy documents now sit untracked side by side (`v3` and
   `v3 (1)` = v3.1). v3.1 is the newer, and this ADR follows it.

## Failure behavior

Invalid records raise `EcosystemError` at construction. `authorize_event`
and `approve_canon` raise with the full reason list; `lineage` raises on a
broken chain rather than projecting a partial answer.

## Observability

None added; events are the observability. `EcosystemEvent` carries no
payload, only a `payload_ref`, so no audience data enters this repository.

## Acceptance tests

`tests/test_ecosystem.py` and the mandatory-channel block of
`tests/test_portfolio.py`: record validation, every firewall rule, canon
approval ordering, stale/orphan/closed lineage, aggregation, priority,
adaptation approval, pause reversibility, retire block, floor deficit, SLA,
`concept_id` round-trips.

## Deferred

Correction-task generation from `stale`, the `Feedback Aggregator` over real
platform events, cohort holdout experiments (§13 P2.4), any HTTP surface,
YouTube/web/app connectors, and the private `saeos-ops-private` layout.
