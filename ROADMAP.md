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
   Design: ADR 0006 (accepted 2026-09-20); precedes item 12. Kernel scope
   done 2026-09-20 (event store v2, task ledger, v1 bridge); replay v2 and
   the corruption matrix remain.
7. **Budget correctness.** Add reservation/reconciliation and concurrency
   budgets. Enforce USD before adding paid providers; current token enforcement
   is post-response and can overshoot by one call.
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
12. **Workspace implementation.** Implement GitWorktreeBackend with exact-base allocation,
    one-writer leases, checkpoints, quarantine, and safe release.
13. **Durable scheduler.** Add task DAGs, leases, retries, cancellation,
    hierarchical budgets, and restart recovery.
14. **Evaluator/policy approvals.** Generalize evidence over repository
    checkpoints and add versioned human approval decisions.
15. **Control-plane events and projections.** Expose authenticated, idempotent
    commands and read-only status without direct store/workspace access.
16. **External adapters.** Integrate Orca, Slack, and Hermes one at a time only
    after the generic contracts are approved and tested. No live external test
    without explicit approval.
17. **Private testbed and extraction review.** Validate from the private
    `social-trend-agent` repository, then create a separate deployable control
    plane only if ADR 0005 extraction criteria are met.

See `docs/implementation_plan.md` for worktrees and verification gates.
