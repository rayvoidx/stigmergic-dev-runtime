# Paper outline (working draft with evidence status)

Last reconciled: 2026-09-09.

**Proposed title:** Persistent Projects, Ephemeral Agents: Evaluator-Gated
Stigmergic Coordination for Continuous Software Evolution

**Venue shape:** systems-for-ML / agents workshop paper first; extend only
after cross-task, adequately powered results.

## Scope boundary

The paper contribution is the public research runtime, TrendEvoBench, the
controlled coordination conditions, and their evidence. The proposed Agentic
Engineering OS architecture is future systems work and operational context;
it is not an implemented contribution and must not be used to inflate the
paper's empirical scope.

## Abstract skeleton

Context: continuous software evolution is difficult for agents (cite
SWE-Milestone with the hedges preserved in `related_work.md`). Mechanism: a
runtime where finite-lived workers coordinate through versioned executable
artifacts, lineage, evaluator evidence, and failure records behind a strict
promotion gate. Contributions: (C1) an open, replayable research runtime and
two-tier synthetic benchmark; (C2) a matched-budget experimental framework
with three implemented coordination conditions and two fail-closed planned
conditions; (C3) exploratory cross-model and replacement evidence; (C4) a
registered, partially confirmatory capability × coordination-medium
interaction on one task/model pair. Conclusion must say that persistent
identity is not uniformly beneficial or harmful; the observed value changes
with worker capability in this setup.

## Claimed contributions

1. **Runtime + benchmark (implemented):** `stigdev` — content-addressed
   artifacts, append-only events, versioned evaluator and policy, promotion
   gate, replay/recovery; TrendEvoBench v1 mechanism tier and v2 discrimination
   tier with deterministic calibration probes.
2. **Experimental framework (partially implemented):** five matched-budget
   condition configs; `artifact_only`, `single_persistent`, and `best_of_n`
   runners; replacement and failure-memory controls; matrix runner; pinned
   manifests. `full_communication` and `orchestrator` remain config-only.
3. **Evidence with explicit tiers:**
   - mechanism demonstrations for promotion/rejection, replay/recovery, and
     worker/provider replacement;
   - exploratory two-model n=5 pilots, medium ablations, and gpt-oss n=20
     extension;
   - registered, partially confirmatory H5 2×2: interaction +0.202, bootstrap
     95% CI [0.093, 0.310], 80/80 runs recorded as replay-clean.

Do not claim that `artifact_only` generally outperforms persistence. The weak
model favors `single_persistent`; the strong model has no statistically
detected difference in the exploratory test. Equivalence was not established.

## Evidence ledger for the results section

| Question | Current evidence | Allowed statement | Missing for a stronger claim |
|---|---|---|---|
| RQ1/H1 | Three-condition n=5 pilots on gemma3 and gpt-oss; gpt-oss n=20 only for AO/SP. | Exploratory ordering is model-dependent; best-of-N was last in both n=5 pilots. | Confirmatory powered design, complete chosen arms, preferably second task family. |
| RQ2/H2 | None: `full_communication` is not implemented. | No result. | Logged message condition and matched communication-cost study. |
| RQ3/H3 | Deterministic failure-memory mechanism plus n=5 medium-content ablations. | Failure records can change repeats in the reference worker; raw failed source hurt gemma3 in an exploratory ablation. | Pre-registered live-model memory ablation with exploration/regression metrics. |
| RQ4/H4 | Offline regression tests and one-seed gemma3 replacement pairs. | Artifact state survives replacement mechanically; n=1 live behavior is a demonstration. | Powered, multi-provider replacement study including input-source failure. |
| RQ5/H5 | 2 models × 2 conditions × 20 seeds; registered after n=5 pilot and before extension; only gemma3 extension fully novel. | Registered interaction direction supported on this benchmark/model pair. | Third capability level and/or second task, runtime-version deconfounding, pre-registered equivalence test at strong end. |

## H5 result to report

Holdout mean [bootstrap 95% CI], n=20 per cell:

| Worker | `artifact_only` | `single_persistent` |
|---|---|---|
| gemma3:12b (weaker) | 0.494 [0.425, 0.567], sd 0.164 | **0.664** [0.595, 0.730], sd 0.157 |
| gpt-oss:20b (stronger) | **0.799** [0.776, 0.819], sd 0.049 | 0.767 [0.727, 0.800], sd 0.090 |

Interaction `(AO − SP)_strong − (AO − SP)_weak`: +0.202, bootstrap
95% CI [0.093, 0.310], 10k resamples. Source:
`docs/experiments/data/h5-2x2-n20.json`.

Registration and validity caveats must appear adjacent to the result:

- H5 followed the gpt-oss n=5 pilot;
- only the gemma3 seeds 46–60 extension was fully novel;
- model and Ollama version are confounded across capability levels;
- one toy benchmark and two models operationalize capability;
- strong-end parity is not a pre-registered equivalence result;
- lower observed dispersion under `artifact_only` is exploratory (SD 0.0493
  versus 0.090 for `single_persistent`); it is not a registered variance test.

## Sections

1. Introduction — thesis and RQ1–5; clearly distinguish H5 from the earlier
   protocol hypotheses.
2. Related work — use `related_work.md`; keep abstract-level verification and
   all hedges.
3. Runtime design — observe/propose/evaluate/gate, store, replay/recovery, and
   current replay/sandbox limits.
4. TrendEvoBench — v1 mechanism tier, v2 discrimination tier, calibration,
   train/holdout threats.
5. Experimental setup — condition semantics, matched budgets, providers,
   registration timeline, exclusions, and analysis plan.
6. Results — mechanism demonstrations; n=5 exploratory pilots/ablations;
   exploratory gpt-oss n=20; H5 2×2 as partially confirmatory.
7. Discussion — selective persistent media, capability interaction, negative
   ablation, alternative explanations.
8. Threats and limitations — task/model/runtime confounds, incomplete
   conditions, no formal equivalence, post-response token cap, sandbox,
   one-artifact state.
9. Future work — H1–H4 confirmatory studies, H5 replication, second task
   family. Mention the Agentic Engineering OS only as an unimplemented systems
   direction.

## Figures and tables

- Fig 1: runtime loop — exists in README.
- Fig 2: current run-store layout and event lifecycle — derive from committed
  run directories; label the event schema as current v1.
- Fig 3: lineage graph of an archived live-model run — source exists.
- Table 1: five-condition matrix with implementation status and matched budget
  fields — configs exist.
- Table 2: exploratory n=5 two-model results — data exists; label
  underpowered.
- Table 3: H5 2×2 cells and interaction — data exists.
- Fig 4: H5 interaction plot with per-seed points — to render from committed
  data.
- Table 4: RQ4 replacement outcomes — mechanism demonstration only.
- Future: RQ2 communication-cost figure and confirmatory H1–H4 tables.

## Blanks that block submission-level claims

- Complete condition 4 and 5 implementations before five-condition claims.
- Pre-register and run a second task family or third capability level for H5
  replication.
- Define a formal equivalence margin before claiming strong-worker parity.
- Run powered H1–H4 studies; the existing records do not confirm them.
- Deconfound model from serving/runtime version where feasible.
- Close or disclose full-evidence replay and budget-enforcement gaps.
- Re-verify all primary-source related-work claims at full-paper level before
  final citation text.
