"""Durable scheduler (M7) over the task ledger and the v2 event store (ADR 0006).

Readiness, retries, budget reservations and reconciliation, cancellation, and
exhaustion are pure reductions over events, so a restarted scheduler on the
same store resumes with the same queue and the same remaining budget. One
scheduler process per run (one writer per store).

Policy in this milestone: head-of-line scheduling in submission order (no
backfilling), retries for failed/timed_out/interrupted up to ``max_attempts``,
and hard exhaustion when the next task cannot fit the budget even if every
active reservation were released.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .eventstore import Event, SqliteEventStore
from .ledger import Lease, TaskLedger, reduce_tasks

DIMENSIONS = ("calls", "tokens", "usd", "wall_seconds", "workspaces")
RETRYABLE = ("failed", "timed_out", "interrupted")


class SchedulerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Budget:
    """Run-level caps; ``None`` means uncapped. ``max_usd`` defaults to zero: no paid work."""

    max_calls: int | None = None
    max_tokens: int | None = None
    max_usd: float = 0.0
    max_wall_seconds: float | None = None
    max_workspaces: int | None = None
    max_concurrency: int = 1

    def cap(self, dimension: str) -> float | None:
        return getattr(self, f"max_{dimension}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Reservation:
    """Per-attempt estimate reserved before a lease is granted."""

    calls: int = 0
    tokens: int = 0
    usd: float = 0.0
    wall_seconds: float = 0.0
    workspaces: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Reservation":
        return Reservation(**{key: raw.get(key, 0) for key in DIMENSIONS})


@dataclass(frozen=True)
class Usage:
    """Actual consumption reported at finish; workspaces are released, not consumed."""

    calls: int = 0
    tokens: int = 0
    usd: float = 0.0
    wall_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskView:
    task_id: str
    status: str  # pending | leased | succeeded | failed | cancelled | blocked
    depends_on: tuple[str, ...]
    max_attempts: int
    attempts: int
    reservation: Reservation
    cancelled: bool


@dataclass(frozen=True)
class ScheduleState:
    tasks: dict[str, TaskView]
    reservations: dict[str, Reservation]  # active, by attempt id
    reserved: dict[str, float]
    used: dict[str, float]
    remaining: dict[str, float | None]
    leased: int
    exhausted: str | None
    cancelled: bool


def reduce_schedule(events: Iterable[Event], budget: Budget) -> ScheduleState:
    events = list(events)
    ledger = reduce_tasks(events)
    specs: dict[str, tuple[tuple[str, ...], int, Reservation]] = {}
    reservations: dict[str, Reservation] = {}
    used: dict[str, float] = {dim: 0 for dim in DIMENSIONS}
    cancelled_tasks: set[str] = set()
    run_cancelled = False
    exhausted: str | None = None
    for event in events:
        payload = event.payload
        if event.type == "task_submitted":
            spec = payload.get("payload", {})
            specs[payload["task_id"]] = (
                tuple(spec.get("depends_on", ())),
                int(spec.get("max_attempts", 1)),
                Reservation.from_dict(spec.get("reservation", {})),
            )
        elif event.type == "budget_reserved":
            reservations[payload["attempt_id"]] = Reservation.from_dict(payload["reservation"])
        elif event.type == "budget_reconciled":
            reservations.pop(payload["attempt_id"], None)
            for dim, value in payload["usage"].items():
                used[dim] += value
        elif event.type == "task_cancelled":
            cancelled_tasks.add(payload["task_id"])
        elif event.type == "run_cancelled":
            run_cancelled = True
        elif event.type == "budget_exhausted" and exhausted is None:
            exhausted = payload["dimension"]
    reserved = {dim: sum(getattr(r, dim) for r in reservations.values()) for dim in DIMENSIONS}
    remaining = {
        dim: None if budget.cap(dim) is None else budget.cap(dim) - used[dim] - reserved[dim]
        for dim in DIMENSIONS
    }
    tasks: dict[str, TaskView] = {}
    for task_id, task in ledger.items():
        depends_on, max_attempts, reservation = specs.get(task_id, ((), 1, Reservation()))
        attempts = len(task.attempts)
        last = task.attempts[-1].status if task.attempts else None
        cancelled = task_id in cancelled_tasks or run_cancelled
        if task.status == "leased":
            status = "leased"
        elif task.status == "finished" and last == "success":
            status = "succeeded"
        elif cancelled or last == "cancelled":
            status = "cancelled"
        elif task.status == "finished" or attempts >= max_attempts:
            status = "failed"
        elif any(tasks[dep].status in ("failed", "cancelled", "blocked") for dep in depends_on if dep in tasks):
            status = "blocked"
        else:
            status = "pending"
        tasks[task_id] = TaskView(task_id, status, depends_on, max_attempts, attempts, reservation, cancelled)
    leased = sum(view.status == "leased" for view in tasks.values())
    return ScheduleState(tasks, reservations, reserved, used, remaining, leased, exhausted, run_cancelled)


class Scheduler:
    def __init__(
        self,
        store: SqliteEventStore,
        *,
        run_id: str,
        budget: Budget,
        started_at: float,
        lease_ttl: float = 900.0,
    ):
        self.store = store
        self.run_id = run_id
        self.budget = budget
        self.lease_ttl = float(lease_ttl)
        self.ledger = TaskLedger(store, run_id=run_id)
        configured = store.append(
            "scheduler_configured",
            {"budget": budget.to_dict(), "started_at": float(started_at)},
            run_id=run_id,
            idempotency_key=f"scheduler:{run_id}",
        )
        if configured.payload["budget"] != budget.to_dict():
            raise SchedulerError("budget differs from the recorded scheduler configuration")
        self.started_at = float(configured.payload["started_at"])

    # -- queries -----------------------------------------------------------

    def state(self) -> ScheduleState:
        return reduce_schedule(self.store.events(run_id=self.run_id), self.budget)

    def ready(self, state: ScheduleState | None = None) -> list[str]:
        """Pending tasks whose dependencies all succeeded, in submission order."""
        state = state or self.state()
        if state.cancelled or state.exhausted is not None:
            return []
        return [
            view.task_id
            for view in state.tasks.values()
            if view.status == "pending"
            and all(state.tasks[dep].status == "succeeded" for dep in view.depends_on)
        ]

    # -- commands ----------------------------------------------------------

    def submit(
        self,
        task_id: str,
        *,
        depends_on: Iterable[str] = (),
        max_attempts: int = 1,
        reservation: Reservation = Reservation(),
    ) -> Event:
        depends_on = tuple(depends_on)
        if max_attempts < 1:
            raise SchedulerError("max_attempts must be at least 1")
        known = self.state().tasks
        for dep in depends_on:
            if dep not in known:
                raise SchedulerError(f"unknown dependency: {dep}")  # dependencies precede dependents: no cycles
        for dim in DIMENSIONS:
            cap = self.budget.cap(dim)
            if cap is not None and getattr(reservation, dim) > cap:
                raise SchedulerError(f"reservation exceeds budget for {dim}: {getattr(reservation, dim)} > {cap}")
        return self.ledger.submit(
            task_id,
            payload={
                "depends_on": list(depends_on),
                "max_attempts": int(max_attempts),
                "reservation": reservation.to_dict(),
            },
        )

    def acquire_next(self, holder: str, *, now: float) -> Lease | None:
        """Lease the head ready task if its reservation fits; None when nothing can start now."""
        with self.store.transaction():
            state = self.state()
            if state.cancelled or state.exhausted is not None:
                return None
            deadline = None
            if self.budget.max_wall_seconds is not None:
                deadline = self.started_at + self.budget.max_wall_seconds
                if now >= deadline:
                    self._exhaust("wall_seconds", state, now)
                    return None
            ready = self.ready(state)
            if not ready or state.leased >= self.budget.max_concurrency:
                return None
            # ponytail: head-of-line only; backfill smaller tasks if idle capacity matters
            view = state.tasks[ready[0]]
            for dim in DIMENSIONS:
                cap = self.budget.cap(dim)
                if cap is None:
                    continue
                wanted = getattr(view.reservation, dim)
                if wanted > cap - state.used[dim] or (
                    dim == "wall_seconds" and deadline is not None and wanted > deadline - now
                ):
                    self._exhaust(dim, state, now)
                    return None
                if wanted > state.remaining[dim]:
                    return None  # waits for active reservations to reconcile
            lease = self.ledger.acquire(view.task_id, holder=holder, now=now, ttl=self.lease_ttl)
            self.store.append(
                "budget_reserved",
                {
                    "task_id": lease.task_id,
                    "attempt_id": lease.attempt_id,
                    "reservation": view.reservation.to_dict(),
                },
                run_id=self.run_id,
                causation_id=lease.lease_event_id,
                correlation_id=lease.attempt_id,
                idempotency_key=f"reserve:{lease.attempt_id}",
            )
            return lease

    def finish(
        self,
        lease: Lease,
        status: str,
        *,
        now: float,
        usage: Usage,
        result: dict[str, Any] | None = None,
    ) -> Event:
        """Record the outcome, decide retry, and reconcile the reservation once."""
        with self.store.transaction():
            state = self.state()
            view = state.tasks.get(lease.task_id)
            if view is None:
                raise SchedulerError(f"unknown task: {lease.task_id}")
            retry = (
                status in RETRYABLE
                and view.attempts < view.max_attempts
                and not view.cancelled
                and not state.cancelled
            )
            event = self.ledger.finish(lease, status, now=now, result=result, retry=retry)
            if self.store.by_idempotency_key(f"reconcile:{lease.attempt_id}") is None:
                self._reconcile(state, lease.task_id, lease.attempt_id, usage, event.event_id)
            return event

    def recover(self, *, now: float) -> list[Event]:
        """Expire stale leases (ledger) and release their reservations with zero usage."""
        with self.store.transaction():
            events = self.ledger.recover(now=now)
            state = self.state()
            for event in list(events):
                if event.type != "attempt_finished":
                    continue
                attempt_id = event.payload["attempt_id"]
                if self.store.by_idempotency_key(f"reconcile:{attempt_id}") is None:
                    events.append(
                        self._reconcile(state, event.payload["task_id"], attempt_id, Usage(), event.event_id)
                    )
            return events

    def cancel(self, task_id: str, *, now: float) -> Event:
        if task_id not in self.state().tasks:
            raise SchedulerError(f"unknown task: {task_id}")
        return self.store.append(
            "task_cancelled",
            {"task_id": task_id, "at": now},
            run_id=self.run_id,
            correlation_id=task_id,
            idempotency_key=f"cancel:{task_id}",
        )

    def cancel_run(self, *, now: float) -> Event:
        return self.store.append(
            "run_cancelled", {"at": now}, run_id=self.run_id, idempotency_key=f"run_cancelled:{self.run_id}"
        )

    # -- internals ---------------------------------------------------------

    def _reconcile(
        self, state: ScheduleState, task_id: str, attempt_id: str, usage: Usage, causation_id: str
    ) -> Event:
        reservation = state.reservations.get(attempt_id, Reservation())
        overshoot = {
            dim: max(0, getattr(usage, dim) - getattr(reservation, dim)) for dim in usage.to_dict()
        }
        return self.store.append(
            "budget_reconciled",
            {
                "task_id": task_id,
                "attempt_id": attempt_id,
                "reservation": reservation.to_dict(),
                "usage": usage.to_dict(),
                "overshoot": overshoot,
            },
            run_id=self.run_id,
            causation_id=causation_id,
            correlation_id=attempt_id,
            idempotency_key=f"reconcile:{attempt_id}",
        )

    def _exhaust(self, dimension: str, state: ScheduleState, now: float) -> Event:
        return self.store.append(
            "budget_exhausted",
            {
                "dimension": dimension,
                "at": now,
                "cap": self.budget.cap(dimension),
                "used": state.used[dimension],
                "reserved": state.reserved[dimension],
            },
            run_id=self.run_id,
            idempotency_key=f"exhausted:{self.run_id}",
        )
