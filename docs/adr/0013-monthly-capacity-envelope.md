# ADR 0013: Monthly capacity envelope and revenue sensitivity (public, generic)

Status: proposed (2026-09-29). Implemented offline in `stigdev/capacity.py`;
pending user review. No runtime path, CLI, or external integration depends on
it.

## Context

ADR 0012 admits or refuses **one job right now**: slots, memory headroom, a
calm machine. Two existing gates ask a different, month-scale question and
currently take the answer on faith:

- `lifecycle.ScaleEvidence.capacity_available` is a bare bool the caller
  asserts ("no GPU, reviewer or calendar capacity").
- `portfolio.PortfolioEvidence.review_hours_per_week` is a number the caller
  measures, checked against `PortfolioPolicy.max_review_hours_per_week`.

A capacity analysis dated 2026-09 (operator-supplied, held privately) sizes
the portfolio against one M5 Ultra at 70% utilisation and concludes **10
channels operating, 12 as a hard cap**, on four grounds that reach code:

1. A month of wall-clock at 70% is a finite compute budget, and every channel
   draws on the same LLM / image / TTS-render queues rather than owning a
   model.
2. Human review, not the GPU, is what runs out first. The machine could carry
   15+ channels; the reviewer cannot.
3. The 1TB internal disk becomes the binding constraint past roughly eight
   channels unless intermediates are cleaned on a retention window.
4. From 2027-02-01 a channel must hold 10M qualified Shorts views per 90 days
   to keep Shorts pool payments, so N Shorts channels imply an aggregate view
   requirement that grows linearly while attention does not.

It also gives a four-stage revenue sensitivity table built from assumed RPMs,
explicitly not a forecast.

## Decision

Add one stdlib module, `stigdev/capacity.py`, holding the month-scale
computation that the existing gates consume. It stores nothing, measures
nothing, and takes every input from the caller.

### Records

| Record | Meaning |
|---|---|
| `ArtifactCost` | GPU hours, review hours, working GB, archive GB for one finished artifact |
| `ChannelDemand` | one channel's planned monthly output per format (`long`/`short`, reusing `portfolio.FORMATS`) |
| `CapacityBudget` | one month of headroom on one node with one operator behind it |

`PLANNING_COSTS` ships `short` and `long` entries. They are the capacity
analysis's planning assumptions, **not measurements**, and carry the same
warning as the ADR 0012 resource classes: replace each the first time a real
render is profiled.

### Functions

- `budget_from(profile, utilization, operator_review_hours_per_week, disk_gb,
  retention_days, working_share)`: derives a month from a `NodeProfile`.
  GPU hours are `24 x 30 x utilization` (504 at 70%). Review hours convert the
  operator's week to a month. The memory ceiling takes the **tighter** of the
  node's reserve-based usable memory and the utilisation share, because the two
  disagree (see conflict 1).
- `artifact_counts`, `review_hours_per_week`: the plan's demands, the latter
  shaped to feed `portfolio.PortfolioEvidence` directly.
- `capacity_report`: used / available / deficit for GPU hours, review hours,
  and the working set, plus artifact counts and monthly archive growth. The
  working set is `working_gb x retention_days / 30`, so the retention window
  is what decides whether the disk holds.
- `capacity_gate`: fail-closed `GateDecision` listing every exhausted resource
  at once. This is what `capacity_available` should mean.
- `months_until_archive_full`: archive headroom divided by monthly growth;
  `None` when nothing is being archived. Answers "when do I need the NAS".
- `shorts_pool_floor(projected_views, snapshot, at)`: reads the threshold and
  effective date out of a `revenue.PolicySnapshot` rather than hardcoding
  them, names the channels below the floor, and reports the aggregate monthly
  view requirement. Returns `long_form_revenue_at_risk: False` because missing
  the Shorts floor stops pool payments only.
- `project_revenue(channel_id, views, rpm_usd, usd_krw, occurred_at)`: the
  sensitivity calculation, emitted as `portfolio.RevenueEvent` rows of kind
  `estimated`. ADR 0009 already bars `estimated` from `gross_revenue`, so a
  projection is **structurally** unable to be counted as money. `WATCH_PAGE_SHARE`
  (0.55) and `SHORTS_POOL_SHARE` (0.45) are recorded as documentation; RPM
  inputs are already creator-side, so applying them again would double-count.

### What the model says, once the shipped costs are used

The acceptance tests pin these, so a future cost change that breaks the
analysis's conclusions fails loudly:

- A 10-channel plan lands inside the stated envelope: 120–180 Shorts, 12–24
  long-form, 60–100 review hours per month.
- At 12 channels the GPU still has headroom — the machine is not the
  constraint — while review hours are over the 15 h/week cap.
- 12 channels fit only once the operator buys more review capacity (20
  h/week), which is the honest form of "12 is a hard cap, not a target".
- A 14-day cleanup keeps the working set on the internal disk; keeping 30 days
  does not.

## Conflicts recorded, not resolved (AGENTS.md)

1. **Memory ceiling.** ADR 0012 reserves 20GB of 96 (76GB usable); the
   capacity analysis caps media work at 70% (67.2GB). Implemented as the
   minimum of the two, so planning fails closed. Neither source was edited.
2. **Channel count lives in two places.** `PortfolioPolicy.max_active = 12`
   (ADR 0010) caps the count; this module caps the resources. They agree today
   at 12 by coincidence of the same analysis, not by construction. A future
   `max_active` change will not move the resource ceiling.
3. **The analysis's "절대 상한 15" is not encoded.** At 15 channels the model
   shows GPU headroom and a review overrun, which is the same failure as 12;
   an extra hard number would add nothing a gate can act on.
4. **Music release derivatives** appear in the analysis's monthly envelope but
   `portfolio.FORMATS` has only `long` and `short`. Their cost is not modelled;
   adding a format is a `portfolio` change, not a capacity one.
5. **Revenue ranges are not encoded.** The analysis's 월 500만–2,500만원 bands
   are outcomes of assumed RPMs, so only the arithmetic is implemented; the
   bands themselves would be a forecast this repository must not assert.

## Failure behavior

Invalid records raise `CapacityError` at construction. `capacity_gate` and
`capacity_report` raise when a plan demands a format with no cost entry rather
than silently costing it at zero. `project_revenue` refuses a format with no
RPM assumption. `shorts_pool_floor` refuses a policy snapshot for a different
feature or without the threshold metric.

## Observability

None added. Every function returns a plain value; a private control plane
records the decisions as events.

## Acceptance tests

`tests/test_capacity.py` (33 cases): record validation and round-trips, the
504-hour derivation, the tighter memory ceiling, the 10-channel envelope, GPU
headroom at 12 channels, review hours as the first constraint, all deficits
reported at once, the derived weekly review figure rejected by
`portfolio.register_channel`, retention deciding the working set, archive
runway, the Shorts floor before and after its effective date, long-form
revenue never at risk from it, the four sensitivity stages reproduced to the
won, and a projection refused by `gross_revenue`.

## Deferred

Per-queue modelling (LLM / image / TTS-render as separate budgets rather than
one GPU pool), calendar and slot-level scheduling, wiring `capacity_gate` into
`lifecycle.ScaleEvidence.capacity_available`, measured artifact costs to
replace `PLANNING_COSTS`, external storage tiering, and any YouTube Analytics
connector to supply real projected views.
