"""The worker loop (ADR 0014): recover, admit, acquire, execute, finish.

`Scheduler` and `TaskLedger` had no production caller, so nothing ran
unattended. This is that caller, and it is deliberately dull: it owns no
policy, decides no retries, and reserves no budget — the scheduler already
does all three. Its whole job is to turn a lease into one executor call and
report the outcome exactly once.

Two rules it does own:

* Admission comes before the lease. Asking the machine first and the queue
  second means a hot laptop never strands a task in `leased`.
* An adapter that raises is still a finished attempt. A worker that dies
  holding a lease is the one failure the ledger cannot see until the lease
  expires, so every exit path finishes — or yields to the fence: when the
  lease expired or was superseded mid-attempt, the outcome is recorded as
  ``interrupted`` by recovery, never by this worker crashing.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from .executor import ExecutionRequest, ExecutionResult
from .ledger import LeaseError
from .node import Allocation, HostFacts, NodeProfile, ResourceClass, admit
from .scheduler import WORK_KEY, Scheduler, Usage
from .workspace import WorkspaceRef

DEFAULT_TIMEOUT_SECONDS = 900.0
DEFAULT_POLL_SECONDS = 5.0


class WorkerLoopError(RuntimeError):
    """The worker cannot start or cannot be configured. Never a task's failure."""


def task_payload(
    *,
    instruction: str,
    workspace: Mapping[str, Any],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Build the work spec a submitter attaches to a task, validated up front.

    The loop stays dumb on purpose: whoever submits the task is responsible for
    naming the workspace and the instruction, so a malformed task is caught at
    submission rather than by a worker at three in the morning.
    """
    if not isinstance(instruction, str) or not instruction.strip():
        raise WorkerLoopError("instruction must be a non-empty string")
    try:
        ref = WorkspaceRef(**dict(workspace))
    except (TypeError, ValueError) as exc:
        raise WorkerLoopError(f"invalid workspace: {exc}") from exc
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
        raise WorkerLoopError("timeout_seconds must be a positive number")
    return {
        "instruction": instruction,
        "workspace": {
            "backend_id": ref.backend_id,
            "workspace_id": ref.workspace_id,
            "locator": ref.locator,
        },
        "timeout_seconds": float(timeout_seconds),
    }


class WorkerLoop:
    """One machine's worker: sequential, single-lease, restartable."""

    def __init__(
        self,
        *,
        scheduler: Scheduler,
        executor: Any,
        holder: str,
        clock: Callable[[], float] = time.time,
        profile: NodeProfile | None = None,
        resource_class: ResourceClass | None = None,
        host_facts: Callable[[], HostFacts] | None = None,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
    ):
        if (profile is None) != (resource_class is None):
            raise WorkerLoopError("profile and resource_class are given together or not at all")
        if profile is not None and resource_class is not None and not profile.can_ever_run(resource_class):
            raise WorkerLoopError(
                f"{resource_class.name} never fits on {profile.node_id}: "
                f"{resource_class.memory_gb:g} GB wanted against "
                f"{profile.usable_memory_gb:g} GB usable"
            )
        self.scheduler = scheduler
        self.executor = executor
        self.holder = holder
        self.clock = clock
        self.profile = profile
        self.resource_class = resource_class
        self.host_facts = host_facts
        self.poll_seconds = float(poll_seconds)

    # -- admission ----------------------------------------------------------

    def admitted(self) -> bool:
        """Ask the machine before asking the queue; no profile means no gate."""
        if self.profile is None or self.resource_class is None or self.host_facts is None:
            return True
        decision = admit(
            self.profile,
            Allocation(),  # sequential worker: nothing held while it polls
            self.resource_class.name,
            self.host_facts(),
        )
        return decision.passed

    # -- one turn of the crank ----------------------------------------------

    def tick(self) -> bool:
        """Do at most one attempt. True when work was taken, False when idle."""
        self.scheduler.recover(now=self.clock())
        if not self.admitted():
            return False
        lease = self.scheduler.acquire_next(self.holder, now=self.clock())
        if lease is None:
            return False
        work = self._work_for(lease.task_id)
        if work is None:
            self._finish(lease, "failed", Usage(calls=1), {"error": "task carries no work spec"})
            return True
        started = self.clock()
        try:
            result = self.executor.execute(self._request(lease, work))
        except Exception as exc:  # noqa: BLE001 - an adapter crash is a task outcome, not a worker death
            self._finish(
                lease,
                "failed",
                Usage(calls=1, wall_seconds=max(0.0, self.clock() - started)),
                {"error": f"{type(exc).__name__}: {exc}"},
            )
            return True
        self._finish(lease, result.status, self._usage(result, started), self._summary(result))
        return True

    def run_until_idle(self, max_ticks: int = 1_000) -> int:
        """Drain what is ready, then stop. `max_ticks` is the anti-spin guard."""
        done = 0
        while done < max_ticks and self.tick():
            done += 1
        return done

    def run_forever(self, sleeper: Callable[[float], None] = time.sleep) -> None:
        """The 24/7 shape: poll, work, poll. Stops only on interrupt."""
        while True:
            if not self.tick():
                sleeper(self.poll_seconds)

    # -- helpers -------------------------------------------------------------

    def _work_for(self, task_id: str) -> dict[str, Any] | None:
        # ponytail: linear scan of the run's events per tick; index it if a run
        # ever holds enough tasks for this to show up in a profile.
        for event in self.scheduler.store.events(run_id=self.scheduler.run_id):
            if event.type != "task_submitted" or event.payload.get("task_id") != task_id:
                continue
            work = (event.payload.get("payload") or {}).get(WORK_KEY)
            return work if isinstance(work, dict) else None
        return None

    def _request(self, lease: Any, work: dict[str, Any]) -> ExecutionRequest:
        return ExecutionRequest(
            run_id=self.scheduler.run_id,
            task_id=lease.task_id,
            attempt_id=lease.attempt_id,
            executor_id=self.executor.executor_id,
            workspace=WorkspaceRef(**work["workspace"]),
            instruction=work["instruction"],
            timeout_seconds=float(work.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
        )

    def _usage(self, result: ExecutionResult, started: float) -> Usage:
        reported = result.usage
        tokens = 0 if reported is None else reported.input_tokens + reported.output_tokens
        # A subscription agent reports usd=0; that is a fact about billing, not
        # a missing measurement, so it is passed through unchanged.
        usd = 0.0 if reported is None else reported.usd
        return Usage(
            calls=1,
            tokens=tokens,
            usd=usd,
            wall_seconds=max(0.0, self.clock() - started),
        )

    @staticmethod
    def _summary(result: ExecutionResult) -> dict[str, Any]:
        """Outcome metadata only. Raw agent output can hold secrets and stays out of the log."""
        return {
            "exit_code": result.exit_code,
            "failure_classification": result.failure_classification,
            "revision_after": result.revision_after,
        }

    def _finish(self, lease: Any, status: str, usage: Usage, result: dict[str, Any]) -> None:
        try:
            self.scheduler.finish(lease, status, now=self.clock(), usage=usage, result=result)
        except LeaseError:
            # The lease expired or was superseded while the attempt ran. The
            # fence is doing its job: this worker may no longer speak for the
            # attempt, and the next recover() records it as interrupted and
            # releases the reservation. Losing the outcome is the price of the
            # fence; killing the 24/7 loop over it is not.
            pass
