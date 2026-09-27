# ADR 0010: Model Radar promotion gate and portfolio capacity policy (public, generic)

Status: proposed (2026-09-27). Implemented offline in `stigdev/modelradar.py`
and additions to `stigdev/portfolio.py`; pending user review. No model is
loaded, no scheduler consumes these yet.

## Context

The operator's target, stated 2026-09-27, is a fully autonomous OS: the
operator supplies plans through a frontier model, the OS turns them into
channels and monetized services, publishes long and short form on a fixed
cadence 24/7 at above-average quality, and a separate agent keeps researching
and swapping the open-source models that run it. The operator only supervises
and checks errors.

Two inputs were applied here:

1. A capacity analysis of the M5 Ultra (30-core CPU, 64-core GPU, 96 GB) at
   70% allocation: image+TTS media automation is bounded by generation and
   human review, not encoding. Economic optimum 8–10 channels, sustainable
   maximum 12, absolute 15; a healthy end state is 2 `scale` winners, 4–6
   `maintain`, 2–4 `pilot`. Human review above 15 h/week or any policy
   incident blocks expansion. Adding channels never fixes a failing format.
2. Blueprint v2 §10.2–10.3 and §22.6: attempts record a model snapshot; a new
   model is discovered automatically but promoted only through
   `discovered -> quarantined -> licensed -> smoke -> private_eval -> shadow ->
   canary_5 -> canary_25 -> canary_50 -> full`, with strict quality gain on
   the same suite, memory and p95 latency inside budget, human edit time not
   worse, at least 20 shadow artifacts, zero critical regressions, cleared
   commercial license, a named approver, and instant rollback.

The reconciliation of 2026-09-20 listed "synthetic model benchmark harness"
and "model promotion and rollback reproducible" as absent. The pasted
operating principles (verification receipts before trust, evals run like unit
tests, make the easy path the correct path through architecture and CI, do
not start with 100 agents) match this repository's existing invariants.

## Decision

### `stigdev/portfolio.py`

- `PortfolioPolicy(max_scale, max_active, max_pilot, max_review_hours_per_week)`
  with `DEFAULT_POLICY = (2, 12, 4, 15.0)`. Limits are data; a private
  instance passes its own. `MAX_SCALE_CHANNELS` is now an alias of
  `DEFAULT_POLICY.max_scale`.
- `PortfolioEvidence(review_hours_per_week, policy_incidents)`.
- `register_channel(plan, portfolio, evidence, policy)` -> `GateDecision`
  ("register-gate/v1"): duplicate id, active limit (stages other than
  `retire`), pilot limit (`hypothesis`, `private_pilot`, `public_pilot`),
  review hours, incidents. All reasons at once.
- `advance_stage(..., policy=DEFAULT_POLICY)` reads `policy.max_scale`.
- Commerce channels use the `commerce_lab` role from ADR 0009 (owner
  reference required). Music channels stay `ip_engine`; affiliate revenue
  never attaches to them.

### `stigdev/modelradar.py`

- `ModelSnapshot(alias, model_id, revision, runtime, quantization,
  prompt_bundle, license_state)`; `license_state` in
  `unknown | restricted | commercial_ok`.
- `BenchmarkResult(model_id, revision, suite_version, quality,
  peak_memory_gb, p95_latency_s, human_edit_minutes, shadow_artifacts,
  critical_regressions)`.
- `PromotionBudget(max_peak_memory_gb, max_p95_latency_s,
  min_shadow_artifacts=20, min_quality_gain=0.0)`.
- `model_promotion_gate(current, candidate, snapshot, budget, approved_by)`
  -> `GateDecision` ("model-promotion/v1"). `current is None` seeds an alias
  and still requires license, budget, shadow count, and approval.
- `ROLLOUT_STAGES`, `next_rollout_stage` (strictly sequential),
  `rollback_stage` (any rung -> `quarantined`).

## Not applied here, on purpose

- Revenue figures, channel names, site domains, and the staged revenue
  milestones from the capacity analysis are private-instance data (v3 §12).
  Only the structural limits became defaults.
- The 70% resource split, memory ceiling (58–62 GB), and per-tier
  concurrency table belong to the private node profile (reconciliation
  2026-09-20, Blueprint §9.2). The public scheduler on the unmerged stack has
  no node concept yet.
- Web KPIs (`video_to_site_rate`, `question_to_new_video_rate`, ...) are
  `AudienceSignal` metrics under ADR 0008; no new schema needed.

## Gap to the autonomy target

What exists on `main` plus this working tree: typed contracts, fail-closed
gates (rights, release, publish, register, scale, canon, model promotion),
deterministic fakes, replay, tests. What full autonomy still needs, in the
order the Blueprint and the pasted principles both prescribe:

1. Merge the durable kernel stack (event store, ledger, scheduler).
2. `Evaluator` / `PolicyGate` protocols injected into the run loop.
3. Restricted local process executor that returns verification receipts
   (logs, hashes, evaluator evidence) before anything is trusted.
4. Local model gateway with aliases and the Model Radar loop consuming this
   gate; evals run in CI like unit tests.
5. Media workers (research, script, image, TTS, render) behind the workflow
   DSL.
6. Connectors (YouTube, web, app) strictly behind human approval.

Scale agents only after step 3 proves a receipt-backed loop locally.

## Failure behavior

Invalid records raise `RadarError` / `PortfolioError`. Gates return every
blocking reason; no partial promotion or registration.

## Acceptance tests

`tests/test_modelradar.py` and the policy block of `tests/test_portfolio.py`.

## Deferred

Benchmark suite runner, model discovery sources, canary traffic split,
rollback automation, node resource profiles.
