# Paper outline (draft skeleton — no results exist yet)

**Proposed title:** Persistent Projects, Ephemeral Agents: Evaluator-Gated
Stigmergic Coordination for Continuous Software Evolution

**Venue shape:** systems-for-ML / agents workshop paper first; extend with
paper-tier results for a full submission.

## Abstract skeleton

Context: continuous software evolution is where agent performance collapses
(cite SWE-Milestone). Mechanism: a runtime where finite-lived workers
coordinate only through versioned executable artifacts, lineage, evaluator
evidence, and failure records, behind a strict promotion gate. Claims: (C1)
an open, replayable runtime + benchmark; (C2) controlled comparison of five
coordination conditions at matched budgets — RESULTS TBD; (C3) ablation of
failure-record inheritance — RESULTS TBD; (C4) continuity under worker/
provider replacement — RESULTS TBD.

## Claimed contributions

1. **Runtime + benchmark (implemented):** stigdev — content-addressed
   artifacts, append-only events, versioned evaluators, promotion gate,
   replay/recovery; TrendEvoBench with deterministic offline reference worker.
2. **Experimental framework (partially implemented):** five matched-budget
   conditions as configuration; pinned manifests; separation of construction
   tooling from experimental agents.
3. **Empirical findings: NONE YET.** All comparative numbers below are blanks.

## Sections

1. Introduction — thesis, RQ1–4.
2. Related work — from `related_work.md` (keep the hedges; e.g. SwarmWorld's
   "most reuse beginning through physical observation").
3. Runtime design — Figs 1–2.
4. TrendEvoBench — fixture design, traps, metrics.
5. Experimental setup — conditions, budgets, statistical plan.
6. Results — [BLANK: RQ1 table], [BLANK: RQ2 retention curve], [BLANK: RQ3
   ablation], [BLANK: RQ4 replacement runs].
7. Discussion & threats — from protocol; honesty about toy scale.
8. Limitations: sandbox is not a security boundary; single-artifact projects;
   offline worker is not a capability claim.

## Figures and tables to produce

- Fig 1: runtime loop (observe/propose/evaluate/gate) — exists in README.
- Fig 2: run-store layout + event lifecycle.
- Fig 3: lineage graph of a live-model run [needs pilot runs].
- Table 1: condition matrix with matched-budget fields (from configs).
- Table 2: RQ1 primary metrics per condition [BLANK].
- Fig 4: repeated-failure rate with/without failure memory [BLANK — offline
  mechanism version can be shown, labeled as mechanism demo].
- Table 3: RQ4 replacement outcomes [BLANK].

## Blanks that block submission

Pilot-tier runs (5 conditions x 5 seeds, live model), power analysis from
pilot variance, paper-tier runs, and conditions 1-2-4-5 implementation.
