# ADR 0006: Durable event store and run-integrity v2

Status: proposed (2026-09-20). Resolves deferred decisions 1 and 2 of ADR 0005
for milestone M6. Design only; no runtime, test, or experiment data changes
accompany this ADR.

## Context

ADR 0005 deferred two decisions until the first operational milestone: (1)
whether the first scheduler is single-process/file-backed or starts on a
transactional database, and (2) the event-schema v1 compatibility and
migration policy.

The current `RunStore` (`stigdev/store.py`) is a single-writer research store,
verified on `6dd99f7` (135 tests, all example replays pass):

- `append_event` opens `events.jsonl` in append mode with no lock, no
  idempotency key, and no stated fsync policy; two writers interleave silently.
- `set_canonical` rewrites `canonical.json` with a plain `write_text`; a crash
  mid-write leaves a torn pointer, and there is no compare-and-swap.
- Benchmark events carry `seq`, `type`, `ts`, and a flat payload. Only the M4
  execution events add `execution_version` and `caused_by_seq`; there is no
  event identity, schema version, or correlation metadata for the rest.
- `recover_executions` must be called after the previous writer has stopped
  and cannot distinguish a crashed writer from a slow one; there is no lease.
- Redaction is a forbidden-value check on M4 execution metadata
  (`_public_strings`), not a store-boundary policy.

These properties are acceptable and documented for reproducible
single-process research runs. They are not acceptable for a long-running
control plane in which many logical agents share one store, tasks are retried
after crashes, and committed evidence must be exactly-once.

## Decision

### Transaction model: stdlib SQLite in WAL mode, one writer per store

- The reference `EventStore` implementation uses `sqlite3` from the standard
  library with `journal_mode=WAL`, one database file per store root
  (`<root>/store.sqlite`), a single write connection owned by the scheduler
  process, and any number of read-only connections for projections and replay.
- `synchronous=NORMAL` is the default (consistent after power loss; the last
  committed transactions may roll back) and is recorded in the manifest;
  `FULL` is available where the deployment requires it.
- Stdlib-only holds (PROJECT_STATE decision 1). No server database, no ORM.
- Every write that must be observed together (event append, projection update,
  pointer compare-and-swap) runs in one transaction.

### Envelope v2

Every event row carries `schema_version` (2), `store_id`, `run_id`,
`event_id` (random 128-bit hex), `seq` (per-store, monotonic, assigned by the
writer), `type`, `ts` (UNIX seconds), `causation_id` (an `event_id` or null),
`correlation_id` (task/attempt lineage), `idempotency_key` (nullable), and
`payload` (a JSON object).

The M4 rule becomes a store rule: payloads never contain raw instructions,
environment values, workspace locators, logs, or exception text. Existing
type namespaces stay; execution events keep `execution_version`; scheduler
and policy events arrive with M7/M8 under their own namespaces.

### Idempotent append and exactly-once commit

- `UNIQUE(store_id, idempotency_key)` where the key is present. Appending an
  event whose key already exists returns the stored event and changes nothing,
  so retried task completions and duplicate deliveries commit once.
- Canonical and projection pointers live in a `pointers` table with a
  `version` column. Updates are `UPDATE ... WHERE version = ?`; zero affected
  rows is a conflict, never a silent overwrite. The v1 file pointer gets
  temp-file + `os.replace` as the compatibility minimum.

### Task and attempt state as a reducer

- Task and attempt state is a pure reduction over events; projections may
  cache it but are always rebuildable from the log.
- Leases are event-sourced (`lease_acquired`, `lease_renewed`,
  `lease_expired`, `lease_released`) with holder, expiry, and last heartbeat.
  A terminal event for an attempt must cite a currently valid lease event as
  its fencing token or it is rejected.
- Restart recovery scans attempts whose lease expired without a terminal
  event, appends `execution_interrupted` caused by the last lease event, and
  re-enqueues them per retry policy. This replaces "call only after the former
  writer is stopped".

### Checkpoint shape: content-addressed tree

- Artifacts generalize from one `.py` blob to blob and tree objects addressed
  by sha256 of canonical bytes. A checkpoint is a tree hash plus the producing
  attempt.
- This fixes the workspace checkpoint shape that M5 needs, so M6 no longer
  waits on M5: the GitWorktreeBackend produces trees; it does not define them.

### v1 compatibility

- Committed v1 run directories are never rewritten. A read-only v1 reader
  remains and `stigdev replay` keeps working on them unchanged.
- A non-destructive importer (v1 directory to a new store) is tested for
  equality of replayed evaluations. It is a tool, not a migration of published
  evidence.
- Research runs may keep the v1 file store until M7. Anything scheduled,
  leased, or approved requires the reference SQLite store.

### Redaction at the store boundary

- The forbidden-value check moves into `EventStore.append` for all namespaces,
  configured with the transient values of the current request. Tests assert
  that instructions, environment values, locators, and stderr never appear in
  events, artifacts, or manifests.
- This remains defense in depth with the M4 limits: it is not a secret
  detector.

### Ordering

M6 (this ADR) precedes M5. Operational order becomes M6, M5, M7, M8, as
recorded in `docs/implementation_plan.md`.

## Acceptance for the M6 gate

- A duplicate append with the same idempotency key commits one event, and a
  simulated duplicate task completion changes canonical state once.
- Killing the writer process mid-transaction leaves a store that opens,
  replays, and recovers the orphaned attempt as `interrupted`.
- A late terminal event from a writer whose lease expired is rejected.
- A pointer compare-and-swap conflict is surfaced, not overwritten.
- Committed v1 examples replay unchanged; importer output replays equal.
- No configured transient value appears anywhere in the store bytes.
- A queue simulation with more logical tasks than fake executor slots
  completes with exactly-once commits and no live model.
- Replay compares complete evaluator evidence and re-runs policy decisions
  (ROADMAP item 6).

## Consequences

Positive: exactly-once commits, crash recovery without operator ordering
assumptions, one transaction for event plus projection plus pointer, an
unchanged stdlib-only footprint, and untouched published evidence.

Costs: two store implementations coexist until M7. A single write connection
is a throughput ceiling; the upgrade path is one database file per run with
the scheduler fanning out. WAL requires every connection on one host, which
suits a local-first single node and rules out a distributed store by design.
The `synchronous` setting trades durability for latency and must be stated in
the manifest.

## Alternatives considered

- **Keep JSONL with file locks and fsync.** Rejected: no idempotency index, no
  compare-and-swap, torn-write detection stays heuristic, and every projection
  is a full scan.
- **PostgreSQL.** Rejected: an operational dependency for a local-first
  single-node kernel and a departure from the stdlib-only decision.
- **Third-party embedded stores (LMDB, RocksDB).** Rejected: not stdlib.
- **Version only the execution namespace.** Rejected: scheduler and policy
  events need the same identity, causation, and idempotency guarantees.
