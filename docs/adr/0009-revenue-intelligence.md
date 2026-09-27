# ADR 0009: Revenue intelligence — claims, policy snapshots, experiments, commerce ledger (public, generic)

Status: proposed (2026-09-27). Implemented offline in `stigdev/revenue.py`
plus amendments to `stigdev/portfolio.py`; pending user review. No runtime
path, CLI, or external integration depends on it.

## Context

The private strategy document v3.2 ("Revenue Intelligence Amendment"; held in
the private `saeos-private` repository, not here) extends v3.1 on five points
that reach code:

1. External revenue claims are graded evidence (A–D), normalised into a
   `RevenueClaim`, and never model inputs unless settled and complete
   (§5.15.1, §5.15.4, §13 P0.15).
2. Platform policy thresholds carry an effective date and the audience they
   bind, so a new-entrant rule cannot raise false urgency for an existing
   channel (§5.15.2 #1, §5.15.3, §13 P0.16).
3. Every experiment is pre-registered as an `ExperimentCard` with primary
   metric, guardrails, variants, holdout, and stop rule (§5.15.6).
4. Fifteen commerce events join the OS; an order moves
   `OrderAttributed -> OrderCancelled | ProductReturned | CommissionFinalized -> CommissionPaid`;
   estimates never reach a target, finalized feeds contribution margin, only
   paid feeds owner cash (§5.15.7, §11.2, §13 P0.13–14).
5. Commerce Lab is a fourth, isolated institution: its own channel config and
   worker permissions with the linked owner on record, promoted to a public
   channel only through seven conditions (§5.15.5, §13 P0.17).

§12 lists the generic `RevenueClaim`, `PolicySnapshot`, `ExperimentCard`,
`AffiliateEvent` schemas, the external-claim verifier, and synthetic commerce
cohort fixtures as public; real claims, offers, orders, cohorts, and
commissions stay private.

## Decision

### `stigdev/revenue.py`

Records (frozen dataclasses, `to_dict`/`from_dict`): `RevenueClaim`,
`PolicySnapshot`, `ExperimentCard`, `CommerceEvent` (15 types; order events
need `order_id`, commission events need `amount`), `CommerceLabEvidence`.

Functions:

- `classify_claim(claim)`: grade A/B/C/D -> `policy_rule` / `hypothesis` /
  `sandbox_only` / `observe_only`; a claim with `scope == "unknown"`, a
  missing period, no revenue streams, or an unanswered
  `linked_offer_or_course` is demoted to at most `sandbox_only` (never
  upgraded from `observe_only`).
- `modeled_amount(claim)`: the amount only when the decision is
  `policy_rule` and `accounting_basis` is finalized/paid/net; otherwise 0.
- `policy_in_effect(snapshots, feature, channel_status, at)`: latest
  snapshot whose `effective_from <= at` and whose `applies_to` is the channel
  status or `all`; `None` when nothing binds.
- `authorize_commerce_event(role, event)`: `commerce_analytics`,
  `partnerships`, `policy_watch` each emit their own subset; no canon role
  exists here and `COMMERCE_EVENT_TYPES` is disjoint from
  `ecosystem.EVENT_TYPES` (tested), so commerce traces can never be canon.
- `order_state(events)` / `commerce_ledger(events)`: fold one order (or all
  orders) through `ORDER_TRANSITIONS` in time order; the ledger returns
  per-order states and three sums that are never added together:
  `estimated` (open orders), `finalized` (contribution base), `paid` (cash).
- `finalization_ratio`, `net_epc`, `margin_per_human_hour`,
  `survivorship_ratio` (§11.2): undefined denominators return `None`, never 0
  (Blueprint §14.1).
- `commerce_lab_promotion_gate(evidence)`: the seven §5.15.5 conditions as a
  fail-closed `GateDecision`, all blockers at once.

### `stigdev/portfolio.py` amendments

- `REVENUE_KINDS` gains `claimed` and `finalized`; `GROSS_KINDS` becomes
  `(finalized, paid)`; new `cash_revenue` (paid only). `attributed` is now
  sales analysis only and is rejected by `gross_revenue` (v3.2 §11.2).
- `ProfitSnapshot` rejects any metric key containing `view` that is not one
  of `raw_views` / `engaged_views` / `qualified_views`; `view_policy_era(at)`
  labels cohorts `pre_2026_08_24` / `first_frame_2026_08_24` (§13 P0.13).
- `ROLES` gains `commerce_lab`; `ChannelPlan.owner_ref` is required for that
  role so an isolated lab channel is always tied to its operator (§13 P0.17).

## Conflicts recorded, not resolved (AGENTS.md)

1. v3 §7.1 (ADR 0007) counted `attributed` in gross; v3.2 §11.2 restricts it
   to sales analysis while §7.3 still lists "사이트·앱의 귀속 가능한 결제"
   inside the monthly target mix and §11.3 adds "Attributed Product Revenue"
   as a separate term. Implemented §11.2: gross = finalized + paid; an
   attributed web/app payment enters the target only once it is recorded as
   a `finalized` or `paid` row.
2. Three strategy copies now sit untracked side by side (`v3`, `v3 (1)` =
   v3.1, `v3 (2)` = v3.2). This ADR follows v3.2.
3. §5.12 still shows the v3 state diagram without `pause` (ADR 0008 #1).
4. §13.1 now names `packages/revenue-intelligence` and
   `packages/policy-watch` under a renamed kernel; implemented inside
   `stigdev` (ADR 0008 #2).
5. The §5.15.4 YAML stores `decision` as a field; implemented as a derived
   value (`classify_claim`) so a stored decision cannot contradict the
   evidence fields.
6. §13 P0.13's 2026-08-24 boundary is applied at UTC midnight; the platform's
   rollout timezone is not stated in the source.
7. §13 P1.9 asks for the ten reviewed videos as fixed regression fixtures.
   Not added: this repository ships synthetic fixtures only (ADR 0003); the
   real URL registry belongs in the private operations repository.

## Failure behavior

Invalid records raise `RevenueError` at construction. `authorize_commerce_event`
and `order_state` raise with the offending role/transition; `commerce_ledger`
raises on the first broken order rather than projecting a partial ledger.
`survivorship_ratio` rejects `winners > attempts`.

## Observability

None added; commerce events are the observability. `CommerceEvent` carries an
amount only so the ledger can be tested; real orders, offers, and cohorts stay
in private storage.

## Acceptance tests

`tests/test_revenue.py` and the amended blocks of `tests/test_portfolio.py`:
record validation and round-trips, grade classification and demotion,
modeled-amount zeroing, policy selection by date and audience, every valid and
invalid order transition, time-order folding, ledger separation of
estimated/finalized/paid, role separation, ratio `None` semantics, all seven
promotion conditions, revenue kind separation, view metric keys, policy era,
commerce lab owner requirement.

## Deferred

Disclosure Gate text detection (§13 P1.10), Monetization Route Planner,
InfluenceOps Risk Gate, OfferGraph / ProblemGraph / Iteration Ledger, the
Commerce Lab publish worker and Policy Watch fetch job (runtime halves of
P0.16–17), cohort holdout experiments (P2.4), the five §13 P0.12 tables, any
YouTube/affiliate/analytics connector, and the private `saeos-ops-private`
layout.
