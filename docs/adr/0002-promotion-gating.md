# ADR 0002: Evaluator-gated promotion

Status: accepted (2026-08-30)

## Context

Unconstrained self-modification makes results unauditable and lets plausible
but wrong changes accumulate. The contribution is a *controlled* runtime.

## Decision

Candidates never become canonical directly. A versioned evaluator
(`trendevobench.select` v1) executes the candidate in the sandbox against
versioned fixtures and emits typed `Evidence` (hard checks + deterministic
metrics + composite score). A versioned policy (`strict-improve/v1`) promotes
iff hard checks pass and the composite score strictly improves on the current
canonical score. Everything else becomes a `rejected` event carrying the
evidence and reason.

Evaluator and policy versions are pinned in every run manifest and event; a
replay refuses to compare scores across evaluator versions.

## Consequences

- Canonical state can only improve under the pinned evaluator — regressions on
  the training signal are structurally impossible; holdout drift remains
  measurable and honest.
- Strict improvement rejects ties, biasing toward smaller canonical churn;
  plateau escapes need policy evolution (e.g. epsilon schedules, multi-metric
  dominance) — deliberately out of MVP scope.
- The gate is the single place where trust enters the system; changing it is a
  versioned, logged act rather than an emergent behavior.
