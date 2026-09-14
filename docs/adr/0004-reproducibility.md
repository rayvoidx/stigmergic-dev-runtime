# ADR 0004: Reproducibility and audit

Status: accepted (2026-08-30)

## Context

Research claims about coordination mechanisms are worthless if runs cannot be
re-derived. Every material transition must be reproducible and auditable.

## Decision

- **Determinism by construction**: offline provider seeded; evaluator metrics
  contain no timings; artifact code avoids Python's randomized `hash()`;
  fixtures are committed and hashed into the manifest; sort orders are total
  (score desc, id asc).
- **Pinning**: the run manifest and `run_started` event record exact provider
  and model id (never a moving alias), effort/temperature/max-output, prompt
  template hash, seeds, budgets (episodes, calls, tokens, USD, wall-clock),
  fixture hashes, evaluator/policy versions, and software environment (Python,
  platform, package version). Per-episode prompt hashes live in
  `episode_started`/`proposed` events rather than the manifest.
- **Replay as verification**: `stigdev replay` re-executes every recorded
  evaluation from stored bytes, compares the hard-check pass flag and score,
  and re-checks the promotion chain and canonical pointer; the e2e suite
  additionally proves bit-for-bit rerun equality of the demo (modulo
  wall-clock fields). Comparing every metric/reason and re-running policy
  decisions is a documented follow-up, not a current capability.
- **Costs are data**: token/USD/call counts are recorded per episode and
  summed; the offline provider must report zeros.

## Consequences

- Wall-clock timestamps in events are informational only; nothing compares
  them.
- Live-model runs will not be bit-reproducible; for them, replay still verifies
  the score-bearing evaluation outcome and chain integrity, which is the
  current auditable core.
- A tampered artifact or canonical pointer is detected by replay (covered by
  tests). Tampering with un-compared evidence fields is not yet detected.
