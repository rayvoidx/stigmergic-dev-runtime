"""Task/attempt ledger over the v2 event store (ADR 0006).

State is a pure reduction over events. Leases are event-sourced and act as
fencing tokens: a terminal event must cite the attempt's current, unexpired
lease event. Restart recovery expires stale leases and records the attempt as
interrupted; interrupted tasks return to ``pending``.

Retry policy, DAG readiness, budgets, and concurrency limits are M7. Here an
interrupted attempt is always re-queued and no attempt cap is enforced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .eventstore import Event, SqliteEventStore
from .store import StoreIntegrityError

TERMINAL = ("success", "failed", "timed_out", "cancelled", "interrupted")
_REQUEUE = ("interrupted",)  # ponytail: retry policy is M7; only crashes re-queue here


class LedgerError(RuntimeError):
    pass


class LeaseError(LedgerError):
    pass


class LedgerIntegrityError(StoreIntegrityError):
    pass


@dataclass(frozen=True)
class Lease:
    task_id: str
    attempt_id: str
    holder: str
    lease_event_id: str
    expires_at: float


@dataclass
class AttemptState:
    attempt_id: str
    holder: str
    lease_event_id: str
    expires_at: float
    lease_valid: bool = True
    status: str | None = None
    last_event_id: str = ""


@dataclass
class TaskState:
    task_id: str
    status: str  # pending | leased | finished
    attempts: list[AttemptState] = field(default_factory=list)
    last_event_id: str = ""


def reduce_tasks(events: Iterable[Event]) -> dict[str, TaskState]:
    """Rebuild task state from events; illegal transitions fail closed."""
    tasks: dict[str, TaskState] = {}
    for event in events:
        payload = event.payload
        if event.type == "task_submitted":
            task_id = payload["task_id"]
            if task_id in tasks:
                raise LedgerIntegrityError(f"task submitted twice: {task_id}")
            tasks[task_id] = TaskState(task_id, "pending", [], event.event_id)
        elif event.type == "lease_acquired":
            task = _task(tasks, payload)
            if task.status != "pending":
                raise LedgerIntegrityError(f"lease on {task.status} task: {task.task_id}")
            task.attempts.append(
                AttemptState(
                    payload["attempt_id"],
                    payload["holder"],
                    event.event_id,
                    float(payload["expires_at"]),
                    last_event_id=event.event_id,
                )
            )
            task.status = "leased"
            task.last_event_id = event.event_id
        elif event.type == "lease_renewed":
            attempt = _active(tasks, payload)
            if not attempt.lease_valid:
                raise LedgerIntegrityError(f"renewal of expired lease: {attempt.attempt_id}")
            attempt.lease_event_id = event.event_id
            attempt.expires_at = float(payload["expires_at"])
            attempt.last_event_id = event.event_id
        elif event.type == "lease_expired":
            attempt = _active(tasks, payload)
            attempt.lease_valid = False
            attempt.last_event_id = event.event_id
        elif event.type == "attempt_finished":
            task = _task(tasks, payload)
            attempt = _active(tasks, payload)
            status = payload["status"]
            if status not in TERMINAL:
                raise LedgerIntegrityError(f"unknown terminal status: {status}")
            attempt.status = status
            attempt.last_event_id = event.event_id
            task.status = "pending" if status in _REQUEUE else "finished"
            task.last_event_id = event.event_id
    return tasks


def _task(tasks: dict[str, TaskState], payload: dict[str, Any]) -> TaskState:
    task = tasks.get(payload.get("task_id"))
    if task is None:
        raise LedgerIntegrityError(f"event for unknown task: {payload.get('task_id')}")
    return task


def _active(tasks: dict[str, TaskState], payload: dict[str, Any]) -> AttemptState:
    task = _task(tasks, payload)
    if task.status != "leased" or not task.attempts:
        raise LedgerIntegrityError(f"no active attempt on task {task.task_id}")
    attempt = task.attempts[-1]
    if attempt.attempt_id != payload.get("attempt_id") or attempt.status is not None:
        raise LedgerIntegrityError(f"event for inactive attempt: {payload.get('attempt_id')}")
    return attempt


class TaskLedger:
    def __init__(self, store: SqliteEventStore, *, run_id: str):
        self.store = store
        self.run_id = run_id

    def state(self) -> dict[str, TaskState]:
        return reduce_tasks(self.store.events(run_id=self.run_id))

    def submit(self, task_id: str, *, payload: dict[str, Any] | None = None) -> Event:
        body: dict[str, Any] = {"task_id": task_id}
        if payload:
            body["payload"] = payload
        return self.store.append(
            "task_submitted",
            body,
            run_id=self.run_id,
            correlation_id=task_id,
            idempotency_key=f"submit:{task_id}",
        )

    def acquire(self, task_id: str, *, holder: str, now: float, ttl: float) -> Lease:
        """Lease a pending task; an expired lease on it is recovered first."""
        with self.store.transaction():
            task = self.state().get(task_id)
            if task is None:
                raise LeaseError(f"unknown task: {task_id}")
            if task.status == "leased":
                attempt = task.attempts[-1]
                if attempt.lease_valid and now <= attempt.expires_at:
                    raise LeaseError(f"task {task_id} has an active lease held by {attempt.holder}")
                self._interrupt(task, attempt)
                task = self.state()[task_id]
            if task.status != "pending":
                raise LeaseError(f"task {task_id} is {task.status}")
            attempt_id = f"{task_id}:{len(task.attempts) + 1}"
            expires_at = now + ttl
            event = self.store.append(
                "lease_acquired",
                {"task_id": task_id, "attempt_id": attempt_id, "holder": holder, "expires_at": expires_at},
                run_id=self.run_id,
                causation_id=task.last_event_id,
                correlation_id=attempt_id,
            )
        return Lease(task_id, attempt_id, holder, event.event_id, expires_at)

    def renew(self, lease: Lease, *, now: float, ttl: float) -> Lease:
        with self.store.transaction():
            self._fenced(lease, now)
            expires_at = now + ttl
            event = self.store.append(
                "lease_renewed",
                {"task_id": lease.task_id, "attempt_id": lease.attempt_id, "expires_at": expires_at},
                run_id=self.run_id,
                causation_id=lease.lease_event_id,
                correlation_id=lease.attempt_id,
            )
        return Lease(lease.task_id, lease.attempt_id, lease.holder, event.event_id, expires_at)

    def finish(
        self, lease: Lease, status: str, *, now: float, result: dict[str, Any] | None = None
    ) -> Event:
        """Record the attempt outcome once; duplicates return the stored event."""
        if status not in TERMINAL:
            raise ValueError(f"status must be one of {TERMINAL}")
        with self.store.transaction():
            existing = self.store.by_idempotency_key(f"finish:{lease.attempt_id}")
            if existing is not None and existing.causation_id == lease.lease_event_id:
                return existing  # duplicate delivery from the same lease
            self._fenced(lease, now)
            return self._finish(lease.task_id, lease.attempt_id, status, lease.lease_event_id, result)

    def recover(self, *, now: float) -> list[Event]:
        """Expire stale leases and mark their attempts interrupted (idempotent)."""
        recovered: list[Event] = []
        with self.store.transaction():
            for task in self.state().values():
                if task.status != "leased":
                    continue
                attempt = task.attempts[-1]
                if attempt.lease_valid and now <= attempt.expires_at:
                    continue
                recovered.extend(self._interrupt(task, attempt))
        return recovered

    def _fenced(self, lease: Lease, now: float) -> AttemptState:
        task = self.state().get(lease.task_id)
        if task is None or task.status != "leased":
            raise LeaseError(f"task {lease.task_id} is not leased")
        attempt = task.attempts[-1]
        if (
            attempt.attempt_id != lease.attempt_id
            or attempt.status is not None
            or not attempt.lease_valid
            or attempt.lease_event_id != lease.lease_event_id
        ):
            raise LeaseError(f"lease for {lease.attempt_id} is superseded or expired")
        if now > attempt.expires_at:
            raise LeaseError(f"lease for {lease.attempt_id} expired at {attempt.expires_at}")
        return attempt

    def _interrupt(self, task: TaskState, attempt: AttemptState) -> list[Event]:
        events: list[Event] = []
        cause = attempt.last_event_id
        if attempt.lease_valid:
            expired = self.store.append(
                "lease_expired",
                {"task_id": task.task_id, "attempt_id": attempt.attempt_id},
                run_id=self.run_id,
                causation_id=attempt.lease_event_id,
                correlation_id=attempt.attempt_id,
                idempotency_key=f"expire:{attempt.attempt_id}:{attempt.lease_event_id}",
            )
            events.append(expired)
            cause = expired.event_id
        events.append(self._finish(task.task_id, attempt.attempt_id, "interrupted", cause, None))
        return events

    def _finish(
        self, task_id: str, attempt_id: str, status: str, causation_id: str, result: dict[str, Any] | None
    ) -> Event:
        payload: dict[str, Any] = {"task_id": task_id, "attempt_id": attempt_id, "status": status}
        if result is not None:
            payload["result"] = result
        return self.store.append(
            "attempt_finished",
            payload,
            run_id=self.run_id,
            causation_id=causation_id,
            correlation_id=attempt_id,
            idempotency_key=f"finish:{attempt_id}",
        )
