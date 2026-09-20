"""Durable scheduler (M7): DAG readiness, retries, budget reservations, cancellation, restart."""

from __future__ import annotations

from pathlib import Path

import pytest

from stigdev.eventstore import SqliteEventStore
from stigdev.scheduler import Budget, Reservation, Scheduler, SchedulerError, Usage


@pytest.fixture
def store(tmp_path: Path) -> SqliteEventStore:
    return SqliteEventStore.create(tmp_path / "s", store_id="s")


def _scheduler(store: SqliteEventStore, **budget: object) -> Scheduler:
    return Scheduler(store, run_id="r1", budget=Budget(**budget), started_at=0.0, lease_ttl=10.0)


def _drain(scheduler: Scheduler, *, now: float, status: str = "success", usage: Usage | None = None) -> list[str]:
    """Lease and finish every ready task once; returns task ids in lease order."""
    done = []
    while (lease := scheduler.acquire_next("w", now=now)) is not None:
        scheduler.finish(lease, status, now=now, usage=usage or Usage())
        done.append(lease.task_id)
    return done


def test_configuration_is_recorded_once_and_a_mismatch_fails_closed(store: SqliteEventStore):
    _scheduler(store, max_usd=1.0)
    _scheduler(store, max_usd=1.0)
    assert len(store.events(type="scheduler_configured")) == 1
    with pytest.raises(SchedulerError):
        _scheduler(store, max_usd=2.0)


def test_readiness_follows_dependencies_in_submission_order(store: SqliteEventStore):
    scheduler = _scheduler(store, max_concurrency=4)
    with pytest.raises(SchedulerError):
        scheduler.submit("c", depends_on=("a", "b"))
    scheduler.submit("b")
    scheduler.submit("a")
    scheduler.submit("c", depends_on=("a", "b"))
    scheduler.submit("d")
    assert scheduler.ready() == ["b", "a", "d"]
    lease = scheduler.acquire_next("w", now=1.0)
    assert lease is not None and lease.task_id == "b"
    scheduler.finish(lease, "success", now=2.0, usage=Usage())
    assert scheduler.ready() == ["a", "d"]
    assert _drain(scheduler, now=3.0) == ["a", "c", "d"]
    assert scheduler.ready() == [] and scheduler.state().tasks["c"].status == "succeeded"


def test_failed_dependency_blocks_dependents(store: SqliteEventStore):
    scheduler = _scheduler(store)
    scheduler.submit("a", max_attempts=1)
    scheduler.submit("b", depends_on=("a",))
    lease = scheduler.acquire_next("w", now=1.0)
    scheduler.finish(lease, "failed", now=2.0, usage=Usage())
    state = scheduler.state()
    assert state.tasks["a"].status == "failed" and state.tasks["b"].status == "blocked"
    assert scheduler.ready() == [] and scheduler.acquire_next("w", now=3.0) is None


def test_retry_policy_requeues_until_max_attempts(store: SqliteEventStore):
    scheduler = _scheduler(store)
    scheduler.submit("a", max_attempts=2)
    scheduler.submit("z", max_attempts=3)
    first = scheduler.acquire_next("w", now=1.0)
    scheduler.finish(first, "timed_out", now=2.0, usage=Usage())
    assert scheduler.ready() == ["a", "z"] and scheduler.state().tasks["a"].attempts == 1
    second = scheduler.acquire_next("w", now=3.0)
    assert second.task_id == "a" and second.attempt_id == "a:2"
    scheduler.finish(second, "failed", now=4.0, usage=Usage())
    assert scheduler.state().tasks["a"].status == "failed" and scheduler.ready() == ["z"]
    lease = scheduler.acquire_next("w", now=5.0)
    scheduler.finish(lease, "cancelled", now=6.0, usage=Usage())
    assert scheduler.state().tasks["z"].status == "cancelled" and scheduler.ready() == []


def test_budget_is_reserved_at_lease_and_reconciled_at_finish(store: SqliteEventStore):
    scheduler = _scheduler(store, max_usd=1.0, max_tokens=1000, max_calls=3, max_concurrency=2)
    spend = Reservation(calls=1, tokens=400, usd=0.6)
    scheduler.submit("t1", reservation=spend)
    scheduler.submit("t2", reservation=spend)
    scheduler.submit("t3", reservation=Reservation(calls=1, tokens=10, usd=0.1))
    one = scheduler.acquire_next("w", now=1.0)
    assert one.task_id == "t1"
    state = scheduler.state()
    assert state.reserved["usd"] == pytest.approx(0.6) and state.remaining["usd"] == pytest.approx(0.4)
    assert scheduler.acquire_next("w", now=1.0) is None  # t2 waits for capacity, not exhausted
    assert state.exhausted is None and store.events(type="budget_exhausted") == []
    scheduler.finish(one, "success", now=2.0, usage=Usage(calls=1, tokens=300, usd=0.25))
    state = scheduler.state()
    assert state.used["usd"] == pytest.approx(0.25) and state.reserved["usd"] == 0
    assert state.remaining == {"calls": 2, "tokens": 700, "usd": pytest.approx(0.75), "wall_seconds": None, "workspaces": None}
    two = scheduler.acquire_next("w", now=3.0)
    assert two.task_id == "t2"
    scheduler.finish(two, "success", now=4.0, usage=Usage(calls=1, tokens=500, usd=0.9))  # overshoot
    reconciled = store.events(type="budget_reconciled")[-1].payload
    assert reconciled["overshoot"]["usd"] == pytest.approx(0.3)
    assert scheduler.acquire_next("w", now=5.0) is None
    state = scheduler.state()
    assert state.exhausted == "usd" and state.remaining["usd"] == pytest.approx(-0.15)
    assert [e.payload["dimension"] for e in store.events(type="budget_exhausted")] == ["usd"]
    assert scheduler.acquire_next("w", now=6.0) is None
    assert len(store.events(type="budget_exhausted")) == 1


def test_max_usd_zero_rejects_any_paid_reservation_before_a_lease(store: SqliteEventStore):
    scheduler = _scheduler(store)
    with pytest.raises(SchedulerError):
        scheduler.submit("paid", reservation=Reservation(usd=0.01))
    assert store.events(type="task_submitted") == []
    scheduler.submit("free", reservation=Reservation(calls=1))
    assert scheduler.acquire_next("w", now=1.0).task_id == "free"


def test_concurrency_and_workspace_limits_gate_leases(store: SqliteEventStore):
    scheduler = _scheduler(store, max_concurrency=2, max_workspaces=1)
    for task_id in ("a", "b", "c"):
        scheduler.submit(task_id, reservation=Reservation(workspaces=1))
    first = scheduler.acquire_next("w", now=1.0)
    assert first is not None and scheduler.acquire_next("w", now=1.0) is None
    assert scheduler.state().reserved["workspaces"] == 1
    scheduler.finish(first, "success", now=2.0, usage=Usage())
    second = scheduler.acquire_next("w", now=3.0)
    assert second.task_id == "b"
    unlimited = Scheduler(
        SqliteEventStore.create(store.root.parent / "s2", store_id="s2"),
        run_id="r2", budget=Budget(max_concurrency=2), started_at=0.0, lease_ttl=10.0,
    )
    for task_id in ("a", "b", "c"):
        unlimited.submit(task_id)
    assert unlimited.acquire_next("w", now=1.0) and unlimited.acquire_next("w", now=1.0)
    assert unlimited.acquire_next("w", now=1.0) is None and unlimited.state().exhausted is None


def test_wall_clock_deadline_exhausts_the_run(store: SqliteEventStore):
    scheduler = _scheduler(store, max_wall_seconds=100.0)
    scheduler.submit("a")
    scheduler.submit("b", reservation=Reservation(wall_seconds=50.0))
    assert scheduler.state().remaining["wall_seconds"] == 100.0
    lease = scheduler.acquire_next("w", now=10.0)
    scheduler.finish(lease, "success", now=20.0, usage=Usage(wall_seconds=10.0))
    assert scheduler.acquire_next("w", now=60.0) is None  # 50 s reservation does not fit in 40 s left
    assert scheduler.state().exhausted == "wall_seconds"
    assert scheduler.acquire_next("w", now=61.0) is None


def test_cancellation_stops_new_leases_and_terminalizes(store: SqliteEventStore):
    scheduler = _scheduler(store, max_concurrency=2)
    for task_id in ("a", "b", "c"):
        scheduler.submit(task_id, max_attempts=3)
    lease = scheduler.acquire_next("w", now=1.0)
    scheduler.cancel("a", now=2.0)
    scheduler.cancel("a", now=2.5)
    assert len(store.events(type="task_cancelled")) == 1
    assert scheduler.ready() == ["b", "c"] and scheduler.state().tasks["a"].status == "leased"
    scheduler.finish(lease, "failed", now=3.0, usage=Usage())  # would retry, but it is cancelled
    assert scheduler.state().tasks["a"].status == "cancelled"
    scheduler.cancel_run(now=4.0)
    assert scheduler.acquire_next("w", now=5.0) is None and scheduler.ready() == []
    assert scheduler.state().cancelled and len(store.events(type="run_cancelled")) == 1
    assert {t.status for t in scheduler.state().tasks.values()} == {"cancelled"}


def test_duplicate_completion_and_expired_lease_are_idempotent(store: SqliteEventStore):
    scheduler = _scheduler(store, max_usd=1.0)
    scheduler.submit("a", max_attempts=2, reservation=Reservation(usd=0.5))
    dead = scheduler.acquire_next("w", now=1.0)
    assert scheduler.recover(now=5.0) == []
    recovered = scheduler.recover(now=12.0)
    assert [e.type for e in recovered] == ["lease_expired", "attempt_finished", "budget_reconciled"]
    assert scheduler.recover(now=13.0) == []
    state = scheduler.state()
    assert state.tasks["a"].status == "pending" and state.reserved["usd"] == 0 and state.used["usd"] == 0
    retry = scheduler.acquire_next("w", now=14.0)
    assert retry.attempt_id == "a:2"
    first = scheduler.finish(retry, "success", now=15.0, usage=Usage(usd=0.4))
    second = scheduler.finish(retry, "success", now=16.0, usage=Usage(usd=0.9))
    assert first.event_id == second.event_id
    assert len(store.events(type="budget_reconciled")) == 2 and scheduler.state().used["usd"] == pytest.approx(0.4)
    with pytest.raises(Exception):
        scheduler.finish(dead, "success", now=17.0, usage=Usage())


def test_restart_reconstructs_queue_and_reservations_from_the_store(store: SqliteEventStore):
    scheduler = _scheduler(store, max_usd=2.0, max_concurrency=2)
    scheduler.submit("a", reservation=Reservation(usd=0.5))
    scheduler.submit("b", depends_on=("a",), reservation=Reservation(usd=0.5))
    scheduler.submit("c", reservation=Reservation(usd=0.5), max_attempts=2)
    done = scheduler.acquire_next("w", now=1.0)
    scheduler.finish(done, "success", now=2.0, usage=Usage(usd=0.3))
    scheduler.cancel("b", now=2.5)
    running = scheduler.acquire_next("w", now=3.0)
    assert running.task_id == "c"
    restarted = _scheduler(store, max_usd=2.0, max_concurrency=2)
    assert restarted.state() == scheduler.state()
    assert restarted.ready() == scheduler.ready() == []
    assert restarted.state().reserved["usd"] == pytest.approx(0.5) and restarted.state().remaining["usd"] == pytest.approx(1.2)
    restarted.finish(running, "success", now=4.0, usage=Usage(usd=0.5))
    assert restarted.state().tasks["c"].status == "succeeded"
    assert {t.status for t in restarted.state().tasks.values()} == {"succeeded", "cancelled"}
