# Roadmap

Ordered by dependency and evidence value. “Proposed” items are not present
capabilities. ADR 0005 accepts the offline contract phase; broad operational
implementation still requires the decisions listed in that ADR.

## Research track

1. **State and claim reconciliation — done (2026-09-09).** The README,
   protocol, paper outline, project state, and roadmap now distinguish
   mechanism demonstrations, exploratory results, and the partially
   confirmatory H5 result.
2. **Baseline conditions — three of five done.** `artifact_only`,
   `single_persistent`, and `best_of_n` run. Next: `orchestrator` with logged
   delegation, then `full_communication` with a logged message channel. Both
   must preserve matched budgets and fail closed until implemented.
3. **Capability × medium replication.** The H5 2×2 at n=20/cell is complete
   and supports the registered interaction direction on one benchmark/model
   pair. Next: pre-register a third capability level and/or second task family;
   do not generalize from the current model/runtime-confounded two-point test.
4. **H1–H4 evidence.** Existing H1/H3/H4 pilots, ablations, and replacement
   runs are mechanism/exploratory records, not confirmatory findings; H2 has no
   result. Complete the two missing conditions, choose power from pilot
   variance, and run the remaining registered comparisons only with explicit
   live-model approval.
5. **Benchmark breadth.** TrendEvoBench v2 is done (0.30 floor, v1-strategy
   plateau around 0.69, 0.97 train calibration probe). Next: a second task
   family, larger pools, and evidence/citation metrics.

## Kernel correctness track

6. **Run integrity v2.** Version event envelopes, add immutable repository
   checkpoints, make projection recovery explicit, compare complete evidence
   and policy decisions in replay, and preserve v1 run compatibility.
   Design: ADR 0006 (accepted 2026-09-20); precedes item 12. Done 2026-09-20:
   event store v2, task ledger, v1 bridge, replay v2 with the corruption
   matrix. Benchmark runs still write the v1 file store.
7. **Budget correctness — scheduler level done (2026-09-20).** Reservation,
   reconciliation, overshoot, concurrency, and `max_usd` checked before any
   lease live in `stigdev.scheduler`. The research runtime still enforces
   tokens post-response and can overshoot by one call until it runs under the
   scheduler.
8. **Paid provider adapters.** Anthropic/OpenAI behind `Provider` only after
   budget correctness, explicit user approval, and offline mocked tests.
9. **Multi-artifact state.** Generalize the one-module canonical state to a
   content-addressed directory/repository checkpoint.
10. **Stronger sandbox.** Container or equivalent enforcement before running
    untrusted model artifacts or coding agents; worktrees and subprocess `-I`
    are not security boundaries.

## Agentic Engineering OS track

11. **Execution contracts — implemented and verified offline.**
    `AgentExecutor`, `WorkspaceBackend`, deterministic fakes, RunStore evidence,
    and inspection/interruption recovery are separate from model-level
    `Provider`. See `docs/execution_contracts.md` for limits.
12. **Workspace implementation — done (2026-09-20).** `GitWorktreeBackend`
    with exact-base allocation, one-writer leases, ADR 0006 tree checkpoints,
    quarantine, and safe release. Not a security boundary; no executor uses
    it yet (M9).
13. **Durable scheduler — done (2026-09-20).** Task DAGs, leases, retries,
    cancellation, run-level budgets, and restart recovery in
    `stigdev.scheduler`; no priorities, backfilling, or per-task budgets.
14. **Evaluator/policy approvals.** Generalize evidence over repository
    checkpoints and add versioned human approval decisions. Media-side
    fail-closed gates (rights, release, publish) and the channel stage
    machine exist as pure contracts in `stigdev/portfolio.py` (ADR 0007,
    proposed); concept lineage, ecosystem events, and the Truth Firewall in
    `stigdev/ecosystem.py` (ADR 0008, proposed); revenue claim grading,
    policy snapshots, experiment cards, and the commerce order ledger in
    `stigdev/revenue.py` (ADR 0009, proposed); portfolio capacity policy and
    the Model Radar promotion gate in `stigdev/modelradar.py` (ADR 0010,
    proposed).
15. **Multi-channel portfolio governance.** Channel lifecycle, audience
    contracts, format fingerprints, overlap review, the payout reconciliation
    ladder, and the K0-K4 incident kill switch in `stigdev/lifecycle.py`,
    `overlap.py`, `payout.py`, and `incident.py` (ADR 0011, proposed), with a
    synthetic 27-channel regression fixture and `docs/anti-evasion.md`.
16. **Node profiles and commissioning.** Resource classes, per-node ceilings,
    fail-closed Metal admission, and a read-only host check in `stigdev/node.py`
    plus `scripts/commission_node.py` (ADR 0012, proposed). Wiring admission
    into the scheduler waits on a worker daemon.
17. **Control-plane events and projections.** Expose authenticated, idempotent
    commands and read-only status without direct store/workspace access.
18. **External adapters.** Integrate Orca, Slack, and Hermes one at a time only
    after the generic contracts are approved and tested. No live external test
    without explicit approval.
19. **Private testbed and extraction review.** Validate from the private
    `social-trend-agent` repository, then create a separate deployable control
    plane only if ADR 0005 extraction criteria are met.

See `docs/implementation_plan.md` for worktrees and verification gates.
