"""Replay v2 (M6): complete evidence comparison, policy re-run, corruption matrix."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Callable

import pytest

from stigdev.eventstore import SqliteEventStore
from stigdev.model import RunConfig
from stigdev.replay import replay, replay_store
from stigdev.runtime import run
from stigdev.v1import import import_run


@pytest.fixture(scope="module")
def clean_run(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("runs")
    run(RunConfig(run_id="clean", seed=42), root)
    return root / "clean"


@pytest.fixture
def run_dir(clean_run: Path, tmp_path: Path) -> Path:
    dest = tmp_path / "clean"
    shutil.copytree(clean_run, dest)
    return dest


def _edit_events(run_dir: Path, mutate: Callable[[list[dict[str, Any]]], list[dict[str, Any]] | None]) -> None:
    path = run_dir / "events.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    records = mutate(records) or records
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records))


def _first(records: list[dict[str, Any]], type: str) -> dict[str, Any]:
    return next(r for r in records if r["type"] == type)


def _divergence(report: dict[str, Any], needle: str) -> bool:
    return not report["ok"] and any(needle in d for d in report["divergences"])


def test_clean_run_replays_evidence_and_decisions(run_dir: Path):
    report = replay(run_dir)
    assert report["ok"], report["divergences"]
    assert report["checked"] == 9 and report["decisions"] == 8


def test_tampered_metric_with_unchanged_score_is_detected(run_dir: Path):
    def mutate(records):
        _first(records, "evaluated")["evidence"]["metrics"]["precision_at_k"] += 0.1

    _edit_events(run_dir, mutate)
    assert _divergence(replay(run_dir), "metrics")


def test_tampered_evidence_reason_is_detected(run_dir: Path):
    def mutate(records):
        _first(records, "holdout_evaluated")["evidence"]["reason"] = "tampered"

    _edit_events(run_dir, mutate)
    assert _divergence(replay(run_dir), "reason")


def test_tampered_policy_reason_is_detected(run_dir: Path):
    def mutate(records):
        _first(records, "promoted")["reason"] = "looked fine"

    _edit_events(run_dir, mutate)
    assert _divergence(replay(run_dir), "policy reason")


def test_tampered_policy_id_is_detected(run_dir: Path):
    def mutate(records):
        _first(records, "rejected")["policy_id"] = "other/v9"

    _edit_events(run_dir, mutate)
    assert _divergence(replay(run_dir), "policy_id")


def test_recorded_decision_must_match_policy_rerun(run_dir: Path):
    def mutate(records):
        rejected = _first(records, "rejected")
        evaluated = next(r for r in records if r["type"] == "evaluated" and r["episode"] == rejected["episode"])
        evaluated["evidence"].update(passed=True, score=0.99, reason="")

    _edit_events(run_dir, mutate)
    assert _divergence(replay(run_dir), "decision mismatch")


def test_promoted_score_must_match_its_evidence(run_dir: Path):
    def mutate(records):
        _first(records, "promoted")["score"] = 0.99  # first promotion: canonical pointer untouched

    _edit_events(run_dir, mutate)
    report = replay(run_dir)
    assert _divergence(report, "score") and not any("canonical pointer" in d for d in report["divergences"])


def test_deleted_decision_event_is_detected(run_dir: Path):
    _edit_events(run_dir, lambda records: [r for r in records if r is not _first(records, "rejected")])
    assert _divergence(replay(run_dir), "without a recorded decision")


def test_broken_event_sequence_is_detected(run_dir: Path):
    def mutate(records):
        records[3]["seq"], records[4]["seq"] = records[4]["seq"], records[3]["seq"]

    _edit_events(run_dir, mutate)
    assert _divergence(replay(run_dir), "sequence")


def test_malformed_event_line_is_reported_not_raised(run_dir: Path):
    with (run_dir / "events.jsonl").open("a") as fh:
        fh.write('{"seq": 999, "type": "promoted"\n')
    report = replay(run_dir)
    assert _divergence(report, "event log") and report["checked"] == 0


def test_refuses_to_rerun_an_unknown_policy_version(run_dir: Path):
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["policy_id"] = "strict-improve/v0"
    manifest_path.write_text(json.dumps(manifest))
    report = replay(run_dir)
    assert _divergence(report, "policy version") and report["decisions"] == 0


def test_replay_store_verifies_an_imported_run(run_dir: Path, tmp_path: Path):
    store = SqliteEventStore.create(tmp_path / "s", store_id="s")
    import_run(run_dir, store)
    report = replay_store(store, "clean")
    assert report["ok"], report["divergences"]
    assert report["checked"] == 9 and report["decisions"] == 8


def test_replay_store_detects_tampered_blob(run_dir: Path, tmp_path: Path):
    store = SqliteEventStore.create(tmp_path / "s", store_id="s")
    import_run(run_dir, store)
    digest = store.pointer("canonical")[1]["artifact_hash"]
    with sqlite3.connect(store.path) as raw:
        raw.execute("UPDATE blobs SET content = ? WHERE digest = ?", (b"def select_trends(i, k):\n    return []\n", digest))
    assert _divergence(replay_store(store, "clean"), digest[:12])


def test_replay_store_detects_tampered_event_payload(run_dir: Path, tmp_path: Path):
    store = SqliteEventStore.create(tmp_path / "s", store_id="s")
    import_run(run_dir, store)
    event = store.events(type="evaluated")[0]
    payload = dict(event.payload)
    payload["evidence"]["metrics"]["precision_at_k"] += 0.1
    with sqlite3.connect(store.path) as raw:
        raw.execute("UPDATE events SET payload = ? WHERE seq = ?", (json.dumps(payload, sort_keys=True), event.seq))
    assert _divergence(replay_store(store, "clean"), "metrics")
