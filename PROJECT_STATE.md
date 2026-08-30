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

## Known gaps / next actions (highest value first)

1. **Implement `single_persistent` and `best_of_n` conditions** in
   `stigdev/runtime.py` (both are small: best_of_n = N independent stores,
   pick best; single_persistent = one worker with carried context). Needed
   before any RQ1 comparison.
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
