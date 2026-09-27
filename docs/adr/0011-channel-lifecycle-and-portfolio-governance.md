# ADR 0011: Channel lifecycle, overlap, payout ladder, and incident control

Status: proposed (2026-09-28). Implemented offline in `stigdev/lifecycle.py`,
`stigdev/overlap.py`, `stigdev/payout.py`, and `stigdev/incident.py` pending
user review; no runtime path, CLI, or external integration depends on them.

## Context

Two private strategy documents were amended after ADR 0007-0010 landed: the
SAEOS Media Foundry strategy v3.3 ("Multi-Channel Revenue Governance") and the
Implementation Blueprint v2.1. Both are held in the private `saeos-private`
repository, not here.

The occasion was an external claim: an operator reporting 27 channels and
60,000,000 KRW in a month, restated elsewhere as 40,000,000. Bank-balance and
payout screens accompanied it. None of that establishes ownership of the 27
channels, the period the money belongs to, costs, tax, or what was actually
received — and the same money can appear simultaneously as an estimate, a
pending payout, and an account balance. The claim is therefore graded `C` and
usable for pattern research only; it must never reach a forecast or a scale
decision.

What the case does contain is an operating structure worth encoding: distinct
audience contracts over a shared production pipeline, canary-then-cohort
validation, and expansion only for members that are profitable after human
time. The accompanying folklore — burner phones, spare SIMs, family members'
names — is rejected outright and documented in `docs/anti-evasion.md`.

## Decision

Add four stdlib modules of pure records and fail-closed transitions. They
store nothing, call nothing, and take `now` from the caller, matching
`stigdev/portfolio.py`.

### `lifecycle` — the operational channel lifecycle

`proposed -> unlisted_canary -> pilot -> monetization_gating -> scale ->
maintain -> retire`, with an orthogonal incident overlay
`clear -> watch -> quarantined -> frozen`. Entering `scale` requires
`ScaleEvidence` satisfying all seven v3.3 §5.16.4 conditions, a named approver,
and a free slot under `PortfolioPolicy.max_scale` (2). De-escalating an
incident requires a named resolver; escalation does not.

Also `AudienceContract` (one per channel, the independence the scale gate
checks) and `FormatFingerprint` (script and asset hashes, so exact
cross-channel reuse is detectable rather than assumed absent).

### `overlap` — review priority, not a verdict

`PortfolioOverlap` as the documented weighted sum over six similarity
components, weights asserted to total 1.0. `review_queue` orders pairs above a
threshold. This is an internal heuristic; it never blocks a publish.

### `payout` — one ladder, never a sum

`observed -> platform_estimated -> platform_finalized -> paid ->
bank_reconciled -> net`. Each rung is a better-evidenced view of the *same*
money, so `total_across` totals one rung and refuses a mixed set rather than
coercing it. Business promotion reads `platform_finalized` at the earliest; a
cash figure reads `paid` or `bank_reconciled` only.
`risk_adjusted_contribution_margin` subtracts human labour, rights, compute,
operator payout, refunds, and a policy-loss reserve from finalized revenue.

### `incident` — scoped stopping

`PolicyIncident` with severities mapped to a kill floor, and the K0-K4 ladder:
video, channel, format family, portfolio read-only, credential revocation.
`halted_channels` walks the portfolio graph; `action_allowed` fails closed, and
at K4 refuses reads too, because the credential is gone.

### Relationship to `portfolio.STAGES`

`portfolio.py` already carries the coarser v3 §5.4 stages, published in ADR
0007 and depended on across the suite. Rather than rewrite those call sites,
`lifecycle.PORTFOLIO_STAGE` maps the finer machine onto the coarser one and a
test asserts the mapping is total and monotonic. Two names (`pilot`,
`monetization_gating`) collapse onto `public_pilot`.

This duplication is deliberate but temporary: the finer lifecycle is canonical,
and a follow-up should collapse `portfolio.STAGES` into it once the private
consumers that read the coarse names have moved.

## Alternatives considered

- **Rewriting `portfolio.STAGES` in place.** Correct in the long run, but it
  touches roughly seventy call sites across modules and tests that other work
  had just committed, for no behavioural gain today.
- **Adding the eight `packages/*` trees the blueprints sketch.** This
  repository is a single stdlib-only package with a paper-track identity;
  restructuring it into a monorepo would serve the document's layout rather
  than the code. The module names carry the same separation.

## Consequences

- The synthetic 27-channel portfolio in
  `examples/synthetic_27_channel_portfolio/` is the regression surface: scale
  limits, a deliberately duplicated asset pair, a quarantined format family, a
  month-end reconciliation, and the graded external claim.
- Public fixtures hold no real channel IDs, audiences, revenue, accounts, or
  prompts, and a test asserts it. A first draft of the fixture used a real
  brand name as a family ID; that test caught it.
- What is still missing: the audit-event stream, `Policy Watch` for tracking
  platform-rule effective dates, and the private revenue control plane itself.
