# Project state

Durable state + decision log. A fresh agent should be able to resume from this
file alone. Update it at every milestone.

Last updated: 2026-10-26 (M6 event store, M5 GitWorktreeBackend and M7
scheduler merged to `main` via PRs #3-#7 with ADR 0006 accepted; media
portfolio, concept lineage/Truth Firewall, revenue intelligence, model radar
and portfolio policy, channel lifecycle governance, node profiles, the
monthly capacity envelope, the laptop bridge and model shortlisting added on
top, ADR 0007-0015 proposed; billing blocklist re-pinned to Claude Code
2.1.310, decision #43).

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
- 635 pytest tests passing (2026-10-23): 200 research and kernel tests plus
  the media, governance, node, capacity, worker, and model-fit contracts
  added since.
  Existing unit + e2e coverage includes promotion, rejection, lineage,
  replay, recovery, bit-for-bit reproducibility, condition configs, matrix
  runner, v2 calibration, RQ4 replacement, and observation ablations.
- Committed deterministic and local-model examples in `examples/`.
- Five matched-budget condition configs, all five implemented as of
  2026-09-29 (decision #39). `full_communication` adds a logged inter-worker
  message channel on top of `artifact_only`; `orchestrator` delegates a logged
  assignment from a rule-based planner that spends no provider call. Neither
  new arm has evidence behind it yet. An unknown condition name still refuses
  to run with no silent fallback.
- A conditions × seeds matrix runner and committed live-model evidence:
  two 3×5 pilots, two n=5 medium ablations, an exploratory gpt-oss n=20
  extension, and the registered/partially-confirmatory H5 2×2 (80 runs).
- Agentic Engineering OS design baseline merged in PR #1 (`5867f67`).
  Typed `AgentExecutor`/`WorkspaceBackend`, deterministic fakes, and opt-in
  RunStore execution evidence are implemented and verified offline.
  No production executor/backend, scheduler, gateway, or control
  plane exists. See `docs/execution_contracts.md`.
- M6 kernel scope (ADR 0006) implemented: `stigdev/eventstore.py` (SQLite
  WAL, envelope v2, idempotent append, compare-and-swap pointers,
  content-addressed blobs/trees, store-boundary redaction),
  `stigdev/ledger.py` (event-sourced leases with fencing, recovery, pure
  reducer), `stigdev/v1import.py` (non-destructive import/export), and an
  atomic v1 canonical pointer. Replay v2 compares complete evidence, re-runs
  every policy decision, validates the event sequence, and covers a
  corruption matrix; all 10 committed examples replay clean. Benchmark runs
  still write the v1 file store. See `docs/event_store_v2.md`.
- M5 `GitWorktreeBackend` (`stigdev/gitworkspace.py`) implements the M4
  workspace contract on local Git worktrees: exact-commit allocation on a
  `stigdev/<id>` branch, file-locked one-writer lease with fencing, ADR 0006
  tree checkpoints into the event store, quarantine, and disposal that
  refuses uncheckpointed changes. Worktrees are not a security boundary.
  See `docs/git_worktree_backend.md`.
- M7 `Scheduler` (`stigdev/scheduler.py`) over the ledger: DAG readiness in
  submission order, retries up to `max_attempts`, per-attempt reservations
  reconciled at finish or recovery (calls, tokens, USD, wall, workspaces,
  concurrency), hard exhaustion and cancellation as terminal events, and
  restart from the store. `max_usd` defaults to zero and is checked before
  any lease. See `docs/scheduler.md`.

## Verification commands (2026-10-23)

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest                     # 635 passed
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
25. **ADR 0006 proposed (2026-09-20, design-only).** Resolves ADR 0005
    deferred decisions 1–2 for M6: stdlib `sqlite3` WAL store with one writer
    per store, envelope v2 (schema/event/causation/idempotency identity),
    idempotent append and pointer compare-and-swap, event-sourced leases with
    restart recovery, content-addressed tree checkpoints, read-only v1
    compatibility plus a tested non-destructive importer, and store-boundary
    redaction. M6 now precedes M5. No code, test, or experiment changed;
    135 tests and all example replays still pass on `6dd99f7`.
26. **M6 kernel scope implemented (2026-09-20, `fix/run-integrity-v2`).**
    User direction accepted ADR 0006. Added `SqliteEventStore` (stdlib
    `sqlite3`, WAL, one writer per store, envelope v2, unique idempotency
    key, causation must exist, CAS pointers, sha256 blobs/trees verified on
    read, forbidden-value redaction, nested all-or-nothing transactions),
    `TaskLedger` (lease acquire/renew/finish/recover with the lease event as
    fencing token; a late finish after expiry or renewal raises, a duplicate
    from the same lease returns the stored event; interrupted re-queues),
    and a v1 import/export bridge (sample run round-trips byte-identical and
    replays equal). Tests include a real SIGKILL mid-transaction and a
    24-task/2-slot queue simulation with one crash and one duplicate
    delivery. `RunStore.set_canonical` now uses temp file + `os.replace`.
    Not done: replay v2 evidence/policy comparison, corruption matrix on the
    v2 store, `lease_released`, CLI, budgets. 164 passed; replays unchanged.
27. **Replay v2 implemented (2026-09-20, `fix/replay-v2`).** `replay` now
    parses the log strictly (JSON, strictly increasing seq; unreadable logs
    are reported, not raised), refuses evaluator or policy version
    mismatches, compares complete evidence (all metrics and reasons), re-runs
    `strict-improve/v1` on the recorded evidence of every promoted/rejected
    event (decision, reason, policy_id, artifact, score, generation; missing
    or orphan decisions are divergences; best-of-n selection at episode -1
    only advances the chain), and reports `decisions`. `replay_store`
    replays a v2-store run via export. Corruption matrix: events, metrics,
    reasons, policy decisions, blobs, pointers. All 10 committed examples
    replay clean with 0 divergences (sample_run 9 checked/8 decisions).
    178 passed. ADR 0004's follow-up is now present behavior.
28. **M5 GitWorktreeBackend implemented (2026-09-20, `feat/workspace-backend`).**
    Local Git worktrees behind the M4 `WorkspaceBackend` protocol: `create`
    requires an exact 40-hex commit present in a registered repository and
    allocates `git worktree add -b stigdev/<id>`; ids containing `/` or `..`
    are refused; `inspect` reports `HEAD` or `HEAD:<tree digest>` when dirty;
    `checkpoint` writes blobs plus a content-addressed tree into a
    `SqliteEventStore` and records tree, `HEAD`, patch digest, and file
    count; `quarantine` retains with a reason; `dispose` removes worktree and
    branch, refusing changes not captured by the last checkpoint unless
    `discard=True`, and records the cleanup outcome. One-writer lease per
    workspace (holder + TTL, `flock`-guarded JSON record) fences a previous
    holder after expiry. Symlinks and out-of-root paths fail closed; the
    linked worktree's `.git` file is excluded (found by test: it was counted
    as a file). 188 passed. Not a security boundary; no executor uses it
    yet.
29. **M7 scheduler implemented (2026-09-20, `feat/task-scheduler`).**
    `Scheduler` reduces ledger + budget events into a `ScheduleState`:
    submission-order head-of-line readiness over a DAG (dependencies must
    be submitted first, so no cycles), retry of failed/timed_out/interrupted
    up to `max_attempts` via an explicit `retry` flag on `attempt_finished`,
    `budget_reserved` at lease and `budget_reconciled` at finish/recovery
    with overshoot recorded, hard `budget_exhausted` once per run (cap minus
    used, wall deadline), `task_cancelled`/`run_cancelled` terminal events,
    concurrency and workspace limits, and identical state from a restarted
    instance. A paid reservation cannot be submitted under the default
    `max_usd=0`. No backfilling, priorities, or per-task budgets. The
    research runtime does not run under the scheduler yet. 200 passed.

30. **Media portfolio contracts implemented offline (2026-09-27, ADR 0007
    proposed).** Executing §13 P0 of the private SAEOS Media Foundry strategy
    document v3 (held in `saeos-private`, not here) as the public, generic
    half: `stigdev/portfolio.py` holds
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

31. **v3.1 amendment executed offline (2026-09-27, ADR 0008 proposed).**
    The private strategy document v3.1 ("Organic Ecosystem Amendment") makes
    Signal Stories a mandatory channel and ties every surface to one
    `concept_id` behind a
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

32. **v3.2 amendment executed offline (2026-09-27, ADR 0009 proposed).**
    The private strategy document v3.2 ("Revenue Intelligence Amendment")
    adds §5.15 and §11.2:
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

33. **Capacity policy and Model Radar gate implemented offline (2026-09-27,
    ADR 0010 proposed).** Operator target restated: a fully autonomous 24/7
    OS where plans arrive via a frontier model, channels and
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

34. **Multi-channel portfolio governance implemented offline (2026-09-28,
    ADR 0011 proposed).** Executing v3.3 §5.16 and Blueprint v2.1 §14.4-14.6,
    both held privately. Four stdlib modules: `stigdev/lifecycle.py`
    (`proposed → unlisted_canary → pilot → monetization_gating → scale →
    maintain → retire`, an orthogonal `clear/watch/quarantined/frozen`
    incident overlay, `AudienceContract`, `FormatFingerprint`, the
    seven-condition scale gate, and `PORTFOLIO_STAGE` mapping onto the coarser
    `portfolio.STAGES`); `stigdev/overlap.py` (six-component weighted review
    heuristic, never a block); `stigdev/payout.py` (`observed →
    platform_estimated → platform_finalized → paid → bank_reconciled → net`,
    where `total_across` refuses to mix rungs, because one payment shows up on
    several screens at once); `stigdev/incident.py` (K0-K4 blast radius,
    fail-closed, reads refused at K4). The external 27-channel / 60,000,000
    KRW claim is graded C and provably cannot reach a forecast. Anti-evasion
    stance in `docs/anti-evasion.md`: ownership obfuscation, near-duplicate
    publishing, and flooding are refused as designs. Regression surface is
    `examples/synthetic_27_channel_portfolio/`, synthetic only. Suite 477
    passed; sample replay clean. Decisions 30-33 were renumbered here: merging
    the kernel stack had left two independent sequences both restarting at 25.

35. **Node profiles, Metal admission, and a commissioning check (2026-09-28,
    ADR 0012 proposed).** An audit found the kernel had no concept of a machine
    at all — no node, no host, no memory or GPU in the budget dimensions.
    `stigdev/node.py` adds `ResourceClass`, `NodeProfile` (`mobile-m4`,
    `studio-m5-ultra`), `HostFacts`, fail-closed `admit`, and a
    `commissioning_gate`. `scripts/commission_node.py` is the read-only macOS
    measurement half; `docs/commissioning.md` is the day-one runbook;
    `deploy/launchd/` carries a daily readiness agent. Stated plainly and
    asserted by test: the laptop admits one of six resource classes and cannot
    host the writer alias at 28 GB against 16 GB usable.
    Nothing is wired into `Scheduler` yet — the prerequisite is a worker
    daemon, and `Scheduler`/`TaskLedger` still have no production caller.

36. **Defects found by review and fixed (2026-09-28).** Three parallel reviews
    of the 2026-09-27 work found six real defects, each reproduced before being
    fixed. (a) `incident`: a credential- or portfolio-scoped incident at low
    severity halted nothing, because only severity set the kill floor; scope
    now sets one too, so a credential incident is K4 however mild it reads.
    (b) `payout`: `amounts` was a plain dict on a frozen dataclass, so a caller
    could write a `paid` figure the ladder never reached and defeat
    `total_across`; it is a read-only mapping now. (c) `overlap`: `components`
    was not copied, so mutating the caller's dict changed a frozen object's
    score after construction. (d) `payout.cash()` admitted a state its own
    contract excluded. (e) `ledger`: lease fencing compared ids but not the
    holder, so with two machines on one store a stale lease could be used by
    the wrong worker. (f) `store`: the v1 JSONL log keeps its sequence counter
    in memory, so a second writer silently produced duplicate seq numbers and
    an unreplayable run — it now refuses to append if the log grew underneath
    it. Also implemented `lifecycle.cross_channel_reuse_gate`, because
    `docs/anti-evasion.md` claimed exact reuse was a hard publish failure when
    nothing enforced it; the remaining overstatements in that document were
    corrected rather than left flattering.

37. **Monthly capacity envelope implemented offline (2026-09-29, ADR 0013
    proposed).** ADR 0012 answers "may this job start now"; nothing answered
    "does a month of this publish plan fit". Two gates were taking that on
    faith: `lifecycle.ScaleEvidence.capacity_available` (a bare bool) and
    `portfolio.PortfolioEvidence.review_hours_per_week` (a caller-measured
    number). `stigdev/capacity.py` now computes both from a plan:
    `ArtifactCost`/`ChannelDemand`/`CapacityBudget`, `budget_from` (504 GPU
    hours at 70% of a month; memory ceiling = min of the ADR 0012 reserve and
    the utilisation share), `capacity_report`/`capacity_gate` (GPU hours,
    review hours, retention-scaled working set, every deficit at once),
    `months_until_archive_full`, `shorts_pool_floor` (threshold and effective
    date read from a `revenue.PolicySnapshot`, never hardcoded), and
    `project_revenue`, which emits `estimated` rows so ADR 0009's
    `gross_revenue` rule structurally prevents a sensitivity calculation from
    being counted as money. Shipped `PLANNING_COSTS` are the analysis's
    assumptions, not measurements, and tests pin what they imply: 10 channels
    sit inside the 120-180 Shorts / 12-24 long / 60-100 review-hour envelope;
    at 12 channels the GPU still has headroom while review hours break the
    15 h/week cap; a 14-day cleanup is what keeps the working set on a 1TB
    disk. 33 tests, full suite 547, sample replay ok. Conflicts recorded in
    ADR 0013: the 76GB-vs-67.2GB memory ceiling, channel count capped in two
    places, the analysis's absolute-15 ceiling deliberately not encoded, music
    derivatives outside `portfolio.FORMATS`, and revenue bands left out as
    forecasts. Not wired into any gate yet.

38. **External hypotheses can be registered with their provenance
    (2026-09-29, amends ADR 0007).** An operator-supplied X thread claimed
    qualified views are about 45% of nominal views. Registering it exposed a
    hole: `RevenueClaim` grades external *money* claims, but an external
    *mechanism* claim had nowhere to keep its source or grade, so recording it
    would have meant recording a number without the grade the repository's own
    rule demands. `FormatHypothesis` gained co-required `source_url` and
    `evidence_grade` plus an `external` property, and `EVIDENCE_GRADES` moved
    from `revenue.py` down to `portfolio.py` (imported back) so one vocabulary
    grades both kinds of claim — `revenue` already depends on `portfolio`, so
    duplicating it was the only alternative. Both fields default to `None`; no
    caller changed. The claim itself is registered as grade C, status open, in
    `docs/experiments/2026-09-29-external-qualified-view-ratio.md`, with the
    source quoted from screenshots because X returns `HTTP 402` to `WebFetch`.
    Recorded there and not acted on: 0.45 must not become a constant, and
    `capacity.SHORTS_POOL_SHARE` is already 0.45 meaning something unrelated.
    6 tests, full suite 553, sample replay ok.

39. **The condition matrix is complete (2026-09-29, closes gap 2).**
    `full_communication` and `orchestrator` were config-only since the first
    build. Both now run, following the registered protocol wording rather than
    a convenient reading of it. `full_communication` is condition 3 *plus* a
    logged inter-worker message channel: the stigmergic medium stays and each
    ephemeral worker additionally hears what every earlier worker said, so its
    observation is strictly larger — that difference is what H2 prices.
    `orchestrator` runs a rule-based planner (`worker.plan_directive`) that
    reads the store, logs a `delegated` assignment per episode, and hands the
    worker that assignment instead of the failure records. The planner spends
    no provider call, so budgets stay matched; the cost is that the arm
    measures centralised routing, not an LLM planner, and that ceiling is
    recorded in the code and the protocol. New events `message_broadcast` and
    `delegated` replay clean. `artifact_only` is untouched: both new
    parameters default to `None`, and the seed-42 demo invariants still hold.
    **Honest limit found while testing:** H2's token-cost half is not
    measurable offline, because the deterministic provider reports zero cost.
    A test pins that equality so no offline matrix is misread as cost
    evidence; the claim needs a live provider. The now-dead
    "unimplemented conditions fail loudly" parametrisation was replaced with
    a test of the live refusal path (an unknown condition name).
    Also closed the first half of gap 11: `capacity.capacity_available`
    derives `lifecycle.ScaleEvidence.capacity_available` from a plan, with a
    test showing an over-committed 12-channel portfolio cannot scale another
    channel. It stays a function, not a record change, because every other
    field on that evidence record is caller-measured by design.
    Full suite 565, sample replay ok. README, `docs/research_protocol.md`,
    and `docs/paper_outline.md` no longer claim the two arms are config-only.

40. **The laptop bridge runs unattended (2026-09-29, ADR 0014 proposed;
    closes gap 10's first item).** The Mac Studio is about seven weeks out, so
    24/7 has to happen on the M4. Two pieces were missing and both now exist.
    `stigdev/workerd.py` is the first production caller `Scheduler` and
    `TaskLedger` ever had: one tick is recover, admit, acquire, execute,
    finish. Admission runs *before* the lease so a hot laptop leaves work
    `pending` instead of stranding it `leased`, and every exit path finishes —
    an adapter that raises is a failed attempt, never a worker holding a lease
    the ledger cannot see. `stigdev/claudecode.py` puts Claude Code behind
    `AgentExecutor`, where ADR 0005 says a coding-agent CLI belongs, not behind
    `Provider`. The operator's requirement was that this stay off the API, and
    it is enforced twice: `BILLING_ROUTE_VARS` (seven variables, Claude Code
    2.1.261) is stripped from the subprocess environment and a request that
    *sets* one is refused before launch; and `ExecutionUsage.usd` is pinned to
    zero, because the CLI's `total_cost_usd` is an API-equivalent estimate and
    recording it would tell every budget that cash moved when none did.
    Verified on this machine: `claude` 2.1.261 at `~/.local/bin`, no
    `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` set. Added `stigdev worker`
    and a launchd agent at `Background` QoS with `Nice 5`.
    **The honest ceiling:** `MOBILE_M4` leaves 16 GB usable, so of six
    resource classes only `text_small` (10 GB) and `render_cpu` (12 GB) can
    ever run there. `text_coder`, `vision`, `image_final` and `video_heavy`
    are impossible on this machine, not merely slow — local image, vision and
    video work waits for the Studio, and a worker asking for one of those
    classes fails at construction. Concurrency stays 1. 31 tests, full suite
    596, sample replay ok. Recorded in ADR 0014 and not resolved: the billing
    list is a blocklist pinned to one CLI version, nothing proves a valid
    subscription positively, and no workspace backend is wired in yet.

41. **Model choice follows public rankings, bounded by memory (2026-09-29,
    ADR 0015 proposed).** `node.py` knew what a machine holds and knew nothing
    about models; `modelradar.py` promoted on measurement and knew nothing
    about where a candidate came from. `stigdev/modelfit.py` joins them:
    `ModelCandidate` carries a rank, its source, a licence state and an
    evidence grade that **cannot be A** (grade A is reserved for a benchmark
    this repository ran), `estimated_memory_gb` sizes it from a deliberately
    generous table, `fits` requires the estimate inside both the resource
    class budget and the node, and `shortlist` returns what fits in rank
    order — commercial licences only by default. `to_snapshot` hands a
    candidate to Model Radar with the rank stripped, so a leaderboard can pick
    what to *try* and never what to run. `scripts/fetch_model_rankings.py` is
    the networked half, kept out of `stigdev/` like `commission_node.py`.
    Verified live on 2026-09-29 against the Hugging Face API with
    `--node mobile-m4 --class text_small`: 39 considered, shortlist led by
    `Qwen/Qwen3-0.6B` (1.86 GB) and `Qwen/Qwen3-8B` (6.3 GB), both Apache-2.0,
    all under the 10 GB class budget. 24 tests, full suite 620, replay ok.
    Recorded and not resolved: downloads are popularity, not quality; the
    sizing table is a guess until a benchmark contradicts it; parameter counts
    fall back to name parsing; the licence allowlist is conservative and drops
    real candidates; and nothing yet submits benchmark tasks for a shortlist.
    Also drafted `docs/archive-channel-launch.md`: name candidates for the
    Archive lane (recommendation 밤의 사관, with 야사담 for the unofficial-history
    segment), its audience contract, the `ChannelPlan` to register, and the
    cadence checked against ADR 0013. Creating the account needs the
    operator's Google sign-in and is not automated here.

42. **Downstream publication boundary clarified (2026-09-30).** The operator
    requested daytime laptop uploads and public scheduling at least 24 hours
    after upload completion, with quantity following finished assets (initial
    ceiling five/day). This supersedes the older weekly cadence in the Archive
    launch proposal for that deployment. Implementation and account material
    stay in the private operations layer; no public runtime code was changed
    for this request. See `docs/publication_boundary.md`. Channel creation,
    OAuth consent and live publication were not completed at this handoff.
    Local verification against the current working tree: 620 public tests;
    all 10 committed example stores replay clean (56 evaluations). These are
    correctness checks, not model or publication-performance evidence.

43. **The billing blocklist caught up with the installed CLI (2026-10-23).**
    ADR 0014 pinned `BILLING_ROUTE_VARS` to Claude Code 2.1.261 and recorded,
    as its first unresolved limit, that a later release could add a route the
    executor would not know. It did: the installed CLI is 2.1.310 and its
    binary carries thirteen routing variables the list did not name — Mantle,
    "Anthropic on AWS", "Anthropic on Google Cloud", Microsoft Foundry
    (resource, base URL, API key, auth token) and the gateway switch. All
    twenty are now stripped from the subprocess environment and refused when
    a request sets one; a test pins the seven cloud families so narrowing the
    list fails loudly. The pin is read from the binary's own strings, not from
    memory. Same pass, same review: `read_host_facts` pushed the scripts
    directory onto `sys.path` on every worker tick (every five seconds under
    `run_forever`), now once, with a test; three unused imports dropped
    (`cli.py`, `node.py`); pyflakes clean. 635 tests, seed-42 demo invariants
    unchanged, sample replay ok. Still a blocklist and not a proof — ADR 0014
    limit 1 stands, and the next CLI upgrade should re-read the binary.

44. **A daily pass for this repository, and a steward over the whole system
    (2026-10-25, ADR 0016 proposed).** The operator asked whether "the whole
    system improves every day and GitHub work happens on its own" was true.
    It was not: the media side had its daily loop (supervisor, 06:40 pulse,
    six-hourly performance snapshots, a 09:30 growth agent) but this
    repository had moved only by hand, and nothing anywhere pushed to GitHub
    unattended. `scripts/daily_pass.py` is the missing caller: one bounded
    Claude Code pass a day in a throwaway worktree off `origin/main`, through
    `ClaudeCodeExecutor` so the subscription rule holds, gated by a path
    blocklist (the agent cannot edit its own gates), a 12-file / 600-line
    cap, a secret scan over added lines, pyflakes, pytest, the seed-42 demo
    and replay, then one push to `main`. `NO_CHANGE` is a recorded outcome and
    produces no commit; every run writes `state/daily/<date>.json`.
    `deploy/launchd/dev.stigmergic.daily.plist` runs it at 05:30 KST. 20
    tests, suite 655. The private operations layer gained a steward that
    reads that file beside its own agents, the Pages site and the app
    backend; it stays private (`docs/integration_boundary.md`). Recorded and
    not resolved: the pass is not a security boundary, the gates are a
    blocklist, a green pass proves only that the tests still hold, and the
    first unattended run under launchd is still to be observed.

45. **A slow attempt no longer kills the worker loop (2026-10-25).** When an
    attempt outlived its lease (the executor timeout and the lease TTL both
    default to 900 s, so a task that hits its timeout usually does),
    `WorkerLoop._finish` hit the ledger's fencing check and the resulting
    `LeaseError` propagated out of `tick()`, crashing `run_forever` — the
    docstring's "every exit path finishes" did not hold on the one path where
    the ledger had already taken the lease back. The fence is correct: a
    superseded worker must not record the outcome. The worker now yields to it
    (catches `LeaseError` in `_finish` and keeps polling; the next `recover()`
    records the attempt as interrupted and releases the reservation).
    Reproduced pre-fix with `lease_ttl=1.0` against the stepping test clock;
    regression test added. 656 tests, seed-42 demo invariants unchanged,
    sample replay ok.

46. **A malformed executor result no longer kills the worker loop
    (2026-10-26, daily pass).** `ExecutionResult`'s own contract says it is
    untrusted until `validate_result` passes; `execution.py` obeyed that and
    `workerd.tick` did not. An adapter returning a status the ledger does not
    know (e.g. `"succeeded"`) raised `ValueError` out of `tick()` — killing
    `run_forever` and stranding the task `leased` until the TTL — and a
    foreign `attempt_id` would have been recorded under this worker's lease.
    `tick` now runs `validate_result` inside the same try as the executor
    call, so a contract-violating result is a failed attempt like any other
    adapter crash (reproduced pre-fix; regression test added; the test fake
    now emits contract-valid failures). 658 tests, seed-42 demo invariants
    unchanged, sample replay ok.

47. **The daily pass takes other repositories through flags (2026-10-26,
    ADR 0017 proposed).** The first unattended run of #44 pushed #46 at 05:51
    KST from launchd, so the loop works end to end. The operator then decided
    that every part of the system gets one bounded, test-gated improvement
    pass a day, applied to GitHub where a remote exists and to the running
    checkout either way. `scripts/daily_pass.py` stays one script:
    `--prompt FILE`, `--verify CMD` (repeatable, replaces the default checks),
    `--guard PREFIX` (widens the blocklist only), `--state DIR`,
    `--base`/`--branch`, `--merge` (a fast-forward of the checked-out branch,
    never a reset; a merge the checkout cannot take is a note after a push and
    `merge_failed` without one) and `--after CMD` (restart what serves the
    code). Without flags it behaves exactly as ADR 0016. Which repositories,
    with which prompts, checks and restarts, stays in the private operations
    layer, which runs the targets in sequence under one launchd label so two
    agents never share the CPU or the quota. 27 tests in
    `tests/test_daily_pass.py`, suite 664; demo and replay unchanged. Recorded
    and not resolved: a target whose `main` deploys deploys the agent's commit
    unattended; `--verify` runs the operator's shell commands, outside the
    agent's reach. First app-target rehearsal the same evening: a real fix with
    four tests, committed on its branch in 8 minutes with all five checks
    green; the agent's preamble had become the subject, so `commit_message`
    now starts at the first conventional subject line.

## Known gaps / next actions (highest value first)

1. **Replicate before paper-level H5 claims** — use a third capability level
   and/or a second task family. The current interaction is registered but
   partially confirmatory, limited to one benchmark/model pair, and model is
   confounded with Ollama version. Pre-register the replication and any
   equivalence margin before data collection.
2. **Collect data on the completed condition matrix** — all five arms run as
   of 2026-09-29 (decision #39), but `full_communication` and `orchestrator`
   have zero evidence behind them. H1–H4 still lack confirmatory evidence, and
   H2's cost half needs a live provider because the offline one reports zero
   tokens. The orchestrator arm's planner is rule-based; a generative
   coordinator would need its own budget line before it could be compared.
3. **Close run-integrity gaps before paid/control-plane execution** — version
   event envelopes, make checkpoint/promotion transitions recoverable, compare
   full evidence and policy decisions during replay, and implement atomic
   budget reservation/reconciliation. Today `max_usd` is not enforced and a
   token cap can overshoot by one provider call in the research runtime. M6
   and M7 are done: event store v2, ledger, v1 bridge, replay v2, and
   scheduler-level reservation/reconciliation with `max_usd` checked before
   any lease. Moving the research runtime under the scheduler is open.
4. **Build on the merged M6/M5/M7 kernel** — PRs #3-#7 merged the event
   store, task ledger, replay v2, GitWorktreeBackend, and scheduler into
   `main` (CI green on 3.12/3.13). OpenCode, Codex CLI, and
   Hermes adapters remain separately scoped; supervision, isolation, budget
   enforcement, and durable control APIs still need work.
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

9. **Portfolio governance follow-ups (ADR 0011)** — collapse
   `portfolio.STAGES` into the finer `lifecycle` machine once private
   consumers move off the coarse names. Direction: `lifecycle` becomes the
   single machine and the coarse stage stays only as a derived view
   (`ChannelSlot.portfolio_stage`), with `register_channel` the one place that
   counts; no third machine. `portfolio.pause` is superseded by the
   `lifecycle` incident overlay, which is orthogonal to the lifecycle rather
   than a state inside it, so the collapse deletes `pause` and lets
   `may_publish`/`incident_state` carry it. Until then a test pins the mapping
   image to `STAGES - {pause}`. Then add the audit-event stream and a
   `Policy Watch` job tracking platform-rule effective dates. The private
   revenue control plane itself is out of scope for this repository.

10. **Make the second machine earn its keep (ADR 0012)** — the `worker`
   command exists now (decision #40) and `Scheduler`/`TaskLedger` finally have
   a production caller. Remaining, in order: a node id carried as the lease holder
   and added to the execution event identity; a ledger clock derived from the
   database rather than the caller, so drift cannot move leases between
   machines; then memory as a scheduler dimension with `node.admit` at the
   acquire seam. Keep the store on one machine's local disk: WAL is unsafe over
   network mounts.

11. **Close the capacity loop (ADR 0013)** — the derivation seams exist now
   (`capacity.capacity_available` and `capacity.review_hours_per_week`, both
   tested against the gates they feed), so what is left is a caller: no
   control plane computes either today. Then replace `PLANNING_COSTS` with
   measured render costs, because every conclusion above rests on assumed
   numbers. Model the LLM / image / TTS-render queues separately only once
   measurement shows one pooled GPU budget hides a real bottleneck.

12. **Watch the daily passes (ADR 0016, ADR 0017)** — read the first days of
   `state/daily/<date>.json` here and the per-target reports the private
   runner keeps, and the commits they pushed or merged. A bad day is reverted
   by hand and that target's prompt tightened; a run of `NO_CHANGE` days means
   the prompt's menu is exhausted and the gaps above (or the target's brief)
   need new entries. The app target's push deploys; if that proves too eager,
   `--branch dev` makes it a reviewed change.

## Blockers

No blocker for documentation, offline research, or the accepted contract phase.
Broad OS implementation still needs milestone-specific decisions. External
model API usage, live gateway tests,
production changes, and any private-repository integration require explicit
user approval (see `docs/integration_boundary.md`).
