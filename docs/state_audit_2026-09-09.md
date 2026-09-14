# Repository state audit — 2026-09-09

Status: completed for the `docs/os-design-v1` design baseline.

This audit compares documentation with the implementation, tests, committed
run artifacts, committed experiment data, and Git history at `d0a7778`. It is
a factual state check, not a new experiment and not evidence beyond the
committed records it cites.

## Evidence precedence

When sources disagreed, this audit used the following order:

1. implementation and tests;
2. committed run manifests, event logs, and experiment data;
3. Git history, including the H5 registration commit;
4. prose documentation.

## Confirmed baseline

- `stigdev` implements `artifact_only`, `single_persistent`, and `best_of_n`.
  `full_communication` and `orchestrator` parse and fail closed.
- The runtime has content-addressed Python artifacts, a flat append-only JSONL
  event log, a canonical pointer, evaluator-gated promotion, recovery, replay,
  explicit run budgets, an offline provider, and a local Ollama provider.
- TrendEvoBench v1 and v2, the conditions matrix runner, promotion-history and
  failed-source ablations, and worker/provider replacement controls exist.
- Pytest collects 55 tests. The suite is offline; the Ollama transport is
  mocked in tests.
- Committed data covers the two 3×5 live-model pilots, two n=5 ablations, the
  exploratory gpt-oss n=20 extension, and the registered, partially
  confirmatory H5 2×2 with 80 runs.
- H5 was added in commit `6327f7b`; the committed record states that it was
  registered after the gpt-oss n=5 pilot but before the n=20 extension and
  before gemma3 seeds 46–60.

## Discrepancies and disposition

| Source | Stale or over-broad statement | Evidence | Disposition |
|---|---|---|---|
| `PROJECT_STATE.md` | Last update remained 2026-08-30 although entries include the 2026-09-06 H5 result. | Git log and decision entries 20–21. | Update date and baseline. |
| `PROJECT_STATE.md` | 41 tests and only `artifact_only` implemented. | `pytest --collect-only` collects 55; `IMPLEMENTED_CONDITIONS` contains three arms. | Correct counts and condition status. |
| `README.md` | “No experimental results exist yet” and four of five conditions are config-only. | Experiment notes/data exist; three conditions run and two fail closed. | Replace with tiered result summary and exact limits. |
| `README.md` | Research questions stop at RQ4. | RQ5/H5 is in the protocol and commit `6327f7b`. | Add RQ5 and its registration caveat. |
| `docs/paper_outline.md` | No results, empirical findings empty, and conditions 1, 2, 4, 5 blocking. | Conditions 1–3 run; H5 and exploratory data are committed. | Rewrite results and remaining evidence gaps. |
| `docs/research_protocol.md` | No experiment in the protocol has run. | Multiple lab notes and six data files are committed. | Record the present protocol/result status without retroactively rewriting hypotheses. |
| `ROADMAP.md` | Pilot experiments are wholly future work. | Two-model 3×5 pilots, ablations, and an H5 2×2 are complete. | Split completed evidence from remaining confirmatory work. |
| `PROJECT_STATE.md` | Next step is n≥20 seeds or unlocking gpt-oss. | gpt-oss n=20 and the full 2×2 were completed. | Replace with third capability level and second task family. |
| Protocol and roadmap | Budget enforcement is described as strict, including USD. | `runtime.py` checks calls/wall before an episode and tokens after a response; it never checks `max_usd`. | Document as a correctness milestone before paid providers. |
| README and ADR 0004 | Replay is described as verifying all evidence. | `replay.py` re-executes evaluations but compares only `passed` and `score`, then checks lineage and the canonical pointer. | Narrow the current claim; plan full evidence/policy verification. |
| ADR 0004 | Per-episode prompt hashes are described as pinned in the manifest. | The manifest stores the template hash; `episode_started`/`proposed` events store episode prompt hashes. | Correct the storage description. |
| `SECURITY.md` | The runtime makes no network calls. | `OllamaProvider` uses HTTP to a configurable local endpoint; tests and the offline provider remain network-free. | State the actual offline/live boundary. |
| `docs/integration_boundary.md` | Architectural seams are presented as fully usable extension points and `RunConfig` as a JSON Schema. | The run loop directly constructs concrete provider/sandbox/evaluator implementations; config is a dataclass JSON representation with no published JSON Schema. | Label present seams and missing injection/registry contracts exactly. |
| Research docs | H5 was absent or described as untested outside its lab note. | `h5-2x2-n20.json` records +0.202 with bootstrap CI [0.093, 0.3095]. | Classify it as registered, partially confirmatory and preserve all caveats. |
| Architecture docs | No boundary separated model inference from CLI coding-agent execution. | Current `Provider` returns model text; Codex/Claude Code/OpenCode own tools, process lifecycle, and workspace effects. | Add `AgentExecutor` and `WorkspaceBackend` as proposed contracts. |

## Claim classification after reconciliation

| Class | Records | Permitted interpretation |
|---|---|---|
| Mechanism demonstrations | deterministic demo; one-seed v1 live comparison; RQ4 replacement archives; first v2 run | The mechanisms execute, reject unsafe candidates, retain state, replay core outcomes, and recover the canonical pointer. No capability superiority claim. |
| Exploratory | gemma3 and gpt-oss n=5 pilots; promotion-history and failed-source ablations; gpt-oss n=20 extension | Hypothesis generation and variance estimates only. The gpt-oss n=20 result does not establish equivalence. |
| Registered, partially confirmatory | H5 2×2, 80 runs | The registered interaction direction is supported on one benchmark/model pair. It is not a clean pre-registration and does not show general stigmergic superiority. |
| Not yet supported | confirmatory H1–H4; H2 comparison; cross-task or third-capability H5 replication | Must remain future work. |

## Implementation gaps discovered during the audit

These are not documentation errors; they are present technical limits to carry
into implementation planning:

- `SCHEMA_VERSION` exists but current events do not carry a schema version.
- Event writes and canonical-pointer writes do not form one atomic transaction.
- Replay does not compare full metrics/reasons, re-run policy decisions, or
  validate every event payload.
- `max_usd` is not enforced, token limits can overshoot by one provider call,
  and there is no concurrency/reservation budget.
- The store models one canonical Python module, not a repository checkpoint.
- Git worktrees isolate files but are not a security boundary.
- No `AgentExecutor`, `WorkspaceBackend`, durable scheduler, human approval
  queue, gateway adapter, or multi-repository control plane exists yet.

## Verification

- `python3.12 -m venv .venv` and `.venv/bin/pip install -e '.[dev]'` completed
  in the worktree.
- `.venv/bin/python -m pytest`: 55 passed in 7.58 seconds.
- `stigdev replay` succeeded for all 10 committed example run directories,
  including the three isolated best-of-N worker stores.
- `git diff --check` reported no whitespace errors.

### Completion review — 2026-09-14

The first-stage draft was reviewed against the unchanged runtime and committed
data. `.venv/bin/python -m pytest` passed all 55 tests in 9.01 seconds; replay
passed for all 10 example stores (56 evaluations). Research records and
hypotheses were not changed. New paper wording avoids claiming equivalence
from a non-significant test or confusing standard deviation with variance.
ADR 0005 now records acceptance of the offline executor/workspace contract
phase; real adapters, scheduling, and integrity v2 remain deferred.
