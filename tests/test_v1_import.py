"""v1 run directories stay readable; import/export round-trips replay unchanged (ADR 0006)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from stigdev.eventstore import SqliteEventStore
from stigdev.replay import replay
from stigdev.store import RunStore, StoreIntegrityError
from stigdev.v1import import export_run, import_run

SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "sample_run"


def test_import_preserves_events_artifacts_and_pointers(tmp_path: Path):
    store = SqliteEventStore.create(tmp_path / "s", store_id="s")
    v1 = RunStore.open(SAMPLE)
    records = v1.events()
    assert import_run(SAMPLE, store) == len(records)
    imported = store.events(run_id="sample_run")
    assert [(e.type, e.ts) for e in imported] == [(r["type"], r["ts"]) for r in records]
    for event, record in zip(imported, records, strict=True):
        assert event.idempotency_key == f"v1:sample_run:{record['seq']}"
        assert event.payload == {
            "v1_seq": record["seq"],
            **{k: v for k, v in record.items() if k not in ("seq", "type", "ts")},
        }
    for path in (SAMPLE / "artifacts").glob("*.py"):
        assert store.get_blob(path.stem) == path.read_bytes()
    assert store.pointer("canonical")[1] == v1.canonical()
    assert store.pointer("manifest")[1] == v1.manifest()


def test_import_is_idempotent(tmp_path: Path):
    store = SqliteEventStore.create(tmp_path / "s", store_id="s")
    count = import_run(SAMPLE, store)
    assert import_run(SAMPLE, store) == count
    assert len(store.events()) == count


def test_import_rejects_artifact_whose_bytes_do_not_match_its_hash(tmp_path: Path):
    run_dir = tmp_path / "run"
    shutil.copytree(SAMPLE, run_dir)
    artifact = next((run_dir / "artifacts").glob("*.py"))
    artifact.write_text(artifact.read_text() + "\n# tampered\n")
    store = SqliteEventStore.create(tmp_path / "s", store_id="s")
    with pytest.raises(StoreIntegrityError):
        import_run(run_dir, store)
    assert store.events() == [] and store.blobs() == []  # all or nothing


def test_export_round_trip_replays_like_the_original(tmp_path: Path):
    store = SqliteEventStore.create(tmp_path / "s", store_id="s")
    import_run(SAMPLE, store)
    dest = export_run(store, "sample_run", tmp_path / "exported")
    assert (dest / "events.jsonl").read_bytes() == (SAMPLE / "events.jsonl").read_bytes()
    assert (dest / "canonical.json").read_bytes() == (SAMPLE / "canonical.json").read_bytes()
    report = replay(dest)
    assert report["ok"] and report == replay(SAMPLE)


def test_v1_canonical_pointer_write_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = RunStore.create(tmp_path / "run")
    store.set_canonical("a" * 64, 1, 0.5)

    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError):
        store.set_canonical("b" * 64, 2, 0.9)
    assert store.canonical() == {"artifact_hash": "a" * 64, "generation": 1, "score": 0.5}
