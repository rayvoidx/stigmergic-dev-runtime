# Offline execution contracts

Stage 2 implements typed contracts, deterministic test doubles, and opt-in
execution evidence over the existing `RunStore`. All 135 tests pass offline
(55 existing + 80 new), as do all 10 committed example replays and the example
below. The design baseline was merged in PR #1 (`5867f67`).

`Provider.generate` remains model inference. `AgentExecutor.execute` handles
one already selected attempt in an assigned workspace. `WorkspaceBackend`
owns workspace lifecycle, not task ordering. Neither new protocol inherits
from `Provider`; existing benchmark configuration and experiments are unchanged.

## Public interfaces

All types use standard-library dataclasses and protocols. Import from their
own modules; no adapter registry or new configuration framework is introduced.

| Module | Interface |
|---|---|
| `stigdev.executor` | `AgentExecutor.executor_id`, `execute(ExecutionRequest) -> ExecutionResult` |
| `stigdev.workspace` | `WorkspaceBackend.backend_id`, `create(WorkspaceSpec) -> WorkspaceRef`, `resolve(workspace_id) -> WorkspaceRef` |
| `stigdev.workspace` | `prepare`, `inspect`, `retain`, `dispose`: `(WorkspaceRef) -> WorkspaceState` |
| `stigdev.execution` | `execute_agent(store, request, executor, workspace_backend) -> ExecutionResult` |
| `stigdev.execution` | `inspect_executions(store)` and `recover_executions(store) -> list[dict[str, Any]]` |

`ExecutionRequest` contains `run_id`, `task_id`, `attempt_id`, `executor_id`,
`workspace`, transient `instruction`, explicit `environment` name/value pairs,
`timeout_seconds`, `ExecutionBudget`, and optional `parent_attempt_id`.
No host environment is inherited. `ExecutionBudget(max_tokens, max_usd)` is
metadata, not authorization, reservation, or enforcement.
`max_tokens=None` means no stated token limit; `0` requests zero tokens.
The default `max_usd=0` describes zero spending, not a payment permission.

`ExecutionResult` contains attempt/workspace identity, `status`, `started_at`
and `finished_at` as UNIX seconds, optional `exit_code`, transient
`stdout`/`stderr`, existing `artifact_hashes`, before/after workspace revisions,
`failure_classification`, `retryable`, and optional
`ExecutionUsage(input_tokens, output_tokens, usd)`. Usage is adapter-reported
evidence. A missing start time means execution never began or its start was
not durably observed.

`WorkspaceSpec(workspace_id, repository_id, base_revision)` resolves through a
backend. `WorkspaceRef(backend_id, workspace_id, locator)` separates stable
identity from transient location; locator is excluded from identity equality.
`WorkspaceState(workspace, revision, prepared, disposition)` reports observed
state. Disposition is `active`, `retained`, or `disposed`. Revisions are opaque
backend identities, not necessarily Git commits.

Requests, results, and workspace states are validated through
`validate_request`, `validate_result`, and `validate_state`. Invalid contracts
raise `ContractError`/`WorkspaceError`; inconsistent persisted execution
evidence raises `ExecutionIntegrityError` (a `StoreIntegrityError`).

## Offline example

Run this Python code from the installed checkout. It creates no process,
network request, Git worktree, or real coding-agent session.

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from stigdev.execution import execute_agent, inspect_executions
from stigdev.executor import ExecutionBudget, ExecutionRequest
from stigdev.store import RunStore
from stigdev.testing import DeterministicFakeExecutor, FakeWorkspaceBackend
from stigdev.workspace import WorkspaceSpec

with TemporaryDirectory() as directory:
    store = RunStore.create(Path(directory) / "execution-example")
    artifact = store.put_artifact("RESULT = 'synthetic'\n")
    backend = FakeWorkspaceBackend()
    workspace = backend.create(WorkspaceSpec("workspace-1", "synthetic-repo"))
    executor = DeterministicFakeExecutor(backend, artifact_hashes=(artifact,))
    request = ExecutionRequest(
        run_id="run-1", task_id="task-1", attempt_id="attempt-1",
        executor_id=executor.executor_id, workspace=workspace,
        instruction="Perform the deterministic fixture attempt.",
        environment=(), timeout_seconds=10,
        budget=ExecutionBudget(max_tokens=0, max_usd=0),
    )
    result = execute_agent(store, request, executor, backend)
    assert result.status == "success"
    assert result.revision_before != result.revision_after
    assert inspect_executions(RunStore.open(store.root))[0]["status"] == "success"
    assert store.canonical() is None
    backend.retain(workspace)  # The caller chooses retention or disposal.
    backend.dispose(workspace)  # Explicit test-fixture cleanup decision.
```

The caller creates/resolves a workspace; `execute_agent` prepares and inspects
it, invokes the executor, then independently inspects the resulting revision.
Retention and disposal remain explicit caller operations. Failed workspaces
remain caller-owned; the runner never cleans them up. The fake backend stores
only in-memory state, so reopening a run recovers evidence, not a workspace.

`DeterministicFakeExecutor` supports `success`, `nonzero_exit`, `timeout`,
`cancelled`, `malformed`, and `raise_error`. `FakeWorkspaceBackend` supports
`fail_prepare=True`. These are test fixtures, not production adapters. Fake
result timestamps and revisions are deterministic; event timestamps record
wall time and are not promised to be bit-identical across fresh runs.

## Events, inspection, and recovery

Execution events retain `{seq, type, ts, ...payload}` and add
`execution_version: 1`. Each carries run/task/attempt/executor/workspace IDs
and parent lineage. Later events link to the request and preceding attempt
event through `request_seq` and `caused_by_seq`.

Normal order is `execution_requested` → `workspace_prepared` →
`execution_started` → one terminal event: `execution_completed`,
`execution_failed`, `execution_timed_out`, or `execution_cancelled`.
Preparation failure goes directly from requested to failed. Terminal records
contain validated results, existing artifact hashes, and observed revisions.
This phase adds no global event-schema migration or canonical promotion.

Statuses are `success`, `failed`, `timed_out`, `cancelled`, and `interrupted`.
Failures classify nonzero exit, timeout, cancellation, malformed result,
workspace preparation/inspection, executor error, or interruption. Adapter
identity mismatches, duplicate attempts, invalid parents, unresolved workspace
attempts, and corrupt evidence fail closed before invocation. An ordinary
adapter exception becomes a classified failure without persisting its text.

For a retained execution run directory:

```bash
stigdev executions RUN
stigdev recover-executions RUN
```

`executions` validates event order, lineage, and referenced artifact hashes.
It does not rerun agents, attest workspace revisions, or evaluate candidates.
The existing `replay`/`recover` commands keep their benchmark/canonical meaning.
There is no live-agent execution CLI.

Stop the previous writer before `recover-executions`. Recovery appends
`execution_interrupted` for open attempts, recording an unknown outcome and
`retryable=False`. Repeating recovery adds no duplicate terminal events. A
caller-authorized retry needs a new attempt ID and its terminal parent's ID
for the same run/task. Recovery does not resume, rerun, or dispose anything.
There are no locks, leases, fencing, fsync guarantees, torn-JSON repair,
transactional writes, or exactly-once execution guarantees.

## Security and deferred implementation

Instructions, environments, workspace locators, raw output, and exception text
are never copied into execution events. Returned durable-safe results replace
nonempty stdout/stderr with `[output omitted]`; no log blob is stored. Known
instruction/locator/environment values are checked against public metadata and
referenced artifacts: values of at least eight characters use substring checks;
shorter values use whole-field equality. Embedded short, encoded, or unknown
secrets can evade these checks. This is not a comprehensive secret detector:
callers must supply public opaque IDs/revisions and review artifacts before
storing them. Already stored artifact bytes are not removed by result rejection.

Synchronous execution cannot forcibly stop arbitrary blocking Python code.
Adapters must honor deadlines; reported timeout or a detected late result is
recorded, but process supervision, heartbeat transport, asynchronous cancel,
tool/network permission enforcement, and credential injection are deferred.
No real Claude Code, Codex CLI, OpenCode, Hermes, Slack, Git worktree,
container, or remote backend is supported. There is no paid API, scheduler,
general checkpoint/blob ingestion, evaluator gate integration, or deployment.
