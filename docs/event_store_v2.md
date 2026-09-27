# Durable event store v2 and task ledger

Status: M6 kernel scope implemented and verified offline on 2026-09-20 under
ADR 0006. 164 tests pass (135 existing + 29 new); all committed example runs
replay unchanged. Replay v2 (complete evidence and policy-decision comparison)
and the remaining corruption matrix stay open in `docs/implementation_plan.md`.

## Public interfaces

Standard-library only (`sqlite3`, dataclasses). No CLI commands were added.

| Module | Interface |
|---|---|
| `stigdev.eventstore` | `SqliteEventStore.create(root, store_id=..., synchronous="NORMAL")`, `open(root)`, `close()`, `meta()` |
| `stigdev.eventstore` | `transaction()` context manager; `append(type, payload, run_id=..., causation_id=, correlation_id=, idempotency_key=, ts=, forbidden=) -> Event` |
| `stigdev.eventstore` | `events(type=, run_id=, after_seq=)`, `event(event_id)`, `by_idempotency_key(key)` |
| `stigdev.eventstore` | `put_blob(bytes, kind=, forbidden=) -> digest`, `get_blob(digest)`, `blobs(kind=)`, `put_tree({path: digest}) -> digest`, `get_tree(digest)` |
| `stigdev.eventstore` | `pointer(name) -> (version, value) or None`, `set_pointer(name, value, expected_version=) -> version` |
| `stigdev.ledger` | `TaskLedger(store, run_id=...)`: `submit`, `acquire`, `renew`, `finish`, `recover`, `state()`; pure `reduce_tasks(events)` |
| `stigdev.v1import` | `import_run(run_dir, store) -> event count`, `export_run(store, run_id, dest) -> Path` |

### Envelope v2

`Event(seq, schema_version=2, store_id, run_id, event_id, type, ts,
causation_id, correlation_id, idempotency_key, payload)`. `seq` is per-store
and monotonic across reopen; `event_id` is 32 hex characters; `payload` must be
a JSON object. `forbidden` values raise `RedactionError` when they appear in
payload keys or values or in blob text: values shorter than eight characters
match whole strings only, longer values also match as substrings.

### Store semantics

- One `store.sqlite` per store root, `journal_mode=WAL`; `synchronous`
  (`NORMAL` default, `FULL` optional) is recorded in `meta`.
- `append` with an idempotency key that already exists returns the stored event
  and writes nothing.
- `causation_id` must name an existing event; otherwise `StoreIntegrityError`.
- `set_pointer` is compare-and-swap. `expected_version=0` means the pointer must
  not exist; any mismatch raises `PointerConflict`.
- Blobs and trees are sha256 content-addressed; reads verify the hash and raise
  `StoreIntegrityError` on tampering. Tree paths are relative and may not
  contain `..`; trees may only reference stored blobs.
- `transaction()` is all-or-nothing; nested scopes join the outermost one. An
  uncommitted transaction is lost when the writer process dies (tested with
  `SIGKILL`), and the store reopens with a continuous sequence.

### Ledger semantics

Event types: `task_submitted`, `lease_acquired`, `lease_renewed`,
`lease_expired`, `attempt_finished` (status `success`, `failed`, `timed_out`,
`cancelled`, or `interrupted`). Attempt ids are `<task_id>:<n>`.

- `submit` is idempotent per task id.
- `acquire` leases a pending task for `ttl` seconds from the caller-supplied
  `now`. If the task holds an expired lease, that attempt is recovered first
  (`lease_expired`, then `attempt_finished` with `interrupted`) in the same
  transaction. The new lease event is caused by the task's last event, which
  gives retry lineage.
- `renew` and `finish` require the attempt's current, unexpired lease event
  (fencing token). A duplicate `finish` from the same lease returns the stored
  event; a late `finish` from an expired or superseded lease raises
  `LeaseError`.
- `recover(now)` expires every stale lease, marks the attempts interrupted, and
  returns the appended events; running it again appends nothing.
- `interrupted` returns the task to `pending`; other terminal statuses finish
  it. There is no attempt cap or retry policy (M7).
- `reduce_tasks` is a pure function over events and fails closed on unknown
  tasks, duplicate submissions, events for inactive attempts, and unknown
  terminal statuses.

### v1 bridge

`import_run` reads a v1 run directory without modifying it: artifacts are
hash-checked and stored as `py` blobs, every event is appended with its
original type and `ts`, payload `v1_seq` plus the original fields, idempotency
key `v1:<run_id>:<seq>`, and `caused_by_seq` mapped to `causation_id`; the
canonical pointer and manifest become pointers. The import is one transaction
and re-importing is a no-op. `export_run` writes the v1 layout back; for the
committed sample run the exported `events.jsonl` and `canonical.json` are
byte-identical and `stigdev replay` reports the same result.

`RunStore.set_canonical` (v1) now writes through a temporary file and
`os.replace`, so a crash mid-write cannot leave a torn pointer.

## Verification (2026-09-20)

```bash
.venv/bin/python -m pytest                     # 164 passed
.venv/bin/stigdev replay examples/sample_run   # ok: true, checked: 9
```

## Limits

- Not a security boundary and not a distributed store. One writer per store is
  a deployment rule; SQLite serialises a second writer for up to
  `busy_timeout` (5 s) and then fails.
- `synchronous=NORMAL` is consistent after power loss but the last committed
  transactions may roll back; use `FULL` where that matters.
- Redaction is a forbidden-value check, not a secret detector.
- The ledger takes `now` from the caller; it has no clock, heartbeat transport,
  cancellation transport, DAG, budgets, or retry limits.
- `lease_released` from ADR 0006 is not implemented; a worker that gives up
  records `finish(..., "cancelled")`.
- Benchmark runs still use the v1 file store. Replay v2 (complete evidence and
  policy-decision comparison), corruption tests for events, metrics, reasons,
  and policy decisions on the v2 store, and budget reservation remain open.
- `export_run` assumes one v1 run per store.
