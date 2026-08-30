# Lab note: local pilot matrix on fixtures v2 (2026-08-30)

**Status: underpowered pilot (n=5 seeds/arm, one 12B local model, toy
benchmark). All CIs overlap; nothing here confirms or refutes H1–H4.**
Recorded in full because the point estimate ordering is *opposite* to H1's
prediction and burying that would be exactly the kind of result-shaping this
project exists to avoid.

## Setup

`stigdev matrix` — 3 implemented conditions x seeds {41..45}, matched budgets
(6 episodes, gemma3:12b via Ollama, temperature 0.7 for across-seed sampling
variance, num_ctx 8192, fixtures v2, $0 cost, 34.3 min wall on an M4 Pro).
Base config: `configs/experiments/pilot-v2-gemma3.json`. Full per-run data:
`docs/experiments/data/pilot-v2-gemma3-matrix.json` (run directories remain
local; every run is individually replayable).

## Aggregates (mean [bootstrap 95% CI], n=5)

| condition | holdout | train | promoted/run | floor-stuck seeds |
|---|---|---|---|---|
| single_persistent | **0.646** [0.504, 0.774] | 0.562 | 1.2 | 1/5 |
| artifact_only | 0.528 [0.370, 0.700] | 0.456 | 0.6 | 3/5 |
| best_of_n (3x2) | 0.454 [0.370, 0.538] | 0.384 | 0.4 | 3/5 |

## Honest reading

1. **Direction is against H1 in this setup**: the persistent worker escaped
   the v2 floor most often (4/5 seeds) and reached the highest scores;
   artifact_only was bimodal (3 seeds stuck at 0.30, 2 seeds reaching
   0.73–0.80); best_of_n escaped shallowly (budget split, consistent with the
   offline demo).
2. **Not evidence**: n=5, all CIs overlap heavily, single model, single
   benchmark, and the protocol's inference rules (power floor n>=20) are
   deliberately not met. This is what pilots are for.
3. **Design confound worth fixing before believing anything**: the
   single_persistent observation carries `own_history` (its full trajectory
   including promotions), while the artifact_only observation exposes only
   canonical + *failure* records. At temperature 0.7 the richer private
   context may simply be better prompting, not better coordination. The
   stigmergic medium currently transmits failures but not successful-attempt
   context beyond the canonical artifact itself — an asymmetry we introduced,
   not one inherent to the thesis.

## Follow-ups this pilot motivates

- Ablation: add recent *promotion* history to the artifact_only observation
  (richer medium) and rerun the same matrix — isolates "information richness"
  from "information source". **Done same day; see below.**
- Stronger worker model (paid adapter, needs approval; or a larger local
  model) — gemma3:12b fails to realize known-reachable rungs (calibration
  ceiling 0.97, best observed 0.83).
- More seeds per the protocol before any comparative language.

## Ablation result: richer medium did NOT close the gap

`observe_promotion_history: true` (artifact_only x seeds 41–45, otherwise
identical setup; data: `docs/experiments/data/ablation-richmedium-matrix.json`,
12.1 min, $0):

| variant | holdout mean [95% CI] | promoted/run | floor-stuck |
|---|---|---|---|
| artifact_only + promotion history | 0.498 [0.370, 0.670] | 0.4 | 3/5 |
| artifact_only baseline | 0.528 [0.370, 0.700] | 0.6 | 3/5 |
| single_persistent baseline | 0.646 [0.504, 0.774] | 1.2 | 1/5 |

Exposing what-worked summaries (mutation, score, generation) did not move
artifact_only toward single_persistent — the difference is
indistinguishable from noise at n=5, and certainly not a closure. The
"information richness" explanation in its simplest form is **weakened**.
Remaining candidates, untested: (a) pure noise — every CI here overlaps;
(b) the persistent worker's advantage lives in *attempt-level context*
(its own prior source code and reasoning traces, not summary tuples);
(c) an interaction with temperature-0.7 sampling. Next discriminating step
is more seeds and/or a stronger worker model; summary-tuple enrichment of
the medium is not it.
