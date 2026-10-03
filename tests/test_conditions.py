"""The five experimental conditions are configurable with matched budgets;
unimplemented ones refuse to run instead of silently falling back."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stigdev.model import CONDITIONS, IMPLEMENTED_CONDITIONS, Budget, RunConfig
from stigdev.replay import replay
from stigdev.runtime import ConditionNotImplementedError, run
from stigdev.store import RunStore
from stigdev.worker import build_observation

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


def test_an_unknown_condition_still_refuses_to_run(tmp_path: Path):
    """All five are implemented now, so the fail-closed path is only reachable
    through an unknown name; the refusal itself must not rot."""
    from dataclasses import replace as _replace

    with pytest.raises(ValueError):
        run(_replace(_load("artifact_only"), condition="telepathy"), tmp_path)
    assert issubclass(ConditionNotImplementedError, NotImplementedError)


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


def test_observe_promotion_history_enriches_stigmergic_medium(tmp_path: Path):
    """Ablation flag: medium can also transmit what worked, not only failures.
    Default stays off (baseline observation unchanged)."""
    from dataclasses import replace

    from stigdev.store import RunStore
    from stigdev.worker import build_observation

    base = _load("artifact_only")
    run(base, tmp_path)
    store = RunStore.open(tmp_path / base.run_id)

    default_obs = build_observation(store, base, episode=99)
    assert "promotions" not in default_obs and "own_history" not in default_obs

    rich = replace(base, observe_promotion_history=True)
    rich_obs = build_observation(store, rich, episode=99)
    assert [p["mutation"] for p in rich_obs["promotions"]] == ["recency", "keyword", "dedup"]
    assert all(set(p) == {"mutation", "score", "generation"} for p in rich_obs["promotions"])

    # persistent workers keep their private view; the flag must not leak there
    persistent_obs = build_observation(store, rich, 99, private_history=[])
    assert "promotions" not in persistent_obs and persistent_obs["own_history"] == []

    # attempt-level ablation: recent failed candidates' actual (truncated) code
    attempt = replace(base, observe_failure_sources=True)
    attempt_obs = build_observation(store, attempt, episode=99)
    sources = attempt_obs["failure_sources"]
    assert 1 <= len(sources) <= 3
    assert all(
        "select_trends" in s["source"] and len(s["source"]) <= 1200 for s in sources
    )
    assert "failure_sources" not in build_observation(store, base, episode=99)
    assert "failure_sources" not in build_observation(store, attempt, 99, private_history=[])


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


# --- full_communication and orchestrator (gap 2) ------------------------------


def _cfg(condition: str, tmp_path: Path, **kw) -> RunConfig:
    base = dict(
        run_id=f"{condition}-run",
        condition=condition,
        seed=42,
        budget=Budget(max_episodes=6, max_provider_calls=12, max_wall_seconds=120.0),
    )
    base.update(kw)
    return RunConfig(**base)


def _run(condition: str, tmp_path: Path, **kw):
    config = _cfg(condition, tmp_path, **kw)
    summary = run(config, tmp_path / condition)
    return config, summary, RunStore.open(tmp_path / condition / config.run_id)


def test_both_remaining_conditions_are_implemented():
    assert set(CONDITIONS) == set(IMPLEMENTED_CONDITIONS)


def test_full_communication_is_artifact_only_plus_a_logged_channel(tmp_path: Path):
    _, summary, store = _run("full_communication", tmp_path)
    broadcasts = store.events("message_broadcast")
    assert broadcasts, "workers must leave a logged message trail"
    assert [b["episode"] for b in broadcasts] == sorted(b["episode"] for b in broadcasts)
    # the store medium is still there: this arm ADDS a channel, it does not replace one
    assert summary["condition"] == "full_communication"
    assert store.canonical() is not None


def test_a_full_communication_worker_hears_the_previous_worker(tmp_path: Path):
    config = _cfg("full_communication", tmp_path)
    store = RunStore.create(tmp_path / "obs")
    artifact = store.put_artifact("x = 1\n")
    store.set_canonical(artifact, 0, 0.5)
    channel = [{"episode": 0, "worker": "w0", "status": "rejected", "mutation": "m0", "score": 0.4}]
    observation = build_observation(store, config, 1, None, channel)
    assert observation["messages"] == channel
    assert "failures" in observation, "full_communication keeps the stigmergic medium"
    # strictly more context than the same worker without the channel
    quiet = build_observation(store, config, 1)
    assert len(json.dumps(observation, sort_keys=True)) > len(json.dumps(quiet, sort_keys=True))


def test_the_offline_provider_cannot_measure_the_cost_half_of_h2(tmp_path: Path):
    """The channel is strictly more context, but the deterministic offline
    provider reports zero cost, so H2's token claim needs a live provider.
    Pinned so nobody reads an offline matrix as evidence about cost."""
    _, chatty, _ = _run("full_communication", tmp_path)
    _, quiet, _ = _run("artifact_only", tmp_path)
    assert chatty["cost"] == quiet["cost"] == {"input_tokens": 0, "output_tokens": 0, "usd": 0.0}


def test_orchestrator_logs_every_delegation(tmp_path: Path):
    _, summary, store = _run("orchestrator", tmp_path)
    delegations = store.events("delegated")
    assert delegations, "a central planner must log what it delegated"
    assert all(d["directive"] for d in delegations)
    assert [d["episode"] for d in delegations] == sorted(d["episode"] for d in delegations)
    assert summary["condition"] == "orchestrator"


def test_an_orchestrated_worker_sees_the_directive_instead_of_the_raw_medium(tmp_path: Path):
    config = _cfg("orchestrator", tmp_path)
    store = RunStore.create(tmp_path / "obs")
    artifact = store.put_artifact("x = 1\n")
    store.set_canonical(artifact, 0, 0.5)
    observation = build_observation(store, config, 0, None, None, {"focus": "recency", "avoid": []})
    assert observation["directive"] == {"focus": "recency", "avoid": []}
    assert "failures" not in observation, "the planner distils the medium; the worker does not read it"


def test_the_planner_spends_no_provider_call(tmp_path: Path):
    # matched budgets: delegation must not buy the orchestrator arm extra inference
    _, orchestrated, store = _run("orchestrator", tmp_path)
    assert orchestrated["provider_calls"] == len(store.events("episode_started"))


@pytest.mark.parametrize("condition", ["full_communication", "orchestrator"])
def test_new_conditions_are_deterministic_and_replay_clean(condition: str, tmp_path: Path):
    _, first, _ = _run(condition, tmp_path / "a")
    _, second, _ = _run(condition, tmp_path / "b")
    assert first["holdout_score"] == second["holdout_score"]
    assert first["cost"] == second["cost"]
    config = _cfg(condition, tmp_path)
    report = replay(tmp_path / "a" / condition / config.run_id)
    assert report["ok"], report


@pytest.mark.parametrize("condition", ["full_communication", "orchestrator"])
def test_new_conditions_respect_the_matched_budget(condition: str, tmp_path: Path):
    _, summary, store = _run(condition, tmp_path, budget=Budget(max_episodes=2, max_provider_calls=4))
    assert len(store.events("episode_started")) <= 2
