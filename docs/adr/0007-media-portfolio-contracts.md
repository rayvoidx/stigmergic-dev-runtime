# ADR 0007: Media portfolio, rights, and release contracts (public, generic)

Status: proposed (2026-09-27), amended the same day by ADR 0008 (`pause` stage,
existence floor, SLA, `concept_id` links). Implemented offline in
`stigdev/portfolio.py` pending user review; no runtime path, CLI, or external integration depends on
it.

## Context

`docs/adr/YouTube_Portfolio_and_RAYV_Strategy_SAEOS_v3_2026-09-27.md` §13 P0
lists six additions to the SAEOS Media Foundry design: portfolio tables
(`channel_plans`, `rights_assets`, `release_units`, `profit_snapshots`,
`format_hypotheses`), a Rights Gate forced ahead of publish, a release-unit
workflow, weekly publish caps with at most two channels in `scale`, revenue
split into `estimated | paid | attributed | influenced`, and a pre-publish
check (private upload, Content ID result, AI disclosure).

Its §12 and `SAEOS_Media_Foundry_Integrated_Design_v1.md` §8 place the generic
`ChannelPlan`, `RightsManifest`, `ReleaseUnit` schemas, the quality/rights/AI
disclosure evaluators, and the state machine in the public repository, and all
real channel IDs, revenue, prompts, masters, and scoring weights in private
storage. `SAEOS_Media_Foundry_Implementation_Blueprint_v2.md` §1 puts the
control plane and media foundry in a private repository that does not exist
yet.

## Decision

Add one stdlib module, `stigdev/portfolio.py`, holding typed records and
pure, fail-closed gate functions. It stores nothing, calls nothing, and takes
`now` from the caller (same rule as the task ledger). Private consumers
supply real data; this repository ships only synthetic test fixtures.

### Records (frozen dataclasses, `to_dict`/`from_dict`)

| Record | v3 table | Validation in `__post_init__` |
|---|---|---|
| `ChannelPlan` | `channel_plans` | identifier, `stage` in `STAGES`, `business_role` in `ROLES` (`cash_engine`, `ip_engine`, `product_funnel`), caps keyed by `FORMATS`, `0 <= owned_ip_ratio_min <= 1` |
| `RightsManifest` | `rights_assets` | `rights_basis` in `original/licensed/public_domain/unknown`, `exclusivity` in `exclusive/non_exclusive/none` |
| `ReleaseUnit` | `release_units` | identifier, `distributor_delivery` in `pending/delivered` |
| `ProfitSnapshot` | `profit_snapshots` | `window` in `SNAPSHOT_WINDOWS`; metric values finite floats — a missing value is omitted, never recorded as 0 (Blueprint §14.1) |
| `FormatHypothesis` | `format_hypotheses` | `status` in `open/supported/rejected/inconclusive` |
| `RevenueEvent` | revenue ledger rows | `kind` in `REVENUE_KINDS`, finite `amount >= 0` |

### State machine (v3 §5.4)

`hypothesis -> private_pilot -> public_pilot -> {scale, retire}`,
`scale -> maintain`, `maintain -> {scale, retire}`, `retire` terminal.
`advance_stage` rejects any other edge. Entering `scale` additionally
requires a `ScaleEvidence` satisfying the seven §5.4 conditions and fewer
than `MAX_SCALE_CHANNELS = 2` other channels already in `scale`.

### Gates (all return `GateDecision(gate_id, passed, reasons)`)

- `rights_gate(manifests, now)`: fails on an empty manifest set, unknown
  basis, no commercial use, missing owner, licensed without receipt hash,
  expiry at or before `now`, or `content_id_eligible` without exclusive
  original rights (v3 §5.5, §6.6).
- `release_gate(unit, master_rights, now)`: rights gate on the master,
  manifest must cover `master_artifact_id`, ISRC present, splits sum to 1,
  `official_visualizer` derivative present (v3 §6.4).
- `publish_gate(candidate, plan, published_this_week, now)`: channel match,
  stage publishable, weekly cap (`can_publish`), upload still `private`,
  Content ID result `clear`, AI disclosure decided, approved payload hash
  equals current payload hash, rights gate (v3 §13 P0.6, Blueprint §12.3,
  §13.2).

### Revenue

`revenue_by_kind` never sums across kinds. `gross_revenue` accepts only
`paid` and `attributed`; asking it to include `estimated` or `influenced`
raises `PortfolioError`. `contribution_margin(events, direct_costs)` is gross
minus caller-supplied direct costs (v3 §7.1).

## Failure behavior

Every gate is fail-closed: any reason means `passed=False`, and the full
reason list is returned so an operator sees all blockers at once. Invalid
records raise `PortfolioError` at construction. `advance_stage` raises
`PortfolioError` carrying the unmet conditions.

## Observability

None added. Gate decisions are plain values; a private control plane records
them as events. Reason strings are stable and contain only identifiers.

## Acceptance tests

`tests/test_portfolio.py`: record round-trips and validation, every rights
gate reason, release gate reasons, publish gate reasons including hash
mismatch and weekly cap, all valid and one invalid stage edge, scale
conditions and the two-channel limit, revenue kind separation.

## Operator direction recorded 2026-09-27

Signal Stories is mandatory (it feeds and is fed by the private Social Trend
product), so the third channel exists from the start as `product_funnel`;
the `MAX_SCALE_CHANNELS = 2` rule caps only concurrent `scale` slots, not
channel count. The operator wants one organic loop web/app service <->
YouTube video (v3 §8 single-CTA table, Blueprint §14.2 attribution chain).
Today the module covers only the money end of that loop (`attributed`
revenue with a `source`); CTA/product-link records wait for the operator's
follow-up analysis.

## Deferred

- Workflow DSL, SQLite tables, and the RAYV Release Unit workflow execution
  (needs the unmerged event-store/scheduler stack and a private repository).
- Content ID allowlist management, human-time measurement, Signal shadow
  pipeline (v3 §13 P1/P2).
- Any YouTube, distributor, or analytics connector.
