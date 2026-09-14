# Lab note: local pilot matrices on fixtures v2 (2026-08-30)

> Later same day, the full matrix was replicated on a stronger open-weights
> model (gpt-oss:20b) and the condition ordering did not replicate — see the
> final section. Read the gemma3 sections below with that in mind.

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

## Second ablation: attempt-level context in the medium BACKFIRED

`observe_failure_sources: true` (medium carries the actual truncated source
of the last 3 rejected candidates; artifact_only x seeds 41–45, same setup;
data: `docs/experiments/data/ablation-attemptlevel-matrix.json`, 14.3 min,
$0): **all five seeds floor-stuck** — 0 promotions in 25 proposals
(quintuple-zero), holdout pinned at 0.37, tokens +60% vs baseline.

The ablation ladder now reads (holdout mean, n=5 each):

| medium contents (artifact_only) | holdout |
|---|---|
| failure summaries only (baseline) | 0.528 |
| + promotion tuples | 0.498 |
| + failed-attempt source code | **0.370 (all stuck)** |
| private full trajectory (single_persistent) | 0.646 |

Tentative mechanism (hypothesis, not established): failed code in the
observation dominates the 12B model's prompt and pulls it into
imitate-and-patch loops on known-bad artifacts — structurally the same
self-repair trap the persistent worker showed on v1. If it holds, it cuts
against a naive "richer medium is better" reading of stigmergy and suggests
the medium's *selectivity* (canonical + outcome summaries, not raw failed
code) is a feature, while the persistent advantage — if it is real at all at
this n — comes from narrative continuity of the worker's *own* context
rather than from any information the medium could carry. Testable next on a
stronger model and more seeds.

## Cross-model replication: gpt-oss:20b reverses the ordering

Same matrix (3 conditions x seeds 41–45, identical budgets/config except
`model_id: gpt-oss:20b`, max_tokens 800k for reasoning tokens) on Ollama
0.33.2 (standalone binary, port 11500; the 12-month-old local gpt-oss blob
was corrupt — "tensor size overflow" — and was re-pulled). Data:
`docs/experiments/data/pilot-v2-gptoss-matrix.json` (merged from an
interrupted 10-run matrix + a 5-run resume, identical config; all 15 runs
replay with 0 divergences). ~$0, local.

| condition | holdout mean [95% CI] | train mean | promoted/run |
|---|---|---|---|
| artifact_only | **0.804** [0.760, 0.840] | 0.800 | 2.2 |
| single_persistent | 0.786 [0.734, 0.832] | 0.728 | 2.2 |
| best_of_n (3x2) | 0.674 [0.594, 0.754] | 0.576 | 2.8 |

Honest reading:

1. **The gemma3 ordering did not replicate.** With a stronger worker,
   artifact_only edges ahead of single_persistent (CIs overlap — call them
   indistinguishable, not a win). The pilot's H1-opposite signal is
   model-dependent, not a property of the conditions.
2. **best_of_n is last on both models** — the budget-split cost is the one
   pattern that has now replicated across two models (and offline).
3. **Capability interacts with coordination**: gpt-oss:20b escaped the floor
   in 15/15 runs and repeatedly beat the v1-gene plateau (best train 0.91 vs
   calibration probe ceiling 0.97); gemma3:12b escaped in 8/15. Weak workers
   may lean on private narrative continuity; strong workers seem to exploit
   the selective medium at least as well — a hypothesis worth pre-registering
   properly, not a conclusion.
4. Still n=5 per cell, one benchmark, two models. Paper-tier inference rules
   remain unmet by design.

## Seed extension to n=20 (2026-08-31, gpt-oss:20b, exploratory)

Seeds 41–60 for the two head conditions (best_of_n dropped — its budget-split
penalty had already replicated three times; decided before running). Executed
in chunks after repeated background-task terminations; identical config
throughout; **all 40 runs replay with 0 divergences**. Data:
`docs/experiments/data/pilot-v2-gptoss-n20-matrix.json`. Registered H5 was
committed before these data were seen (commit 6327f7b).

| condition | holdout mean [95% CI] | sd | train mean | promoted/run | n |
|---|---|---|---|---|---|
| artifact_only | 0.7985 [0.776, 0.819] | **0.049** | 0.783 | 2.15 | 20 |
| single_persistent | 0.767 [0.727, 0.800] | 0.090 | 0.718 | 1.90 | 20 |

Exploratory Mann-Whitney U on holdout: U=171.5, p≈0.44 (two-sided, normal
approximation) — **no detectable difference at n=20**.

Honest reading:

1. On a strong open-weights worker, ephemeral stigmergic workers are
   statistically indistinguishable from a persistent-context agent at
   matched budgets, with the point estimate slightly favoring
   artifact_only. For the core thesis ("persistent conversational identity
   is not required"), indistinguishability is the load-bearing observation
   — though formal equivalence would need a pre-registered TOST-style
   bound, which this exploratory extension does not provide.
2. **Variance halved under the stigmergic medium** (sd 0.049 vs 0.090;
   single_persistent's worst seeds sink much lower). Consistent with the
   selective medium acting as a stabilizer — unregistered observation,
   hypothesis fodder only.
3. This extension is exploratory (chunked execution, one model, one
   benchmark); the pre-registered H5 interaction test still requires the
   full 2x2 with a weaker model at n>=20 per cell.

**Later status (2026-09-06):** that 2×2 was completed. The registered,
partially confirmatory result and its caveats are recorded in
`docs/experiments/2026-09-06-h5-2x2.md`; do not read the “still requires” line
above as current project state.
