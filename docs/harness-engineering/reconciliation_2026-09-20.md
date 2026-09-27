# Local-First Architecture v1: reconciliation with repository state

Date: 2026-09-20. Companion to
`Stigmergic_Agentic_OS_Local_First_Architecture_v1.md` (the "venture doc"
below). Design-level only: no runtime, test, or experiment data changed.

## Verification basis

| Ref | What | Result |
|---|---|---|
| `main` @ `6dd99f7` | M0 + M4 merged (PR #1, PR #2) | 135 passed |
| `feat/task-scheduler` @ `6a40900` | unmerged stack: ADR 0006 → M6 event store/ledger/v1 bridge → replay v2 → M5 GitWorktreeBackend → M7 scheduler (5 commits, all dated 2026-09-20, 25 files, +3,179 lines, 65 new tests) | 200 passed in a detached scratch worktree |

Stack order, each branch containing the previous:
`docs/adr-0006-event-store` ⊂ `fix/run-integrity-v2` ⊂ `fix/replay-v2` ⊂
`feat/workspace-backend` ⊂ `feat/task-scheduler`. All five are on `origin`;
none is merged; `PROJECT_STATE.md` on `main` does not mention them.

## Placement (settled 2026-09-28)

The venture doc was originally requested at `docs/harness-engineering/` in this
public repository. By its own §0 table and §7 lists, the personal-instance
material it contains — hardware plan, Apple account layout, revenue targets,
portfolio rules, commissioning schedule — belongs on the private side, and it
now lives in the private `saeos-private` repository under `docs/design/`.
The same call was applied to the SAEOS Media Foundry design documents and the
YouTube portfolio strategy versions, which had been sitting untracked here.

This reconciliation stays public: it measures the public kernel against its own
code, which is what this repository should carry. The section-level
classification at the end is kept as the record of how the line was drawn.

## §7 "problems to fix first in the public code"

| # | Venture doc claim | `main` | Stack | Remaining |
|---|---|---|---|---|
| 1 | provider/evaluator/policy hard-coded, DI incomplete | True. `Provider` and `Sandbox` are Protocols; `runtime.run` still constructs `TrendSelectEvaluator`, `StrictImprovementPolicy`, `SubprocessSandbox` directly (`stigdev/runtime.py:148`, `:243`). No `Evaluator` or `PolicyGate` Protocol. | Unchanged | Open |
| 2 | JSONL store has no transaction, lock, or idempotency | True | `SqliteEventStore`: WAL, one writer, unique idempotency key, nested all-or-nothing transactions, SIGKILL mid-transaction test | Research runs still write v1 JSONL |
| 3 | canonical pointer update not atomic | True | v1: temp file + `os.replace`; v2: compare-and-swap `set_pointer` | Done on stack |
| 4 | `SubprocessSandbox` is not a security boundary | True, documented | Unchanged, by design | ADR 0005 deferred decision 3 (isolation backend) still open |
| 5 | no generic task state, lease, heartbeat, cancel, restart recovery | True | `TaskLedger` (lease event as fencing token, `renew`, `recover`, pure reducer) + `Scheduler` (retry, cancel, restart from store) | No heartbeat transport; no cancellation of a running process; ledger takes `now` from the caller |
| 6 | text completion and workspace agent execution not separated | **Stale.** Done in M4 (`stigdev/executor.py`, `workspace.py`, `execution.py`), merged in PR #2 | — | Done on `main` |
| 7 | event schema version and redaction not enforced | True for v1 | envelope v2 `schema_version=2`; `RedactionError` at `append` and `put_blob` | Forbidden-value check only, not a secret detector; v1 research events stay flat |

## §11 window 1 (2026-09-20 → 10-03, "design and public contracts")

| Item | Status |
|---|---|
| Public/private classification table | §7 lists exist in the venture doc; section classification of the doc itself is added below |
| ADR: OS scope, AgentExecutor, WorkspaceBackend | ADR 0005 accepted on `main` |
| ADR: event store | ADR 0006 proposed on `docs/adr-0006-event-store`; the stack's `PROJECT_STATE.md` and `ROADMAP.md` record it as accepted by user direction; `main` has no ADR 0006 |
| Generic executor/workspace contracts + deterministic fakes in the public repo | Done on `main` (M4) |
| Keep research-runtime regression tests | 135 on `main`, 200 on the stack; all 10 example replays clean on both |
| Fix the Hermes adapter interface before coupling | Not started. `GatewayAdapter` is a sketch in `docs/agentic_engineering_os_architecture.md`; M8 (`feat/control-plane-events`) is the public prerequisite |

## §11 window 2 (2026-10-04 → 10-17, "durable kernel")

Already implemented on the stack, ahead of the doc's window:

| Item | Where |
|---|---|
| SQLite WAL event store, idempotency, optimistic version | `stigdev/eventstore.py` |
| task/attempt reducer and crash recovery | `stigdev/ledger.py` (`reduce_tasks`, `recover`; SIGKILL test) |
| artifact tree and secret redaction | `put_tree`, `tree_digest`; `RedactionError` |
| timeout, cancellation, retry, lease-expiry tests | `tests/test_scheduler.py`, `tests/test_ledger.py` |
| queue simulation of 20–25 logical agents without inference | `test_queue_simulation_more_tasks_than_slots_commits_exactly_once`: 24 tasks, 2 slots, one crash, one duplicate delivery |

## §11 M4 acceptance criteria

| Criterion | Status |
|---|---|
| Duplicate task execution commits once | Met on stack (idempotency key; duplicate `finish` returns the stored event) |
| Orphaned attempt recovered after process kill | Met on stack (`recover`; SIGKILL test) |
| No secret in event, log, or artifact | Partial: forbidden-value redaction at the store boundary; not a detector |
| 20–25 logical agents processed by queue, not memory-resident | Met on stack (24-task / 2-slot simulation) |
| Dangerous unattended action auto-denied | Not met: no `PolicyGate`, no approval matrix (ADR 0005 deferred decision 4; venture doc §10 tiers A–E) |
| Model promotion and rollback reproducible | Not met: no Model Radar component in the public repo |
| Zero external paid inference calls | Met by construction: `Budget.max_usd=0` rejects a paid reservation at `submit`; tests never touch the network |

## §7 "keep in the public repository" checklist

| Item | Present |
|---|---|
| `AgentExecutor`, request/result types | `main` |
| `WorkspaceBackend`, ref/state types | `main` |
| versioned event envelope + redaction | stack |
| transactional `EventStore` Protocol + SQLite reference | stack has `SqliteEventStore` only; no Protocol |
| generic artifact/blob/tree store | stack |
| `Evaluator`, `PolicyGate`, evidence contracts | concrete classes only; no Protocols (problem 1) |
| task/attempt reducer, replay, crash recovery | stack |
| generic resource budget and node capability | budget on stack (`Budget`, `Reservation`, `Usage`); node capability absent |
| deterministic fake executor/workspace/provider | `main` |
| synthetic model benchmark harness | absent |
| generic license/hash/format checks | absent |
| Git worktree; restricted local process executor | worktree on stack; process executor absent |

## §13 implementation order

| # | Step | Status |
|---|---|---|
| 1 | Public contract: executor + workspace + fakes | Done (`main`) |
| 2 | Durable kernel: typed events + SQLite + reducer + recovery | Done (stack, unmerged) |
| 3 | Private skeleton: scheduler + node registry + resource governor | Generic DAG/lease/retry/budget scheduler is public on the stack; node registry, priorities, `metal lease`, and the heavy-job queue (venture doc §4) are absent and private-scoped |
| 4 | Hermes adapter | Not started; needs M8 first |
| 5–9 | M4 end-to-end, Model Radar v0, Venture Portfolio v0, M5 commissioning, first vertical | Private-instance work; not in this repository |
| 10 | Selective upstream | Standing rule |

## Conflicts between the venture doc and repository documents

Recorded, not resolved (AGENTS.md: do not silently choose one document).

1. **Scheduler placement.** Venture doc §7 lists "scheduler priorities,
   lease, retry, real node registry" as private; `docs/implementation_plan.md`
   M7 puts a generic scheduler in the public kernel, and the stack implements
   it there. Consistent reading: generic DAG/lease/retry/budget public;
   priorities, node registry, resource governor private. Needs one explicit
   line in ADR 0005 or ADR 0006.
2. **Baseline stack naming.** Venture doc §2 fixes Hermes, OpenCode, Ollama,
   MLX, and llama.cpp as the baseline; ADR 0005 calls them integration
   targets whose adapters live privately. Compatible only if §2 is read as a
   private-instance choice.
3. **Problem 6 is stale** (table above); the venture doc predates the M4
   merge on that point.
4. **ADR 0006 status** differs between `main` (absent) and the stack
   (accepted). Merging the stack resolves it; not merging leaves it proposed.
5. **Node and Metal resources.** Venture doc §4 assumes a `metal lease`, an
   exclusive heavy-job queue, and per-node profiles. `stigdev.scheduler` has
   no node concept, only `max_concurrency` and `max_workspaces`.

## Section classification of the venture doc

| Section | Class | Reason |
|---|---|---|
| 0 conclusion, naming table | public-safe | naming and boundary only |
| 1 goals and non-goals | mixed | revenue-concentration goal is private-instance |
| 2 system diagram, roles, baseline stack | mixed | role split generic; stack choices private-instance |
| 3 devices and trust zones | private | hardware; company/personal boundary |
| 4 agent and model resource model | mixed | logical-agent vs model-pool principle generic; profiles and limits private |
| 5 revenue engine | private | scoring, allocation, targets |
| 6 Model Radar | mixed | pipeline generic; sources, golden tasks, thresholds private |
| 7 repository boundary | public-safe | this is the boundary itself |
| 8 Apple accounts | private | |
| 9 monitors and storage | private | |
| 10 permission tiers A–E | public-safe | generic policy classes; maps onto `PolicyGate` |
| 11 M4 simulation plan | mixed | acceptance criteria generic; dates and device private |
| 12 M5 commissioning | private | |
| 13 implementation order | public-safe | |
| 14 success metrics | mixed | system and engineering metrics generic; business metrics private |
| 15 final judgment | private | purchase and account decisions |

## Decisions

1. **Where the venture doc lives.** Keep the whole doc here (public), or keep
   only the public-safe sections here and move the rest to
   `stigmergic-agent-control-plane`. Nothing is committed yet.
2. **Merge the stack.** One PR from `feat/task-scheduler` carries all five
   commits; review order M6 → replay v2 → M5 → M7. Until merged, `main` stays
   at M4 and every "Done (stack)" row above is unreviewed.
3. **Next public-kernel item after the merge**, recommended order:
   1. `Evaluator` and `PolicyGate` Protocols with injection in `runtime.run`
      (problem 1). Unblocks the §10 approval tiers and Model Radar evidence
      contracts.
   2. M8 command/status API with a `GatewayAdapter` Protocol and a CLI fake
      (window 1's last item; Hermes prerequisite).
   3. Restricted local process executor, the first real `AgentExecutor`;
      needs ADR 0005 deferred decision 3 (minimum isolation) first.

   Node capability, license/hash/format checks, and the synthetic model
   benchmark harness follow item 2.
