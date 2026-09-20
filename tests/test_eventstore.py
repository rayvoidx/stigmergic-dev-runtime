"""Durable event store v2 (ADR 0006): envelope, idempotency, CAS, blobs, crash safety."""

from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from stigdev.eventstore import (
    SCHEMA_VERSION,
    Event,
    PointerConflict,
    RedactionError,
    SqliteEventStore,
)
from stigdev.store import StoreIntegrityError


@pytest.fixture
def store(tmp_path: Path) -> SqliteEventStore:
    return SqliteEventStore.create(tmp_path / "s", store_id="s1")


def test_create_then_open_preserves_events_and_identity(tmp_path: Path):
    store = SqliteEventStore.create(tmp_path / "s", store_id="s1")
    store.append("task_submitted", {"task_id": "t1"}, run_id="r1")
    store.close()
    with pytest.raises(FileExistsError):
        SqliteEventStore.create(tmp_path / "s", store_id="s1")
    with pytest.raises(FileNotFoundError):
        SqliteEventStore.open(tmp_path / "missing")
    reopened = SqliteEventStore.open(tmp_path / "s")
    assert reopened.store_id == "s1"
    assert [e.type for e in reopened.events()] == ["task_submitted"]


def test_appended_event_carries_v2_envelope(store: SqliteEventStore):
    event = store.append(
        "task_submitted", {"task_id": "t1"}, run_id="r1", correlation_id="t1", idempotency_key="k1"
    )
    assert isinstance(event, Event)
    assert event.schema_version == SCHEMA_VERSION == 2
    assert event.store_id == "s1" and event.run_id == "r1"
    assert len(event.event_id) == 32 and int(event.event_id, 16) >= 0
    assert event.seq == 1
    assert event.type == "task_submitted"
    assert isinstance(event.ts, float)
    assert event.causation_id is None
    assert event.correlation_id == "t1" and event.idempotency_key == "k1"
    assert event.payload == {"task_id": "t1"}


def test_seq_is_monotonic_across_reopen(tmp_path: Path):
    store = SqliteEventStore.create(tmp_path / "s", store_id="s1")
    assert store.append("a", {}, run_id="r").seq == 1
    assert store.append("b", {}, run_id="r").seq == 2
    store.close()
    assert SqliteEventStore.open(tmp_path / "s").append("c", {}, run_id="r").seq == 3


def test_duplicate_idempotency_key_returns_stored_event_unchanged(store: SqliteEventStore):
    first = store.append("done", {"n": 1}, run_id="r", idempotency_key="finish:a1")
    second = store.append("done", {"n": 2}, run_id="r", idempotency_key="finish:a1")
    assert second.event_id == first.event_id and second.seq == first.seq
    assert second.payload == {"n": 1}
    assert len(store.events()) == 1


def test_causation_must_reference_an_existing_event(store: SqliteEventStore):
    parent = store.append("a", {}, run_id="r")
    child = store.append("b", {}, run_id="r", causation_id=parent.event_id)
    assert child.causation_id == parent.event_id
    with pytest.raises(StoreIntegrityError):
        store.append("c", {}, run_id="r", causation_id="0" * 32)


def test_payload_must_be_a_json_object(store: SqliteEventStore):
    with pytest.raises(ValueError):
        store.append("a", ["not", "an", "object"], run_id="r")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        store.append("a", {"x": object()}, run_id="r")


def test_redaction_rejects_forbidden_values_in_nested_payload(store: SqliteEventStore):
    forbidden = ("token-abcdefgh", "1")
    with pytest.raises(RedactionError):
        store.append("a", {"note": "token-abcdefgh"}, run_id="r", forbidden=forbidden)
    with pytest.raises(RedactionError):
        store.append("a", {"n": [{"x": "see token-abcdefgh here"}]}, run_id="r", forbidden=forbidden)
    with pytest.raises(RedactionError):  # short values match whole fields only
        store.append("a", {"flag": "1"}, run_id="r", forbidden=forbidden)
    store.append("a", {"flag": "10", "ok": "tok"}, run_id="r", forbidden=forbidden)
    assert len(store.events()) == 1


def test_redaction_applies_to_blobs(store: SqliteEventStore):
    with pytest.raises(RedactionError):
        store.put_blob(b"x = 'secret-value-123'\n", forbidden=("secret-value-123",))
    assert store.put_blob(b"x = 1\n", forbidden=("secret-value-123",))


def test_blob_round_trip_and_tamper_detection(store: SqliteEventStore):
    digest = store.put_blob(b"print(1)\n", kind="py")
    assert len(digest) == 64 and store.put_blob(b"print(1)\n", kind="py") == digest
    assert store.get_blob(digest) == b"print(1)\n"
    with sqlite3.connect(store.path) as raw:
        raw.execute("UPDATE blobs SET content = ? WHERE digest = ?", (b"print(2)\n", digest))
    with pytest.raises(StoreIntegrityError):
        store.get_blob(digest)


def test_tree_is_content_addressed_and_checks_blob_references(store: SqliteEventStore):
    a = store.put_blob(b"a")
    b = store.put_blob(b"b")
    tree = store.put_tree({"src/b.py": b, "a.py": a})
    assert tree == store.put_tree({"a.py": a, "src/b.py": b})
    assert store.get_tree(tree) == {"a.py": a, "src/b.py": b}
    with pytest.raises(StoreIntegrityError):
        store.put_tree({"missing.py": "0" * 64})


def test_pointer_compare_and_swap_surfaces_conflicts(store: SqliteEventStore):
    assert store.pointer("canonical") is None
    assert store.set_pointer("canonical", {"tree": "t1"}, expected_version=0) == 1
    with pytest.raises(PointerConflict):
        store.set_pointer("canonical", {"tree": "stale"}, expected_version=0)
    assert store.set_pointer("canonical", {"tree": "t2"}, expected_version=1) == 2
    assert store.pointer("canonical") == (2, {"tree": "t2"})


def test_transaction_rolls_back_every_write_on_error(store: SqliteEventStore):
    with pytest.raises(RuntimeError):
        with store.transaction():
            store.append("a", {}, run_id="r")
            store.set_pointer("p", {"v": 1}, expected_version=0)
            store.put_blob(b"z")
            raise RuntimeError("boom")
    assert store.events() == [] and store.pointer("p") is None
    assert store.append("b", {}, run_id="r").seq == 1


def test_uncommitted_transaction_is_lost_when_writer_is_killed(tmp_path: Path):
    root = tmp_path / "s"
    store = SqliteEventStore.create(root, store_id="s1")
    store.append("before", {}, run_id="r")
    store.close()
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                f"""
                import sys, time
                from stigdev.eventstore import SqliteEventStore
                store = SqliteEventStore.open({str(root)!r})
                with store.transaction():
                    store.append("torn", {{}}, run_id="r")
                    print("ready", flush=True)
                    time.sleep(30)
                """
            ),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert child.stdout is not None and child.stdout.readline().strip() == "ready"
    os.kill(child.pid, signal.SIGKILL)
    child.wait()
    reopened = SqliteEventStore.open(root)
    assert [e.type for e in reopened.events()] == ["before"]
    assert reopened.append("after", {}, run_id="r").seq == 2


def test_store_runs_in_wal_mode_and_records_synchronous(store: SqliteEventStore):
    with sqlite3.connect(store.path) as raw:
        assert raw.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert store.meta()["synchronous"] == "NORMAL"
    assert store.meta()["schema_version"] == "2"


def test_events_filter_by_type_run_and_seq(store: SqliteEventStore):
    store.append("a", {}, run_id="r1")
    store.append("b", {}, run_id="r2")
    store.append("a", {}, run_id="r2")
    assert [e.seq for e in store.events(type="a")] == [1, 3]
    assert [e.seq for e in store.events(run_id="r2")] == [2, 3]
    assert [e.seq for e in store.events(after_seq=2)] == [3]
