# stigmergic-dev-runtime

[![ci](https://github.com/rayvoidx/stigmergic-dev-runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/rayvoidx/stigmergic-dev-runtime/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)

A minimal, reproducible research runtime for **evaluator-gated stigmergic software
evolution**.

**Thesis.** *Persistent projects, ephemeral agents:* finite-lived AI workers can
accumulate useful software capability through versioned executable artifacts,
lineage, evidence, and failure records — without depending on persistent
conversational identity.

Workers never talk to each other. Coordination happens only through the shared
project state: the canonical artifact, its lineage, evaluator evidence, and the
recorded failures of earlier (now gone) workers.

## Research questions

- **RQ1** Under matched inference and tool budgets, does artifact-mediated
  coordination outperform a single persistent agent and isolated best-of-N on
  continuous software-evolution milestones?
- **RQ2** How much useful coordination remains when direct agent communication
  is removed but executable artifacts, lineage, evaluator evidence, and failure
  records persist?
- **RQ3** Does inherited failure evidence reduce repeated failures and
  regressions without suppressing exploration?
- **RQ4** Does artifact-centric state improve continuity when workers or model
  providers are replaced?

See `docs/research_protocol.md` for hypotheses, variables, metrics, and the
statistical plan; `docs/related_work.md` for the claim ledger.

## Quickstart

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/stigdev demo                      # deterministic offline demo -> runs/demo-seed42
.venv/bin/stigdev lineage runs/demo-seed42  # promotion chain + failure records
.venv/bin/stigdev replay runs/demo-seed42   # re-derive all evidence, verify the run
.venv/bin/python -m pytest                  # full suite
```

Requires Python >= 3.12. No third-party runtime dependencies; `pytest` for dev.
The demo, benchmark, and tests are fully offline and deterministic — no model
API calls, no network, no cost.

## What one run does

Each episode is an ephemeral worker: it sees only a bounded observation
(canonical artifact + score, recent failure records, budget), proposes a full
replacement artifact, and disappears. The evaluator executes the candidate in a
sandbox against versioned fixtures; the promotion gate accepts strict
improvements only. Rejected candidates stay content-addressed on disk as
failure evidence — visible to later workers, never contaminating canonical
state.

```mermaid
flowchart LR
    S[(Run store\nartifacts + events\ncanonical pointer)] -->|bounded observation| W[Ephemeral worker\nepisode]
    W -->|candidate artifact| E[Evaluator\nsandboxed execution\nversioned fixtures]
    E -->|evidence| G{Promotion gate\nstrict-improve/v1}
    G -->|promote| S
    G -->|reject: failure record| S
```

Every transition is an event in an append-only `events.jsonl`; artifacts are
immutable `artifacts/<sha256>.py` files; `manifest.json` pins config, seeds,
fixture hashes, evaluator/policy versions, environment, and cost. `stigdev
replay` re-executes every recorded evaluation and verifies the promotion chain;
`stigdev recover` restores the canonical pointer from the event log after
corruption.

## TrendEvoBench

A toy, fully synthetic trend-selection benchmark (`benchmarks/trendevobench/`):
evolve `select_trends(items, k) -> ids` against fixtures containing clickbait
traps, near-duplicates, stale items, and keyword-bearing hype. Metrics:
precision@k, duplicate-group uniqueness, composite score, train/holdout split.
The seed-42 demo goes from 0.55 to 0.86 (train) and 0.52 to 0.86 (holdout) via
three promotions, with five rejections recorded as failure evidence.

Two fixture tiers exist: **v1** (mechanism tier, used by the demo and most
tests) and **v2** (discrimination tier: paraphrased duplicates that defeat
prefix dedup, spam detectable only via source reliability, old-but-relevant
items, engagement as anti-signal; floor 0.30 / v1-strategy plateau ~0.69 /
probed ceiling 0.97 on train). See `benchmarks/trendevobench/README.md` for
the calibration table.

The shipped offline provider is a deterministic reference worker that proposes
predefined mutations ("genes") — it exists to exercise the runtime and tests
without a model API. It reads inherited failure records and skips known-failed
mutations (the RQ3 mechanism, toggleable via `use_failure_memory`). Paid
provider adapters (Anthropic/OpenAI) are future work behind the same
`Provider` protocol.

## Running with a live local model

An Ollama adapter (localhost, zero cost, stdlib urllib) is included:

```bash
stigdev run --config configs/providers/ollama-gemma3-12b.json --runs-root runs
```

Example outcome of one such run (gemma3:12b on an M4 Pro, 100% Metal GPU
offload, 92 s wall, 6,616 tokens, $0 — committed as
`examples/live_run_gemma3_12b/`): the model wrote a free-form
`recency_weighting` artifact that was promoted (train 0.55 -> 0.66, holdout
0.52 -> 0.63); five later proposals tied or regressed and were rejected, and
inherited failure records kept all six proposals distinct. This is a
mechanism demonstration on a toy benchmark, not a capability or comparison
claim. Live-model runs are not bit-reproducible; `stigdev replay` still
re-derives and verifies all recorded evidence (it does for this run: 7
evaluations, 0 divergences). Tests never call a live model.

A first archived 3-condition comparison (offline + live gemma3:12b, one seed,
qualitative only) lives in
`docs/experiments/2026-08-30-local-3condition-comparison.md`.

## Experimental conditions

`configs/conditions/` holds matched-budget configs for all five comparison
arms. Unimplemented ones parse, validate, and **refuse to run** rather than
silently falling back:

| Condition | Status |
|---|---|
| `single_persistent` | **implemented** — one worker, private full-trajectory memory, never reads the store's failure records |
| `best_of_n` | **implemented** — `n_workers` isolated stores, budget split n ways, best final artifact selected (logged as a promotion) |
| `artifact_only` (stigmergic) | **implemented** — ephemeral workers, coordination only through the shared store |
| `full_communication` | config only |
| `orchestrator` | config only |

Caveat: with a single sequential offline worker, `single_persistent` and
`artifact_only` carry the same information and produce identical results by
construction — the conditions differ in the information *source* (private
context vs persistent medium), which is exactly what worker-replacement (RQ4)
and live-context-limit experiments will stress. One deterministic matched-
budget run (8 episodes, seed 42) illustrates the structure:
`artifact_only` = `single_persistent` 0.86 train / 0.86 holdout, versus
`best_of_n` (4 workers x 2 episodes) 0.84 train / 0.74 holdout — splitting
the budget cost search depth. Single runs; mechanism demo, not evidence.

## Current limitations

- The sandbox (`stigdev/sandbox.py`) is process isolation only: separate
  CPython in `-I` mode, timeout, temp cwd. It does **not** confine filesystem
  or network access and is not a security boundary against malicious code.
- The offline provider explores a small fixed mutation space; results with it
  demonstrate the runtime mechanics, not model capability.
- TrendEvoBench is a toy task; no experimental results exist yet. Nothing here
  claims autonomous continual learning or superiority over other approaches.
- Four of five experimental conditions are configuration-only.

## Public/private boundary

This repository is public (Apache-2.0) and self-contained: generic runtime,
schemas, synthetic fixtures, benchmark, docs. It must never contain production
connectors, scraped data, credentials, commercial ranking logic, or private
prompts. Downstream commercial systems (e.g. a trend agent) may depend on this
runtime through the interfaces described in `docs/integration_boundary.md`;
the dependency is strictly one-way. See `SECURITY.md`.

## Repository map

```
stigdev/                  runtime package (store, sandbox, evaluator, policy,
                          provider, worker, runtime, replay, cli)
benchmarks/trendevobench/ fixture generator, versioned fixtures, seed artifact
configs/conditions/       five matched-budget experiment configs
examples/sample_run/      committed output of the deterministic demo
tests/                    unit + end-to-end suite (pytest)
docs/                     ADRs, related-work claim ledger, research protocol,
                          paper outline, integration boundary
PROJECT_STATE.md          durable state + decision log for continuation
```

## License

Apache-2.0. See `LICENSE`, `CITATION.cff`, `CONTRIBUTING.md`, `ROADMAP.md`.
