"""RQ4 replacement harness: worker/provider replacement mid-run.

The claim under test (mechanism level, offline deterministic worker):
- replacing a persistent worker destroys its private memory -> it repeats a
  recorded failure the store still knows about;
- the same replacement is informationally a no-op under artifact_only;
- replacing the provider with a failure-memory-less variant wastes the
  remaining budget on repeats and caps the final score.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from stigdev.model import ProviderSpec, RunConfig
from stigdev.runtime import run
from stigdev.store import RunStore


def _config(condition: str, run_id: str, **kwargs) -> RunConfig:
    return RunConfig(run_id=run_id, condition=condition, seed=42, **kwargs)


def test_worker_replacement_wipes_persistent_memory(tmp_path: Path):
    summary = run(_config("single_persistent", "rq4-single", replace_at_episode=2), tmp_path)
    store = RunStore.open(tmp_path / "rq4-single")

    replaced = store.events("worker_replaced")
    assert [e["episode"] for e in replaced] == [2]
    assert replaced[0]["lost_private_entries"] == 2  # ep0 rejection + ep1 promotion
    assert summary["worker_replaced_at"] == [2]

    # The replacement worker, memoryless, re-proposes the mutation its
    # predecessor already saw fail at ep0 — and the objective metric counts it.
    ep2 = next(e for e in store.events("proposed") if e["episode"] == 2)
    assert ep2["mutation"] == "short_filter"
    assert ep2["repeated_failure"] is True


def test_worker_replacement_is_noop_for_artifact_only(tmp_path: Path):
    baseline = run(_config("artifact_only", "base"), tmp_path)
    replaced = run(_config("artifact_only", "repl", replace_at_episode=2), tmp_path / "b")

    volatile = ("wall_seconds", "worker_replaced_at")
    assert {k: v for k, v in baseline.items() if k not in volatile} == {
        k: v for k, v in replaced.items() if k not in volatile
    }
    assert replaced["worker_replaced_at"] == [2]
    event = RunStore.open(tmp_path / "b" / "repl").events("worker_replaced")[0]
    assert event["lost_private_entries"] == 0  # nothing to lose: state lives in the store


def test_provider_replacement_without_failure_memory_degrades(tmp_path: Path):
    baseline = run(_config("artifact_only", "base"), tmp_path)
    degraded = run(
        _config(
            "artifact_only",
            "swap",
            replace_at_episode=3,
            replacement_provider=ProviderSpec(use_failure_memory=False),
        ),
        tmp_path / "b",
    )
    assert degraded["provider_replaced_at"] == [3]
    # every post-swap episode re-proposes a recorded failure
    assert degraded["repeated_failure_attempts"] >= 4
    assert degraded["promoted"] == 2  # never reaches the dedup improvement
    assert degraded["canonical"]["score"] == pytest.approx(0.84)
    assert degraded["canonical"]["score"] < baseline["canonical"]["score"]


def test_replacement_config_round_trip():
    config = _config(
        "single_persistent",
        "rt",
        replace_at_episode=3,
        replacement_provider=ProviderSpec(use_failure_memory=False),
    )
    import json

    restored = RunConfig.from_dict(json.loads(json.dumps(config.to_dict())))
    assert restored == config
    assert restored.replacement_provider == replace(ProviderSpec(), use_failure_memory=False)
