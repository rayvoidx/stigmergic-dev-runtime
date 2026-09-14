# Research protocol

Status: evolving protocol with preserved registration history. H1–H4 remain
unconfirmed; their mechanism demonstrations and exploratory pilots have run.
H5 was added on 2026-08-31 after the gpt-oss n=5 pilot, then tested in a
registered, partially confirmatory 2×2 completed on 2026-09-06. Results live in
separate lab notes/data and are summarized below; this file must not be edited
retroactively to make earlier hypotheses fit observed outcomes.

## Research questions and hypotheses

- **RQ1 / H1.** At matched budgets, `artifact_only` outperforms
  `single_persistent` and `best_of_n` on milestone success.
- **RQ2 / H2.** Removing direct communication (`artifact_only` vs
  `full_communication`) retains most performance at lower token cost.
- **RQ3 / H3.** Inheriting failure records reduces repeated-failure rate and
  regressions without reducing exploration (distinct mutations attempted).
  Mechanism toggle: `provider.use_failure_memory`.
- **RQ4 / H4.** Mid-run worker/provider replacement degrades `artifact_only`
  less than `single_persistent`.
- **RQ5 / H5** (added 2026-08-31, motivated by the 2026-08-30 pilots —
  registered BEFORE any n>=20 or multi-model confirmatory run): worker
  capability interacts with the coordination medium. Prediction: the
  advantage of `artifact_only` over `single_persistent` increases with
  worker capability (weak workers lean on private narrative continuity;
  strong workers exploit the selective medium at least as well). Test: 2x2
  (model in {weaker, stronger} x condition in {artifact_only,
  single_persistent}) at matched budgets, interaction contrast on holdout
  score, same bootstrap/Holm machinery as H1–H4. Ancillary registered
  observation: exposing failed-attempt *source code* in the medium is
  predicted to hurt, not help (2026-08-30 ablation: 0/25 promotions) —
  medium selectivity treated as a feature.

## Experiment status as of 2026-09-09

| Tier | Completed record | Classification |
|---|---|---|
| Offline and one-seed live runs | v1 condition and RQ4 replacement archives; first v2 run | Mechanism demonstrations only |
| Pilots | gemma3 and gpt-oss, three implemented conditions × five seeds | Exploratory; all relevant n=5 comparisons underpowered |
| Medium ablations | promotion-history and failed-source exposure, n=5 | Exploratory; failed-source exposure produced 0/25 promotions |
| Seed extension | gpt-oss AO/SP, n=20 per arm | Exploratory; no formal equivalence test |
| H5 2×2 | two models × AO/SP × 20 seeds = 80 runs | Registered, partially confirmatory; interaction +0.202, bootstrap 95% CI [0.093, 0.310] |

H5 caveats are part of the result: registration followed the gpt-oss n=5
pilot; only the gemma3 extension arm was fully novel; model is confounded with
Ollama version; and the design uses one task family and two capability levels.
See `docs/experiments/2026-09-06-h5-2x2.md`.

## Variables

- **Independent:** condition (5 levels below); failure-memory toggle (RQ3:
  `provider.use_failure_memory`); replacement schedule (RQ4:
  `replace_at_episode` wipes a persistent worker's private memory and/or
  swaps in `replacement_provider`; logged as `worker_replaced` /
  `provider_replaced` events). The repeated-failure metric is always computed
  against the store (objective), while the worker's observation stays
  condition-scoped.
- **Dependent:** metrics below.
- **Controlled (matched across arms, pinned in every manifest):** exact model
  id (never a moving alias), effort/temperature/max output, prompt template
  hash, tool inventory, max episodes, max provider calls, max tokens, max USD,
  max wall-clock, seeds, fixture version + hashes, evaluator version, policy
  version, software environment, initial artifact hash.
- **Excluded from all arms:** Claude Agent Teams or any opaque provider-side
  multi-agent feature; unlogged fallbacks. The construction tool used to build
  this repo and the experimental agent are different variables and are
  recorded separately.

## Conditions

1. `single_persistent` — one agent, persistent context, sequential episodes.
   **(implemented)**
2. `best_of_n` — N independent agents, no shared artifacts; best final
   artifact scored. **(implemented)**
3. `artifact_only` — ephemeral workers; shared canonical artifacts, lineage,
   evidence, failure records; no messages. **(implemented)**
4. `full_communication` — condition 3 plus a logged inter-worker message
   channel.
5. `orchestrator` — central planner delegating to workers, all delegation
   logged.

Implementation status: conditions 1, 2, and 3 run today (4 and 5 are
config-only). Configs for all five exist with identical budget blocks and are
schema-tested. Note: with one sequential worker and no replacement, condition
1 and condition 3 are informationally equivalent by construction and produce
identical offline results; they separate under worker replacement (RQ4),
parallel workers, and live context limits — comparisons between them are only
meaningful in those regimes.

## Metrics

Primary:
- Milestone/task success: composite score on train; final holdout score.
- Retention: previously passed hard checks / capabilities still passing at end.
- Regression rate: promoted candidates that lower holdout score.
- Repeated-failure rate: proposals matching a recorded failure (hash or
  mutation id) / total proposals.

Secondary:
- Accepted-candidate ratio; lineage depth; artifact reuse breadth (distinct
  parents referenced); time/episodes to first accepted improvement; recovery
  after injected worker/provider/input failure (RQ4); cost (tokens, USD,
  calls, wall-clock latency).

Trend-domain (from evaluator): precision@k, unique duplicate-group rate;
future fixture versions may add citation/evidence precision and lead time.

## Statistical plan

- Unit of analysis: one run (seed). Report per-condition means with 95%
  bootstrap CIs (10k resamples); pairwise comparisons via Mann-Whitney U with
  Holm correction across the pre-registered hypothesis family.
- **Four seeds are not conclusive and will not be reported as findings.**
  Pilot tier estimates variance; paper-tier n per arm is chosen from the pilot
  so that the minimal effect of interest (0.05 composite-score difference)
  has >= 0.8 power at alpha 0.05; floor of n >= 20 seeds per arm.
- Deterministic offline runs have zero variance across repeats by design;
  comparative claims therefore require live-model providers, where seeds vary
  prompts/sampling. Offline results are mechanism demonstrations only.

## Budget tiers

| Tier | Purpose | Arms x seeds | Provider | Est. cost |
|---|---|---|---|---|
| smoke | CI / mechanism checks | 1 x 1 (offline) | offline deterministic | $0 |
| pilot | variance + harness shakeout | planned 5 x 5; completed pilots cover 3 implemented conditions x 5 | small live local models | $0 local; any paid launch requires estimate and explicit approval |
| paper | pre-registered comparisons | 5 x >= 20 (+ RQ3/RQ4 ablations) | >= 2 providers (replacement for RQ4) | budgeted from pilot actuals; requires explicit approval |

All live tiers must set a positive `max_tokens`. A zero-cost local provider may
set `max_usd` to 0; a paid provider must set a positive USD limit and must not
be added until USD reservation/enforcement exists. Current runtime behavior is
more limited than the intended protocol: calls and wall time are checked before
an episode, tokens are checked after a provider response (so one-call overshoot
is possible), and `max_usd` is recorded but not enforced. These limits must be
reported for existing runs and fixed before paid experiments.

## Threats to validity

- **Construct:** TrendEvoBench is a toy; composite score may not reflect
  useful software capability. Mitigation: harder fixture versions and a second
  task family before paper claims.
- **Internal:** train-set gating can overfit; holdout is measured but small.
  Prompt templates could accidentally differ across arms — template hash is
  logged and must be identical.
- **External:** results with one model family may not generalize; RQ4 requires
  at least two providers.
- **Ecological:** offline provider's fixed mutation space cannot exhibit
  model-driven exploration; never analyzed as if it could.
