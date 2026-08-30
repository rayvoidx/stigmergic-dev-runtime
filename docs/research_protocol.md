# Research protocol

Status: pre-registration draft. No experiment in this protocol has been run.
The harness implements the mechanisms; results sections are intentionally
empty until runs exist.

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

## Variables

- **Independent:** condition (5 levels below); failure-memory toggle (RQ3);
  replacement schedule (RQ4).
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
2. `best_of_n` — N independent agents, no shared artifacts; best final
   artifact scored.
3. `artifact_only` — ephemeral workers; shared canonical artifacts, lineage,
   evidence, failure records; no messages. **(implemented)**
4. `full_communication` — condition 3 plus a logged inter-worker message
   channel.
5. `orchestrator` — central planner delegating to workers, all delegation
   logged.

Implementation status: only condition 3 runs today; 1 and 2 are the next
milestone (see PROJECT_STATE.md). Configs for all five exist with identical
budget blocks and are schema-tested.

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
| pilot | variance + harness shakeout | 5 x 5 | one small live model | bounded by per-run max_usd; estimate before launch, requires explicit user approval |
| paper | pre-registered comparisons | 5 x >= 20 (+ RQ3/RQ4 ablations) | >= 2 providers (replacement for RQ4) | budgeted from pilot actuals; requires explicit approval |

All live tiers must set non-zero `max_tokens`/`max_usd` budgets; the runtime
stops runs that exceed them and records the stop as `budget_exhausted`.

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
