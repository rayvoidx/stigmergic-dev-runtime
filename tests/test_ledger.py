"""Task/attempt ledger (ADR 0006): event-sourced leases, fencing, recovery, queue sim."""

from __future__ import annotations

from pathlib import Path

import pytest

from stigdev.eventstore import Event, PointerConflict, SqliteEventStore
from stigdev.ledger import LeaseError, LedgerIntegrityError, TaskLedger, reduce_tasks


@pytest.fixture
def ledger(tmp_path: Path) -> TaskLedger:
    return TaskLedger(SqliteEventStore.create(tmp_path / "s", store_id="s1"), run_id="r1")


def test_submit_is_idempotent(ledger: TaskLedger):
    first = ledger.submit("t1")
    assert ledger.submit("t1").event_id == first.event_id
    assert ledger.state()["t1"].status == "pending"
    assert len(ledger.store.events()) == 1


def test_acquire_creates_attempt_with_lease_caused_by_submission(ledger: TaskLedger):
    submitted = ledger.submit("t1")
    lease = ledger.acquire("t1", holder="w1", now=100.0, ttl=10.0)
    assert lease.task_id == "t1" and lease.attempt_id == "t1:1" and lease.holder == "w1"
    assert lease.expires_at == 110.0
    assert ledger.store.event(lease.lease_event_id).causation_id == submitted.event_id
    task = ledger.state()["t1"]
    assert task.status == "leased"
    assert task.attempts[-1].attempt_id == "t1:1" and task.attempts[-1].status is None


def test_acquire_refuses_unknown_leased_or_finished_tasks(ledger: TaskLedger):
    with pytest.raises(LeaseError):
        ledger.acquire("nope", holder="w1", now=0.0, ttl=1.0)
    ledger.submit("t1")
    lease = ledger.acquire("t1", holder="w1", now=0.0, ttl=10.0)
    with pytest.raises(LeaseError):
        ledger.acquire("t1", holder="w2", now=5.0, ttl=10.0)
    ledger.finish(lease, "success", now=6.0)
    with pytest.raises(LeaseError):
        ledger.acquire("t1", holder="w2", now=7.0, ttl=10.0)


def test_finish_requires_the_current_unexpired_lease(ledger: TaskLedger):
    ledger.submit("t1")
    old = ledger.acquire("t1", holder="w1", now=0.0, ttl=10.0)
    renewed = ledger.renew(old, now=5.0, ttl=10.0)
    assert renewed.expires_at == 15.0
    assert ledger.store.event(renewed.lease_event_id).causation_id == old.lease_event_id
    with pytest.raises(LeaseError):  # superseded lease is fenced out
        ledger.finish(old, "success", now=6.0)
    with pytest.raises(LeaseError):  # expired lease is fenced out
        ledger.finish(renewed, "success", now=16.0)
    with pytest.raises(LeaseError):
        ledger.renew(renewed, now=16.0, ttl=10.0)
    assert ledger.state()["t1"].status == "leased"


def test_duplicate_finish_commits_once(ledger: TaskLedger):
    ledger.submit("t1")
    lease = ledger.acquire("t1", holder="w1", now=0.0, ttl=10.0)
    first = ledger.finish(lease, "success", now=1.0, result={"tree": "abc"})
    second = ledger.finish(lease, "success", now=2.0, result={"tree": "other"})
    assert second.event_id == first.event_id and second.payload["result"] == {"tree": "abc"}
    assert first.causation_id == lease.lease_event_id
    task = ledger.state()["t1"]
    assert task.status == "finished" and task.attempts[-1].status == "success"
    assert len(ledger.store.events(type="attempt_finished")) == 1


def test_recover_marks_expired_leases_interrupted_and_is_idempotent(ledger: TaskLedger):
    ledger.submit("t1")
    ledger.submit("t2")
    dead = ledger.acquire("t1", holder="w1", now=0.0, ttl=10.0)
    alive = ledger.acquire("t2", holder="w2", now=0.0, ttl=100.0)
    recovered = ledger.recover(now=11.0)
    assert [e.type for e in recovered] == ["lease_expired", "attempt_finished"]
    assert recovered[0].causation_id == dead.lease_event_id
    assert recovered[1].causation_id == recovered[0].event_id
    assert recovered[1].payload["status"] == "interrupted"
    assert ledger.recover(now=12.0) == []
    state = ledger.state()
    assert state["t1"].status == "pending" and state["t1"].attempts[-1].status == "interrupted"
    assert state["t2"].status == "leased"
    with pytest.raises(LeaseError):  # the dead worker cannot finish after recovery
        ledger.finish(dead, "success", now=13.0)
    ledger.finish(alive, "success", now=13.0)


def test_acquire_recovers_an_expired_lease_first(ledger: TaskLedger):
    ledger.submit("t1")
    dead = ledger.acquire("t1", holder="w1", now=0.0, ttl=10.0)
    retry = ledger.acquire("t1", holder="w2", now=20.0, ttl=10.0)
    assert retry.attempt_id == "t1:2"
    attempts = ledger.state()["t1"].attempts
    assert [a.status for a in attempts] == ["interrupted", None]
    interrupted = ledger.store.events(type="attempt_finished")[0]
    assert ledger.store.event(retry.lease_event_id).causation_id == interrupted.event_id
    assert dead.lease_event_id != retry.lease_event_id


def _event(seq: int, type: str, payload: dict) -> Event:
    return Event(
        seq=seq, schema_version=2, store_id="s1", run_id="r1", event_id=f"{seq:032x}", type=type,
        ts=0.0, causation_id=None, correlation_id=None, idempotency_key=None, payload=payload,
    )


def test_reducer_fails_closed_on_illegal_transitions(ledger: TaskLedger):
    ledger.store.append(
        "lease_acquired",
        {"task_id": "ghost", "attempt_id": "ghost:1", "holder": "w", "expires_at": 1.0},
        run_id="r1",
    )
    with pytest.raises(LedgerIntegrityError):
        ledger.state()
    submitted = _event(1, "task_submitted", {"task_id": "t"})
    with pytest.raises(LedgerIntegrityError):  # duplicate submission
        reduce_tasks([submitted, _event(2, "task_submitted", {"task_id": "t"})])
    with pytest.raises(LedgerIntegrityError):  # finish without a lease
        reduce_tasks([submitted, _event(2, "attempt_finished", {"task_id": "t", "attempt_id": "t:1", "status": "success"})])
    with pytest.raises(LedgerIntegrityError):  # unknown terminal status
        lease = _event(2, "lease_acquired", {"task_id": "t", "attempt_id": "t:1", "holder": "w", "expires_at": 1.0})
        reduce_tasks([submitted, lease, _event(3, "attempt_finished", {"task_id": "t", "attempt_id": "t:1", "status": "done"})])


def test_queue_simulation_more_tasks_than_slots_commits_exactly_once(ledger: TaskLedger):
    tasks = [f"t{i}" for i in range(24)]
    for task_id in tasks:
        ledger.submit(task_id)
    slots, ttl, clock, crashed = 2, 3.0, 0.0, False
    running: dict[str, object] = {}
    while any(t.status != "finished" for t in ledger.state().values()):
        state = ledger.state()
        leased = sum(t.status == "leased" for t in state.values())
        assert leased <= slots  # a lingering lease occupies capacity until recovery
        for task in state.values():
            if leased >= slots:
                break
            if task.status == "pending":
                running[task.task_id] = ledger.acquire(task.task_id, holder=f"slot{leased}", now=clock, ttl=ttl)
                leased += 1
        clock += 1.0
        for task_id, lease in list(running.items()):
            if task_id == "t7" and not crashed:
                crashed = True  # worker dies: no finish, lease expires, recovery re-queues
                del running[task_id]
                continue
            ledger.finish(lease, "success", now=clock, result={"tree": task_id})
            if task_id == "t3":  # duplicate delivery of the same completion
                ledger.finish(lease, "success", now=clock, result={"tree": "dup"})
            version = ledger.store.pointer("canonical")
            ledger.store.set_pointer(
                "canonical", {"last": task_id}, expected_version=0 if version is None else version[0]
            )
            del running[task_id]
        if clock % 4 == 0:
            ledger.recover(now=clock)
    finished = ledger.store.events(type="attempt_finished")
    assert sum(e.payload["status"] == "success" for e in finished) == 24
    assert sum(e.payload["status"] == "interrupted" for e in finished) == 1
    assert len(ledger.store.events(type="lease_expired")) == 1
    assert [a.status for a in ledger.state()["t7"].attempts] == ["interrupted", "success"]
    assert ledger.store.pointer("canonical")[0] == 24
    with pytest.raises(PointerConflict):
        ledger.store.set_pointer("canonical", {"last": "stale"}, expected_version=23)
