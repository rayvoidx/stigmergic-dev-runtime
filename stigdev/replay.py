"""Replay and recovery.

replay(): validates the event log, re-derives every recorded evaluation from
stored artifact bytes and fixtures and compares the complete evidence, re-runs
every promotion decision against the recorded evidence, and re-checks the
promotion chain and canonical pointer. Any mismatch is a divergence — the run
is not reproducible or was tampered with. replay_store() does the same for a
run imported into the v2 event store.

recover(): restores canonical.json to the last accepted state derivable from
the append-only event log (rejected candidates never contaminate it).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .evaluator import EVALUATOR_VERSION, TrendSelectEvaluator
from .model import Evidence
from .policy import POLICY_ID, StrictImprovementPolicy
from .sandbox import SubprocessSandbox
from .store import RunStore, StoreIntegrityError

if TYPE_CHECKING:
    from .eventstore import SqliteEventStore


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


def _refuse(reason: str) -> dict[str, Any]:
    return {"ok": False, "checked": 0, "decisions": 0, "divergences": [reason]}


def _load_events(store: RunStore) -> list[dict[str, Any]]:
    """Parse the event log strictly: every line JSON, seq strictly increasing."""
    events: list[dict[str, Any]] = []
    last = 0
    with store.events_path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise StoreIntegrityError(f"line {lineno} is not JSON: {exc.msg}") from exc
            seq = event.get("seq") if isinstance(event, dict) else None
            if type(seq) is not int or seq <= last:
                raise StoreIntegrityError(f"event sequence broken at line {lineno}: seq={seq!r} after {last}")
            last = seq
            events.append(event)
    return events


def _replay_decisions(events: list[dict[str, Any]], divergences: list[str]) -> int:
    """Re-run the promotion policy on recorded evidence; returns decisions checked."""
    started = [e for e in events if e["type"] == "run_started"]
    if not started:
        divergences.append("event log has no run_started event")
        return 0
    policy = StrictImprovementPolicy()
    canonical_score = started[0]["seed_score"]
    generation = 0
    pending: dict[int, dict[str, Any]] = {}
    decisions = 0
    for event in events:
        kind = event["type"]
        if kind == "evaluated":
            episode = event.get("episode")
            if episode in pending:
                divergences.append(f"episode {episode}: evaluated twice without a decision")
            pending[episode] = event["evidence"]
        elif kind in ("promoted", "rejected"):
            episode = event.get("episode")
            raw = pending.pop(episode, None)
            if raw is None:
                if kind == "promoted" and episode == -1:  # best_of_n selection carries no local evidence
                    generation = event["generation"]
                    canonical_score = event["score"]
                else:
                    divergences.append(f"episode {episode}: {kind} without an evaluated event")
                continue
            decisions += 1
            recorded = Evidence.from_dict(raw)
            decision = policy.decide(recorded, canonical_score)
            expected = "promoted" if decision.promote else "rejected"
            if kind != expected:
                divergences.append(
                    f"episode {episode}: decision mismatch: recorded {kind}, policy {POLICY_ID} "
                    f"decides {expected} ({decision.reason})"
                )
            elif event.get("reason") != decision.reason:
                divergences.append(
                    f"episode {episode}: policy reason {event.get('reason')!r} != replayed {decision.reason!r}"
                )
            if event.get("policy_id") != decision.policy_id:
                divergences.append(f"episode {episode}: policy_id {event.get('policy_id')!r} != {decision.policy_id!r}")
            if event.get("artifact_hash") != recorded.artifact_hash:
                divergences.append(f"episode {episode}: {kind} artifact != evaluated artifact")
            if event.get("score") != recorded.score:
                divergences.append(f"episode {episode}: {kind} score {event.get('score')} != evidence score {recorded.score}")
            if kind == "promoted":
                if event.get("generation") != generation + 1:
                    divergences.append(f"episode {episode}: generation {event.get('generation')} != expected {generation + 1}")
                generation += 1
                canonical_score = recorded.score
    for episode in sorted(pending, key=str):
        divergences.append(f"episode {episode}: evaluated without a recorded decision")
    return decisions


def replay(run_dir: Path) -> dict[str, Any]:
    try:
        store = RunStore.open(Path(run_dir))
        events = _load_events(store)
    except (json.JSONDecodeError, StoreIntegrityError) as exc:
        return _refuse(f"event log unreadable: {exc}")
    manifest = store.manifest()
    config = manifest["config"]
    divergences: list[str] = []

    if manifest["evaluator_version"] != EVALUATOR_VERSION:
        return _refuse(
            f"evaluator version mismatch: run used {manifest['evaluator_version']}, "
            f"installed is {EVALUATOR_VERSION}; refusing to compare scores"
        )
    if manifest.get("policy_id") != POLICY_ID:
        return _refuse(
            f"policy version mismatch: run used {manifest.get('policy_id')}, installed is "
            f"{POLICY_ID}; refusing to re-run decisions"
        )

    fixtures_dir = Path(config["fixtures_dir"]) if config["fixtures_dir"] else None
    if fixtures_dir is None:
        from .runtime import default_fixtures_dir

        fixtures_dir = default_fixtures_dir(config["fixture_version"])
    evaluator = TrendSelectEvaluator(fixtures_dir, SubprocessSandbox(), config["sandbox_timeout"])

    checked = 0
    for event in [e for e in events if e["type"] in ("evaluated", "holdout_evaluated")]:
        recorded = Evidence.from_dict(event["evidence"])
        try:
            store.get_artifact(recorded.artifact_hash)  # verifies content-hash integrity
        except (FileNotFoundError, StoreIntegrityError) as exc:
            divergences.append(f"artifact {recorded.artifact_hash[:12]}: {exc}")
            continue
        fresh = evaluator.evaluate(store, recorded.artifact_hash, recorded.split, config["k"])
        checked += 1
        fresh_dict, recorded_dict = fresh.to_dict(), recorded.to_dict()
        if fresh_dict != recorded_dict:
            differing = sorted(k for k in fresh_dict if fresh_dict[k] != recorded_dict.get(k))
            divergences.append(
                f"artifact {recorded.artifact_hash[:12]} split={recorded.split}: evidence differs in "
                f"{', '.join(differing)} (recorded passed={recorded.passed} score={recorded.score}, "
                f"replayed passed={fresh.passed} score={fresh.score})"
            )

    decisions = _replay_decisions(events, divergences)

    # Promotion chain: each promoted event must extend the previous canonical.
    started = [e for e in events if e["type"] == "run_started"]
    expected_parent = started[0]["seed_artifact_hash"] if started else None
    for event in [e for e in events if e["type"] == "promoted"]:
        if event["parent_hash"] != expected_parent:
            divergences.append(
                f"lineage break at generation {event['generation']}: parent "
                f"{event['parent_hash'][:12]} != expected {str(expected_parent)[:12]}"
            )
        expected_parent = event["artifact_hash"]

    canonical = store.canonical()
    try:
        expected = _expected_canonical(store)
    except StoreIntegrityError as exc:
        expected = None
        divergences.append(str(exc))
    if expected is not None and canonical != expected:
        divergences.append(f"canonical pointer {canonical} != event-log expectation {expected}")

    return {"ok": not divergences, "checked": checked, "decisions": decisions, "divergences": divergences}


def replay_store(store: "SqliteEventStore", run_id: str) -> dict[str, Any]:
    """Replay a run held in the v2 event store by exporting it to a temporary v1 layout."""
    from .v1import import export_run

    with tempfile.TemporaryDirectory() as tmp:
        try:
            run_dir = export_run(store, run_id, Path(tmp) / run_id)
        except (KeyError, StoreIntegrityError) as exc:
            return _refuse(f"store export failed: {exc}")
        return replay(run_dir)


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
