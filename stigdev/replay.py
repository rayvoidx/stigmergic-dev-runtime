"""Replay and recovery.

replay(): re-derives every recorded evaluation from stored artifact bytes and
fixtures, and re-checks the promotion chain. Any mismatch is a divergence —
the run is not reproducible or was tampered with.

recover(): restores canonical.json to the last accepted state derivable from
the append-only event log (rejected candidates never contaminate it).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .evaluator import EVALUATOR_VERSION, TrendSelectEvaluator
from .model import Evidence
from .sandbox import SubprocessSandbox
from .store import RunStore, StoreIntegrityError


def _expected_canonical(store: RunStore) -> dict[str, Any]:
    """Last accepted state according to the event log (promoted, else seed)."""
    promoted = store.events("promoted")
    if promoted:
        last = promoted[-1]
        return {
            "artifact_hash": last["artifact_hash"],
            "generation": last["generation"],
            "score": last["score"],
        }
    started = store.events("run_started")
    if not started:
        raise StoreIntegrityError("event log has no run_started event")
    return {
        "artifact_hash": started[0]["seed_artifact_hash"],
        "generation": 0,
        "score": started[0]["seed_score"],
    }


def replay(run_dir: Path) -> dict[str, Any]:
    store = RunStore.open(Path(run_dir))
    manifest = store.manifest()
    config = manifest["config"]
    divergences: list[str] = []

    if manifest["evaluator_version"] != EVALUATOR_VERSION:
        return {
            "ok": False,
            "checked": 0,
            "divergences": [
                f"evaluator version mismatch: run used {manifest['evaluator_version']}, "
                f"installed is {EVALUATOR_VERSION}; refusing to compare scores"
            ],
        }

    fixtures_dir = Path(config["fixtures_dir"]) if config["fixtures_dir"] else None
    if fixtures_dir is None:
        from .runtime import default_fixtures_dir

        fixtures_dir = default_fixtures_dir(config["fixture_version"])
    evaluator = TrendSelectEvaluator(fixtures_dir, SubprocessSandbox(), config["sandbox_timeout"])

    checked = 0
    for event in store.events("evaluated") + store.events("holdout_evaluated"):
        recorded = Evidence.from_dict(event["evidence"])
        try:
            store.get_artifact(recorded.artifact_hash)  # verifies content-hash integrity
        except (FileNotFoundError, StoreIntegrityError) as exc:
            divergences.append(f"artifact {recorded.artifact_hash[:12]}: {exc}")
            continue
        fresh = evaluator.evaluate(store, recorded.artifact_hash, recorded.split, config["k"])
        checked += 1
        if (fresh.passed, fresh.score) != (recorded.passed, recorded.score):
            divergences.append(
                f"artifact {recorded.artifact_hash[:12]} split={recorded.split}: recorded "
                f"passed={recorded.passed} score={recorded.score}, replayed "
                f"passed={fresh.passed} score={fresh.score}"
            )

    # Promotion chain: each promoted event must extend the previous canonical.
    expected_parent = store.events("run_started")[0]["seed_artifact_hash"]
    for event in store.events("promoted"):
        if event["parent_hash"] != expected_parent:
            divergences.append(
                f"lineage break at generation {event['generation']}: parent "
                f"{event['parent_hash'][:12]} != expected {expected_parent[:12]}"
            )
        expected_parent = event["artifact_hash"]

    canonical = store.canonical()
    expected = _expected_canonical(store)
    if canonical != expected:
        divergences.append(f"canonical pointer {canonical} != event-log expectation {expected}")

    return {"ok": not divergences, "checked": checked, "divergences": divergences}


def recover(run_dir: Path) -> dict[str, Any]:
    store = RunStore.open(Path(run_dir))
    expected = _expected_canonical(store)
    current = store.canonical()
    try:
        store.get_artifact(expected["artifact_hash"])
    except (FileNotFoundError, StoreIntegrityError):
        return {
            "recovered": False,
            "reason": f"last accepted artifact {expected['artifact_hash'][:12]} missing or corrupt",
            "canonical": current,
        }
    if current == expected:
        return {
            "recovered": False,
            "reason": "canonical pointer already valid",
            "canonical": current,
        }
    store.set_canonical(expected["artifact_hash"], expected["generation"], expected["score"])
    store.append_event("recovered", previous=current, restored=expected)
    return {
        "recovered": True,
        "reason": "canonical pointer restored from event log",
        "canonical": expected,
    }
