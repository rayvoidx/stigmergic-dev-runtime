# Project state

Durable state + decision log. A fresh agent should be able to resume from this
file alone. Update it at every milestone.

Last updated: 2026-08-30 (initial build session + public release + Ollama adapter).

Published: https://github.com/rayvoidx/stigmergic-dev-runtime (public, CI green).

## Where things stand

MVP vertical slice is **implemented and verified locally**:

- `stigdev` package (stdlib-only, Python >= 3.12): run store (content-addressed
  artifacts, append-only events.jsonl, canonical pointer, manifest), subprocess
  sandbox, TrendEvoBench evaluator v1, strict-improvement promotion policy v1,
  ephemeral worker episodes, deterministic offline provider, run loop with
  explicit budgets, replay/recover, argparse CLI (`demo`, `run`, `evaluate`,
  `replay`, `recover`, `lineage`).
- TrendEvoBench fixtures v1 (synthetic, committed) + seeded generator.
- 41 pytest tests, all passing (unit + e2e: promotion, rejection, lineage,
  replay, recovery, bit-for-bit reproducibility, condition configs).
- Committed sample run in `examples/sample_run/`.
- Five matched-budget condition configs; only `artifact_only` implemented,
  others raise `ConditionNotImplementedError`.

## Verification commands (all confirmed passing in build session)

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest                     # 41 passed
.venv/bin/stigdev demo --runs-root runs        # seed42: 3 promoted, 5 rejected, 0.55->0.86
.venv/bin/stigdev replay examples/sample_run   # ok: true, checked: 9
```

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

## Known gaps / next actions (highest value first)

1. **Pilot-tier comparisons on v2** — the discrimination tier exists; the
   next real gain is 5-seed pilots across conditions with a stronger model
   (paid adapters or a larger local model), per the protocol's pilot tier.
2. Anthropic/OpenAI provider adapters behind `Provider` protocol (paid; gated
   by user approval; never in tests).
3. Harder benchmark tier (larger fixture versions, more mutation surface, or a
   second task family) — current toy saturates at 0.86 quickly.
4. Multi-artifact projects (currently one canonical artifact per run).
5. Stronger sandbox (e.g. seccomp/container) if untrusted-model artifacts are
   ever run.

## Blockers

None. External model API usage and any private-repo integration require
explicit user approval (see `docs/integration_boundary.md`).
