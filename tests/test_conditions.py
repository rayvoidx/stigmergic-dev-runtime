"""The five experimental conditions are configurable with matched budgets;
unimplemented ones refuse to run instead of silently falling back."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stigdev.model import CONDITIONS, IMPLEMENTED_CONDITIONS, RunConfig
from stigdev.runtime import ConditionNotImplementedError, run

CONFIG_DIR = Path(__file__).parents[1] / "configs" / "conditions"


def _load(condition: str) -> RunConfig:
    raw = json.loads((CONFIG_DIR / f"{condition}.json").read_text(encoding="utf-8"))
    return RunConfig.from_dict(raw)


def test_all_five_conditions_have_configs():
    assert {p.stem for p in CONFIG_DIR.glob("*.json")} == set(CONDITIONS)


@pytest.mark.parametrize("condition", CONDITIONS)
def test_condition_configs_parse_with_matched_budgets(condition: str):
    config = _load(condition)
    assert config.condition == condition
    reference = _load("artifact_only")
    assert config.budget == reference.budget
    assert config.provider == reference.provider
    assert config.seed == reference.seed


@pytest.mark.parametrize("condition", sorted(set(CONDITIONS) - set(IMPLEMENTED_CONDITIONS)))
def test_unimplemented_conditions_fail_loudly(condition: str, tmp_path: Path):
    with pytest.raises(ConditionNotImplementedError):
        run(_load(condition), tmp_path)


def test_artifact_only_condition_runs_from_config(tmp_path: Path):
    summary = run(_load("artifact_only"), tmp_path)
    assert summary["promoted"] >= 1 and summary["rejected"] >= 1


def test_single_persistent_matches_artifact_only_offline(tmp_path: Path):
    """With one sequential offline worker, private full memory and the
    stigmergic medium carry the same information, so outcomes coincide.
    The conditions differ in information *source* (private context vs store),
    which matters under replacement, parallelism, and live context limits."""
    persistent = run(_load("single_persistent"), tmp_path)
    stigmergic = run(_load("artifact_only"), tmp_path / "b")
    for key in ("promoted", "rejected", "lineage_depth", "holdout_score"):
        assert persistent[key] == stigmergic[key]
    assert persistent["condition"] == "single_persistent"


def test_single_persistent_ignores_store_failures(tmp_path: Path):
    """A pre-seeded failure record in the store must not steer a persistent
    worker (it has no access to the medium) — assert via observation builder."""
    from stigdev.store import RunStore
    from stigdev.worker import build_observation

    run(_load("artifact_only"), tmp_path)
    store = RunStore.open(tmp_path / "exp-artifact_only-seed42")
    with_medium = build_observation(store, _load("artifact_only"), episode=99)
    private = build_observation(store, _load("single_persistent"), 99, private_history=[])
    assert with_medium["failed_mutations"]  # store has failures
    assert private["failed_mutations"] == []  # private memory starts empty
    assert private["own_history"] == []


def test_best_of_n_isolated_workers_and_selection(tmp_path: Path):
    summary = run(_load("best_of_n"), tmp_path)
    run_dir = tmp_path / "exp-best_of_n-seed42"
    assert summary["condition"] == "best_of_n" and summary["n_workers"] == 4
    assert summary["episodes"] == 8  # 4 workers x 2 episodes, matched total budget
    worker_dirs = sorted((run_dir / "workers").iterdir())
    assert [d.name for d in worker_dirs] == ["w0", "w1", "w2", "w3"]
    scores = [w["score"] for w in summary["workers"]]
    assert summary["canonical"]["score"] == max(scores)
    assert summary["workers"][summary["selected_worker"]]["score"] == max(scores)
    # isolation: no worker event log references another worker's directory
    from stigdev.replay import replay

    parent_report = replay(run_dir)
    assert parent_report["ok"], parent_report["divergences"]
    for d in worker_dirs:
        report = replay(d)
        assert report["ok"], (d.name, report["divergences"])
