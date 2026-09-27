# Project state

Durable state + decision log. A fresh agent should be able to resume from this
file alone. Update it at every milestone.

Last updated: 2026-09-27 (media portfolio, concept lineage/Truth Firewall,
revenue intelligence, model radar and portfolio policy contracts; ADR
0007/0008/0009/0010 proposed, uncommitted on `main`).

Published repository: https://github.com/rayvoidx/stigmergic-dev-runtime.

## Where things stand

The research runtime is **implemented and verified locally**:

- `stigdev` package (stdlib-only, Python >= 3.12): run store (content-addressed
  artifacts, append-only events.jsonl, canonical pointer, manifest), subprocess
  sandbox, TrendEvoBench evaluator v1, strict-improvement promotion policy v1,
  ephemeral worker episodes, deterministic offline provider, run loop with
  explicit budgets, replay/recover, argparse CLI (`demo`, `run`, `evaluate`,
  `replay`, `recover`, `lineage`).
- TrendEvoBench fixtures v1 (mechanism tier) and v2 (discrimination tier),
  synthetic and committed with a seeded generator and calibration probes.
- 135 pytest tests passing: 55 existing tests plus 80 execution-contract tests.
  Existing unit + e2e coverage includes promotion, rejection, lineage,
  replay, recovery, bit-for-bit reproducibility, condition configs, matrix
  runner, v2 calibration, RQ4 replacement, and observation ablations.
- Committed deterministic and local-model examples in `examples/`.
- Five matched-budget condition configs. `artifact_only`,
  `single_persistent`, and `best_of_n` are implemented;
  `full_communication` and `orchestrator` raise
  `ConditionNotImplementedError` with no silent fallback.
- A conditions × seeds matrix runner and committed live-model evidence:
  two 3×5 pilots, two n=5 medium ablations, an exploratory gpt-oss n=20
  extension, and the registered/partially-confirmatory H5 2×2 (80 runs).
- Agentic Engineering OS design baseline merged in PR #1 (`5867f67`).
  Typed `AgentExecutor`/`WorkspaceBackend`, deterministic fakes, and opt-in
  RunStore execution evidence are implemented and verified offline.
  No production executor/backend, scheduler, gateway, or control
  plane exists. See `docs/execution_contracts.md`.

## Verification commands (stage 2, 2026-09-14)

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest                     # 331 passed (135 + 196 media/revenue/model contracts, 2026-09-27)
.venv/bin/stigdev demo --runs-root runs        # seed42: 3 promoted, 5 rejected, 0.55->0.86
.venv/bin/stigdev replay examples/sample_run   # ok: true, checked: 9
```

All 10 committed example stores replayed successfully (56 evaluations).
The runnable example in `docs/execution_contracts.md` also passed. Tests and
replay require no live agent, model endpoint, private asset, or paid API.

Expected seed-42 demo invariants (tests assert these): promoted=3, rejected=5,
repeated_failure_attempts=2, lineage_depth=3, train 0.55->0.86, holdout
0.52->0.86, cost all zeros.

## Decision log

1. **Stdlib-only Python, dataclasses, no frameworks.** Reviewability and
   reproducibility over sophistication; nothing in the MVP needs a dependency.
2. **Artifact = whole Python module, content-addressed by sha256.** Immutable
   files + append-only events give auditability and cheap replay.
3. **Canonical state = one JSON pointer file, recoverable from the event log.**
   The event log is the source of truth; `recover` rebuilds the pointer.
4. **Sandbox = subprocess `-I` + timeout + temp cwd, documented as NOT a
   security boundary.** Honest MVP; fail-closed on any malformed output.
5. **Offline provider = deterministic gene-toggling reference worker.** Same
   python-fence output contract a live LLM adapter must satisfy. Genes are
   the provider's strategy only; runtime treats artifacts as opaque.
6. **Evaluator metrics contain no timings** — replay compares them, so they
   must be deterministic (bug found and fixed in build session).
7. **RunStore roots resolve to absolute paths** — artifact paths cross the
   sandbox cwd boundary (bug found via CLI with relative path, fixed, root
   cause: sandbox runs in its own temp cwd).
8. **Unimplemented conditions refuse to run** rather than silently falling
   back; construction tooling (this session) is not experimental evidence.
9. **Fixture truth fields (`relevant`, `dup_group`) are evaluator-only**; the
   runtime strips them before artifacts see items.
10. **Literature claims verified against arXiv abstracts** before entering
    `docs/related_work.md`; nuances recorded there (e.g. post-deletion
    continuation belongs to EvoX Genesis, not SwarmWorld).
11. **Local Ollama adapter added (`OllamaProvider`)**, wired via
    `provider.provider = "ollama"`; unit-tested with mocked transport, never
    live in tests. Worker prompt asks live models for stdlib-only modules and
    a `# stigdev-mutation:` marker. Note: `gpt-oss:20b` fails on Ollama
    0.31.2 ("tensor size overflow"); `gemma3:12b` works (31 tok/s, 100% Metal
    GPU). First live run committed as `examples/live_run_gemma3_12b/`:
    1 promoted (recency_weighting, train 0.55->0.66, holdout 0.63), 5
    rejected, 6,616 tokens, $0, replay clean.
12. **single_persistent + best_of_n implemented** (2026-08-30).
    single_persistent = private full-trajectory memory (`own_history` in the
    observation), never reads store failure records; with one sequential
    worker it is informationally equivalent to artifact_only and offline
    results are identical by construction (tested). best_of_n = n_workers
    fully isolated sub-stores under `<run>/workers/w<i>`, per-worker budget =
    total/n, seeds seed+i, winner copied into the parent store as a logged
    `promoted` event (parent and each worker dir replay clean). Offline
    matched-budget demo (8 eps, seed 42): artifact_only=single 0.86/0.86,
    best_of_n(4x2) 0.84/0.74.
13. **First live 3-condition comparison archived** (gemma3:12b, 6 eps, seed
    42, $0): artifact_only 0.66/0.63; single_persistent 0/6 promoted (stuck
    in self-repair micro-edits, +54% tokens, canonical preserved by gate);
    best_of_n(3x2) all workers redundantly found the same 0.66 improvement.
    n=1 anecdote — lab note at
    `docs/experiments/2026-08-30-local-3condition-comparison.md`.
14. **RQ4 replacement harness implemented** (2026-08-30):
    `replace_at_episode` (worker replacement; wipes persistent private
    memory, logs `worker_replaced` with lost-entry count) and
    `replacement_provider` (provider swap, logs `provider_replaced`).
    Repeated-failure metric now always computed against the store (objective)
    regardless of condition-scoped observations. Offline regression tests
    lock in: persistent memory wipe -> immediate repeat of a recorded
    failure; artifact_only replacement -> bit-identical no-op; memoryless
    provider swap -> 0.84 cap vs 0.86 baseline. Live gemma3 pair (repl@3):
    artifact_only reproduced its baseline token-for-token; single_persistent
    successor re-crashed with its predecessor's exact NameError artifact.
    Lab note RQ4 addendum + `examples/live_run_rq4_*` archives.
15. **Fixtures v2 (discrimination tier) shipped** (2026-08-30). Generator
    refactored to versioned dispatch (v1 output verified byte-identical).
    v2 adversarial properties: paraphrase duplicates (prefix dedup gains
    exactly 0), subtle listicle spam carrying no clickbait/target words
    (source reliability is the signal), old-but-relevant items, engagement as
    anti-signal. Calibration locked by tests/test_fixtures_v2.py: seed 0.30
    train, v1-gene plateau 0.69, reference_artifact_v2.py probe 0.97/0.90.
    Calibration table in benchmarks/trendevobench/README.md. First live v2
    run (gemma3:12b, 8 eps): zero promotions, stuck at the 0.30 floor —
    the tier now discriminates (archived: examples/live_run_v2_gemma3/).
16. **Matrix runner + first pilot** (2026-08-30). `stigdev matrix` runs
    conditions x seeds with bootstrap-CI aggregates (offline-tested). Pilot
    3x5 on v2 (gemma3:12b, temp 0.7, $0, 34 min): holdout means
    single_persistent 0.646 > artifact_only 0.528 > best_of_n 0.454, all
    CIs overlapping — direction OPPOSITE to H1, honestly recorded in
    docs/experiments/2026-08-30-pilot-v2-gemma3.md with a named confound
    (medium carries failures only; persistent worker sees full trajectory
    incl. promotions). Next: observation-richness ablation.
17. **Richness ablation ran same day** (`observe_promotion_history` flag,
    default off, tested): artifact_only + promotion history holdout 0.498
    [0.37, 0.67] vs baseline 0.528 — gap to single_persistent (0.646) NOT
    closed; summary-tuple enrichment is not the explanation. Remaining
    candidates (untested): noise at n=5; attempt-level context (own prior
    source) as the real persistent advantage; temperature interaction.
18. **Attempt-level ablation backfired** (`observe_failure_sources`,
    default off, tested): exposing failed candidates' source in the medium
    floor-stuck ALL 5 seeds (0/25 promotions, holdout 0.37, +60% tokens).
    Hypothesis (unestablished): failed code dominates the prompt ->
    imitate-and-patch trap; medium selectivity may be a feature. Ablation
    ladder in the lab note. Ollama 0.33.2 standalone runs on port 11500
    (scratchpad binary, app untouched); STIGDEV_OLLAMA_HOST env overrides
    the provider host; gpt-oss:20b blob was corrupt, re-pulled.
19. **Cross-model replication (gpt-oss:20b)**: same 3x5 matrix -> holdout
    artifact_only 0.804 > single_persistent 0.786 (overlapping CIs) >
    best_of_n 0.674. The gemma3 H1-opposite ordering did NOT replicate —
    model-dependent; best_of_n last on both models (only replicated
    pattern). 15/15 runs replay clean; merged data at
    docs/experiments/data/pilot-v2-gptoss-matrix.json. Working hypothesis
    to pre-register: worker capability interacts with coordination medium
    (weak workers lean on private continuity; strong workers exploit the
    selective medium).
20. **n=20 seed extension (gpt-oss:20b, exploratory, 2026-08-31)**: seeds
    41-60, artifact_only vs single_persistent, 40/40 replay clean. Holdout
    0.7985 [0.776,0.819] sd 0.049 vs 0.767 [0.727,0.800] sd 0.090; MWU
    p~0.44 — indistinguishable; variance HALVED under the stigmergic
    medium (unregistered observation). Thesis-relevant reading: persistent
    identity not required to match a persistent agent on this setup. At that
    milestone, the weaker-model n=20 arms still remained for the registered
    RQ5 2x2 and were completed in decision #21.
    Background tasks were killed repeatedly (cause unknown); runs executed
    in 3-run chunks — merged data notes this. Data:
    docs/experiments/data/pilot-v2-gptoss-n20-matrix.json.
21. **H5 2x2 completed (2026-09-06)**: gemma3 arms extended to n=20 (80
    runs total, 80/80 replay clean). Interaction (AO-SP)_strong -
    (AO-SP)_weak = +0.202, bootstrap 95% CI [0.093, 0.310] — registered
    direction supported. Weak model: single_persistent wins outright
    (0.664 vs 0.494, cell CIs disjoint); strong model: parity with halved
    variance. Framing: persistent identity as a capability crutch.
    Registration honesty + confounds in
    docs/experiments/2026-09-06-h5-2x2.md; data in
    docs/experiments/data/h5-2x2-n20.json. Next: third capability level
    and/or second task family before paper claims.
22. **Agentic Engineering OS scope drafted (2026-09-09, design-only).** Keep
    the `stigmergic-dev-runtime` repository and `stigdev` package as the public
    research kernel. Separate `Provider` (model inference) from the proposed
    `AgentExecutor`, `WorkspaceBackend`, `Scheduler`, `PolicyGate`, `RunStore`,
    and `GatewayAdapter` contracts. Do not create a control-plane repository
    until deployment, multi-repo, operational-dependency, or security evidence
    justifies extraction. ADR 0005 remains proposed pending review; no runtime
    or external integration was added.
23. **Design baseline accepted for offline contracts (2026-09-14).** The user
    authorized completing the first-stage baseline and the specified second
    stage. ADR 0005 now accepts both `AgentExecutor` and `WorkspaceBackend`
    contracts/fakes together, with a separate RunStore-backed execution path.
    Actual Git, OpenCode, Codex CLI, Hermes, and Slack integrations remain
    deferred. Verified 55 tests and all 10 committed example stores offline.
    Historical entries 20–21 use “parity”/“halved variance”: the recorded SDs
    are 0.0493 vs 0.090 (variance ratio about 0.30); equivalence was not
    established. No experiment record or numeric result was changed.
24. **Offline execution contracts implemented locally (2026-09-14).** Stage 1
    merged in PR #1 at `5867f67`; stage 2 uses
    `feat/agent-executor-contract`. Added typed executor/workspace protocols,
    deterministic fixtures, additive flat execution-version-1 events, and
    `executions`/`recover-executions` inspection commands. Provider experiments
    and canonical promotion paths remain unchanged. Recovery terminalizes
    unknown outcomes only after the prior writer stops. Full suite: 135 passed;
    all 10 example stores replayed successfully. No external integration added.

25. **Media portfolio contracts implemented offline (2026-09-27, ADR 0007
    proposed, uncommitted).** Executing
    `docs/adr/YouTube_Portfolio_and_RAYV_Strategy_SAEOS_v3_2026-09-27.md` §13
    P0 as the public, generic half: `stigdev/portfolio.py` holds
    `ChannelPlan`, `RightsManifest`, `ReleaseUnit`, `ProfitSnapshot`,
    `FormatHypothesis`, `RevenueEvent` records, the §5.4 stage machine with
    the seven scale conditions and the two-`scale`-channel limit, fail-closed
    `rights_gate`/`release_gate`/`publish_gate`, weekly per-format caps, and a
    revenue ledger that never sums `estimated`/`influenced` into gross.
    54 tests, pure functions, caller-supplied `now`, synthetic fixtures only.
    Operator direction the same day: Signal Stories is mandatory
    (`product_funnel`, tied to the private Social Trend product) and the
    web/app <-> YouTube loop needs a design pass once the operator's detailed
    analysis arrives. Not done: workflow DSL, SQLite tables, RAYV release
    workflow execution, connectors, the private `saeos-*` repositories
    (Blueprint v2 §1) — none exist yet.

26. **v3.1 amendment executed offline (2026-09-27, ADR 0008 proposed,
    uncommitted).** `YouTube_Portfolio_and_RAYV_Strategy_SAEOS_v3_2026-09-27
    (1).md` (v3.1, "Organic Ecosystem Amendment") makes Signal Stories a
    mandatory channel and ties every surface to one `concept_id` behind a
    Truth Firewall. Added `stigdev/ecosystem.py`: `Concept`,
    `EvidenceBundle`, `CanonArtifact`, `PlatformDerivative`,
    `EcosystemEvent` (16 types), `AudienceSignal` (5 groups),
    `AdaptationDecision`; `authorize_event` role firewall, `approve_canon`
    (EvidenceUpdated -> CanonReview -> approval, versions chain),
    `lineage` projection (stale/orphan/closed), `aggregate_signals`,
    `adaptive_priority`, `approve_adaptation`. `stigdev/portfolio.py` gained
    the reversible `pause` stage, `existence_floor` + `time_sensitivity_hours`
    on `ChannelPlan` (mandatory channels cannot retire; `floor_deficit`,
    `sla_breached`), and optional `concept_id` on five records.
    106 media-contract test cases (47 functions); full suite 241; sample replay ok.
    Recorded conflicts (ADR 0008): `pause` missing from the §5.12 diagram,
    §13.1 repo rename vs ADR 0005, HTTP endpoints vs stdlib kernel, two
    untracked strategy copies. Not done: correction-task generation,
    connectors, HTTP API, private `saeos-ops-private`.

27. **v3.2 amendment executed offline (2026-09-27, ADR 0009 proposed,
    uncommitted).** `YouTube_Portfolio_and_RAYV_Strategy_SAEOS_v3_2026-09-27
    (2).md` (v3.2, "Revenue Intelligence Amendment") adds §5.15 and §11.2:
    external revenue claims as graded evidence, policy snapshots with
    effective dates, pre-registered experiments, fifteen commerce events with
    an order state machine, and an isolated Commerce Lab. Added
    `stigdev/revenue.py`: `RevenueClaim` + `classify_claim`/`modeled_amount`
    (grade A–D -> policy_rule/hypothesis/sandbox_only/observe_only; missing
    scope/period/sales interest demotes; only settled grade-A amounts are
    model inputs), `PolicySnapshot` + `policy_in_effect` (new-entrant rules
    never bind existing channels), `ExperimentCard` (registered before
    start, >=2 variants, >=1 guardrail, stop rule), `CommerceEvent` +
    `order_state`/`commerce_ledger` (attributed -> cancelled/returned/
    finalized -> paid; estimated/finalized/paid never summed together),
    role-separated `authorize_commerce_event`, four §11.2 ratios returning
    `None` when undefined, `commerce_lab_promotion_gate` (seven conditions).
    `stigdev/portfolio.py`: `REVENUE_KINDS` now claimed/estimated/attributed/
    finalized/paid/influenced, gross = finalized + paid (attributed excluded),
    `cash_revenue`, view metrics restricted to raw/engaged/qualified with
    `view_policy_era` at 2026-08-24, `commerce_lab` role requiring
    `owner_ref`. 66 new test cases; full suite 307; sample replay ok.
    Recorded conflicts (ADR 0009): attributed revenue in the target mix
    (§7.3/§11.3 vs §11.2), three untracked strategy copies, stored vs derived
    claim decision, UTC boundary for the view-count change, real-video
    fixtures kept private. Not done: Disclosure Gate text detection, Policy
    Watch fetch job, Commerce Lab publish worker, tables, connectors.

28. **Capacity policy and Model Radar gate implemented offline (2026-09-27,
    ADR 0010 proposed, uncommitted).** Operator target restated: a fully
    autonomous 24/7 OS where plans arrive via a frontier model, channels and
    monetized services follow, and a separate agent keeps swapping local
    models; the operator supervises only. Applied the M5 Ultra capacity
    analysis as data, not prose: `PortfolioPolicy` (`DEFAULT_POLICY` =
    2 scale / 12 active / 4 pilot / 15 review h per week), `PortfolioEvidence`,
    `register_channel` gate (duplicate id, active and pilot limits, review
    hours, incidents), `advance_stage(policy=...)`. Added
    `stigdev/modelradar.py` from Blueprint §10.2–10.3: `ModelSnapshot`,
    `BenchmarkResult`, `PromotionBudget`, `model_promotion_gate` (same suite,
    strict quality gain, memory/p95 budget, no extra human edit time, >=20
    shadow artifacts, 0 critical regressions, commercial license, named
    approver), sequential rollout ladder with rollback to quarantine.
    Revenue figures, domains, the 70% resource split and per-tier concurrency
    stay private (node profiles are not in the public scheduler). Full suite
    331; sample replay ok. Three Claude sessions edited this tree the same
    evening (ADR 0007/0008/0010 here, 0009 elsewhere); all string-replace
    edits, all reconciled, nothing committed. ADR 0010 lists the six-step gap
    to the autonomy target: merge the durable stack, Evaluator/PolicyGate
    injection, receipt-returning local executor, model gateway + radar loop,
    media workers, approval-gated connectors.

## Known gaps / next actions (highest value first)

1. **Replicate before paper-level H5 claims** — use a third capability level
   and/or a second task family. The current interaction is registered but
   partially confirmatory, limited to one benchmark/model pair, and model is
   confounded with Ollama version. Pre-register the replication and any
   equivalence margin before data collection.
2. **Complete the experimental condition matrix** — implement
   `orchestrator` and `full_communication` with logged, matched-budget
   treatment semantics. H2 is not testable until the message-channel arm
   exists; H1–H4 still lack confirmatory evidence.
3. **Close run-integrity gaps before paid/control-plane execution** — version
   event envelopes, make checkpoint/promotion transitions recoverable, compare
   full evidence and policy decisions during replay, and implement atomic
   budget reservation/reconciliation. Today `max_usd` is not enforced and a
   token cap can overshoot by one provider call.
4. **Review the verified offline contracts** in
   `feat/agent-executor-contract`. Production GitWorktreeBackend, OpenCode,
   Codex CLI, and Hermes remain separately scoped future tasks; supervision,
   isolation, budget enforcement, and durable control APIs still need work.
5. **Add paid provider adapters only after budget enforcement** —
   Anthropic/OpenAI behind `Provider`, explicit approval required, never live
   in tests.
6. **Generalize the research state** — multi-artifact/directory-tree
   checkpoints; currently one canonical Python module per run.
7. **Add a stronger sandbox before untrusted execution** — local Git
   worktrees and the current subprocess sandbox are isolation aids, not
   security boundaries.

8. **Media contracts follow-ups (ADR 0007/0008/0009/0010)** — user review of
   the four ADRs; resolve the recorded conflicts (pause in the state diagram,
   repo naming, HTTP surface, three duplicate strategy docs, attributed
   revenue inside the monthly target); decide public vs private placement of
   the untracked SAEOS design docs; wire gates, lineage, the firewall, and
   the commerce ledger into a control plane only after the
   event-store/scheduler stack merges.

## Blockers

No blocker for documentation, offline research, or the accepted contract phase.
Broad OS implementation still needs milestone-specific decisions. External
model API usage, live gateway tests,
production changes, and any private-repository integration require explicit
user approval (see `docs/integration_boundary.md`).
