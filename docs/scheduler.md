# Durable scheduler (M7)

Status: implemented and verified offline on 2026-09-20. 200 tests pass (12
new). `stigdev.scheduler.Scheduler` runs on top of `TaskLedger` (M6) and the
v2 event store (ADR 0006). Every decision is a pure reduction over events, so
a restarted scheduler on the same store resumes with the same queue and the
same remaining budget.

## Public interface

| Call | Behavior |
|---|---|
| `Scheduler(store, run_id=, budget=Budget(...), started_at=, lease_ttl=900)` | records `scheduler_configured` once per run (idempotent); a different budget for the same run raises `SchedulerError` |
| `submit(task_id, depends_on=(), max_attempts=1, reservation=Reservation())` | dependencies must already be submitted (no forward references, hence no cycles); a reservation larger than any cap is refused before anything is recorded |
| `ready()` | pending tasks whose dependencies all `succeeded`, in submission order; empty once the run is cancelled or exhausted |
| `acquire_next(holder, now=) -> Lease or None` | leases the head ready task if concurrency and its reservation fit; `None` while capacity is held by active reservations |
| `finish(lease, status, now=, usage=Usage(...), result=None)` | records the outcome once (duplicates return the stored event), decides retry, reconciles the reservation |
| `recover(now=)` | expires stale leases (ledger) and releases their reservations with zero usage; idempotent |
| `cancel(task_id, now=)` / `cancel_run(now=)` | idempotent terminal events; no further leases for the task or run |
| `state() -> ScheduleState` | tasks (status, attempts, reservation), active reservations, reserved/used/remaining per dimension, leased count, `exhausted`, `cancelled` |

`Budget(max_calls, max_tokens, max_usd=0.0, max_wall_seconds, max_workspaces,
max_concurrency=1)`; `None` means uncapped. `max_usd` defaults to zero, so a
paid reservation cannot even be submitted until a run is explicitly funded.
`Reservation(calls, tokens, usd, wall_seconds, workspaces)` is the per-attempt
estimate; `Usage(calls, tokens, usd, wall_seconds)` is what the attempt
actually consumed.

## Events

`scheduler_configured`, `budget_reserved` (caused by `lease_acquired`),
`budget_reconciled` (caused by `attempt_finished`, carries reservation, usage,
and overshoot), `budget_exhausted` (once per run, first dimension),
`task_cancelled`, `run_cancelled`. Task events come from the ledger;
`attempt_finished` carries `retry` set by the scheduler.

## Rules

- **Readiness:** submission order, head-of-line only. The head task waits when
  its reservation does not fit the remaining budget; smaller tasks are not
  backfilled ahead of it.
- **Retry:** `failed`, `timed_out`, and `interrupted` re-queue while
  `attempts < max_attempts` and the task and run are not cancelled;
  `cancelled` is always terminal. A task whose dependency ended `failed`,
  `cancelled`, or `blocked` is `blocked`.
- **Reservation:** reserved at lease, reconciled at finish or recovery. Usage
  above the reservation is recorded as overshoot and counts against the cap.
- **Exhaustion:** hard, once per run, when the head task cannot fit
  `cap - used` even with every active reservation released, when the wall
  deadline (`started_at + max_wall_seconds`) has passed, or when its wall
  reservation exceeds the time left. No lease is issued afterwards.
- **Concurrency:** `max_concurrency` bounds active leases; `max_workspaces`
  bounds active workspace reservations.
- **Idempotency:** duplicate completions, repeated cancels, repeated recovery,
  and re-configuration are no-ops by idempotency key.

## Limits

- One scheduler process per run; the store's one-writer rule applies.
- Wall time is checked against the clock passed by the caller; the scheduler
  has no clock or timer of its own and does not preempt running attempts.
- No priorities, no backfilling, no per-task budgets below the run level, no
  fairness between runs.
- The research runtime (`stigdev.runtime`) still enforces tokens after each
  provider call and can overshoot by one call; it does not yet run under this
  scheduler.
- Paid provider adapters remain out of scope; the scheduler only guarantees
  that an attempt cannot start without USD reserved under `max_usd`.
