"""End-to-end: full deterministic run exercising promotion, rejection,
lineage, replay, recovery, and canonical-state preservation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stigdev.cli import main as cli_main
from stigdev.model import RunConfig
from stigdev.replay import recover, replay
from stigdev.runtime import run
from stigdev.store import RunStore


def test_run_promotes_and_rejects(demo_run):
    _, summary = demo_run
    assert summary["promoted"] == 3
    assert summary["rejected"] == 5  # 3 distinct failures + 2 repeated probes
    assert summary["proposed"] == 8
    assert summary["repeated_failure_attempts"] == 2
    assert summary["lineage_depth"] == 3
    assert summary["cost"] == {"input_tokens": 0, "output_tokens": 0, "usd": 0.0}


def test_run_improves_train_and_holdout(demo_run):
    _, summary = demo_run
    assert summary["canonical"]["score"] == pytest.approx(0.86)
    assert summary["canonical"]["score"] > summary["seed_score_train"]
    assert summary["holdout_score"] == pytest.approx(0.86)


def test_rejected_candidates_never_contaminate_canonical(demo_run):
    run_dir, _ = demo_run
    store = RunStore.open(run_dir)
    canonical = store.canonical()
    rejected_hashes = {e["artifact_hash"] for e in store.failures()}
    promoted_hashes = {e["artifact_hash"] for e in store.events("promoted")}
    assert canonical["artifact_hash"] not in rejected_hashes
    assert canonical["artifact_hash"] in promoted_hashes
    # rejected artifacts stay available as failure evidence
    for digest in rejected_hashes:
        assert store.artifact_path(digest).exists()


def test_lineage_is_a_connected_chain(demo_run):
    run_dir, _ = demo_run
    store = RunStore.open(run_dir)
    edges = store.lineage_edges()
    parent = store.events("run_started")[0]["seed_artifact_hash"]
    for edge in edges:
        assert edge["parent_hash"] == parent
        parent = edge["child_hash"]
    assert parent == store.canonical()["artifact_hash"]


def test_replay_verifies_clean_run(demo_run):
    run_dir, _ = demo_run
    report = replay(run_dir)
    assert report["ok"], report["divergences"]
    assert report["checked"] == 9  # 8 train evaluations + 1 holdout


def test_run_is_reproducible_bit_for_bit(demo_run, tmp_path: Path):
    run_dir, summary = demo_run
    rerun_summary = run(RunConfig(run_id="rerun", seed=42), tmp_path)
    stable = {k: v for k, v in summary.items() if k != "wall_seconds"}
    rerun_stable = {k: v for k, v in rerun_summary.items() if k != "wall_seconds"}
    assert stable == rerun_stable
    original = {p.name for p in (run_dir / "artifacts").iterdir()}
    rerun_artifacts = {p.name for p in (tmp_path / "rerun" / "artifacts").iterdir()}
    assert original == rerun_artifacts


def test_replay_detects_tampered_artifact(tmp_path: Path):
    run(RunConfig(run_id="tamper", seed=42), tmp_path)
    store = RunStore.open(tmp_path / "tamper")
    digest = store.canonical()["artifact_hash"]
    store.artifact_path(digest).write_text("def select_trends(i, k):\n    return []\n")
    report = replay(tmp_path / "tamper")
    assert not report["ok"]
    assert any(digest[:12] in d for d in report["divergences"])


def test_recover_restores_corrupted_canonical_pointer(tmp_path: Path):
    run(RunConfig(run_id="recov", seed=42), tmp_path)
    run_dir = tmp_path / "recov"
    store = RunStore.open(run_dir)
    good = store.canonical()
    bad_hash = next(e["artifact_hash"] for e in store.failures())
    store.set_canonical(bad_hash, 99, 0.0)  # simulate corruption/crash mid-write
    assert not replay(run_dir)["ok"]

    report = recover(run_dir)
    assert report["recovered"]
    assert RunStore.open(run_dir).canonical() == good
    assert replay(run_dir)["ok"]

    second = recover(run_dir)
    assert not second["recovered"]
    assert "already valid" in second["reason"]


def test_cli_end_to_end(tmp_path: Path, capsys):
    runs_root = str(tmp_path / "runs")
    assert cli_main(["demo", "--runs-root", runs_root, "--run-id", "cli-demo"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["promoted"] == 3

    run_dir = f"{runs_root}/cli-demo"
    assert cli_main(["replay", run_dir]) == 0
    capsys.readouterr()
    assert cli_main(["lineage", run_dir]) == 0
    out = capsys.readouterr().out
    assert "gen 0" in out and "rejected" in out and "canonical:" in out

    seed = str(Path(__file__).parents[1] / "benchmarks/trendevobench/seed_artifact.py")
    assert cli_main(["evaluate", "--artifact", seed, "--split", "holdout"]) == 0
