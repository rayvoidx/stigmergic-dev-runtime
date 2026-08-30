"""Run loop: seeds canonical state, executes worker episodes under an explicit
budget, and writes an auditable manifest.

Implemented conditions:
  artifact_only      ephemeral workers; coordination only via the shared store
                     (canonical artifact, lineage, evidence, failure records).
  single_persistent  one worker with private full-trajectory memory; it never
                     reads the store's failure records.
  best_of_n          n_workers fully isolated stores (nothing shared), each
                     with budget/n; the best final canonical is selected into
                     the parent store as a logged promotion.

full_communication and orchestrator are representable in RunConfig and refuse
to run rather than silently falling back.
"""

from __future__ import annotations

import platform
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import __version__
from .evaluator import EVALUATOR_ID, EVALUATOR_VERSION, TrendSelectEvaluator
from .model import CONDITIONS, IMPLEMENTED_CONDITIONS, RunConfig, content_hash, file_hash
from .policy import StrictImprovementPolicy
from .provider import OfflineTrendProvider, OllamaProvider
from .sandbox import SubprocessSandbox
from .store import RunStore
from .worker import PROMPT_TEMPLATE, run_episode

REPO_ROOT = Path(__file__).resolve().parents[1]


class ConditionNotImplementedError(NotImplementedError):
    pass


def default_fixtures_dir(version: str) -> Path:
    return REPO_ROOT / "benchmarks" / "trendevobench" / "fixtures" / version


def default_seed_artifact() -> Path:
    return REPO_ROOT / "benchmarks" / "trendevobench" / "seed_artifact.py"


def _fixtures_dir(config: RunConfig) -> Path:
    if config.fixtures_dir:
        return Path(config.fixtures_dir)
    return default_fixtures_dir(config.fixture_version)


def _make_provider(config: RunConfig) -> OfflineTrendProvider | OllamaProvider:
    if config.provider.provider == "ollama":
        return OllamaProvider(config.provider)
    return OfflineTrendProvider(config.provider, config.seed)


def _environment() -> dict[str, str]:
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "stigdev_version": __version__,
    }


def summarize(store: RunStore) -> dict[str, Any]:
    proposed = store.events("proposed")
    promoted = store.events("promoted")
    rejected = store.events("rejected")
    return {
        "episodes": len(store.events("episode_started")),
        "proposed": len(proposed),
        "promoted": len(promoted),
        "rejected": len(rejected),
        "accepted_ratio": round(len(promoted) / len(proposed), 4) if proposed else 0.0,
        "repeated_failure_attempts": sum(1 for e in proposed if e.get("repeated_failure")),
        "lineage_depth": max((e["generation"] for e in promoted), default=0),
        "canonical": store.canonical(),
    }


def run(
    config: RunConfig,
    runs_root: Path,
    seed_artifact_path: Path | None = None,
) -> dict[str, Any]:
    if config.condition not in CONDITIONS:
        raise ValueError(f"unknown condition {config.condition!r}; expected one of {CONDITIONS}")
    if config.condition not in IMPLEMENTED_CONDITIONS:
        raise ConditionNotImplementedError(
            f"condition {config.condition!r} is configurable but not implemented; "
            f"implemented: {IMPLEMENTED_CONDITIONS}. No silent fallback."
        )
    if config.provider.provider not in ("offline", "ollama"):
        raise NotImplementedError(
            f"provider {config.provider.provider!r} not implemented "
            "(implemented: offline, ollama); paid adapters require explicit approval"
        )
    if config.condition == "best_of_n":
        return _run_best_of_n(config, Path(runs_root), seed_artifact_path)
    return _run_sequential(config, Path(runs_root) / config.run_id, seed_artifact_path)


def _seed_canonical(
    store: RunStore,
    config: RunConfig,
    evaluator: TrendSelectEvaluator,
    seed_artifact_path: Path | None,
) -> tuple[str, Any]:
    seed_path = seed_artifact_path or default_seed_artifact()
    seed_hash = store.put_artifact(seed_path.read_text(encoding="utf-8"))
    seed_evidence = evaluator.evaluate(store, seed_hash, "train", config.k)
    if not seed_evidence.passed:
        raise RuntimeError(f"seed artifact failed hard checks: {seed_evidence.reason}")
    store.set_canonical(seed_hash, 0, seed_evidence.score)
    return seed_hash, seed_evidence


def _base_manifest(
    config: RunConfig, fixtures_dir: Path, seed_hash: str, policy_id: str
) -> dict[str, Any]:
    return {
        "run_id": config.run_id,
        "config": config.to_dict(),
        "environment": _environment(),
        "fixture_hashes": {p.name: file_hash(p) for p in sorted(fixtures_dir.glob("*.jsonl"))},
        "seed_artifact_hash": seed_hash,
        "evaluator_id": EVALUATOR_ID,
        "evaluator_version": EVALUATOR_VERSION,
        "policy_id": policy_id,
        "prompt_template_hash": content_hash(PROMPT_TEMPLATE),
    }


def _run_sequential(
    config: RunConfig,
    run_dir: Path,
    seed_artifact_path: Path | None = None,
) -> dict[str, Any]:
    fixtures_dir = _fixtures_dir(config)
    store = RunStore.create(run_dir)
    evaluator = TrendSelectEvaluator(fixtures_dir, SubprocessSandbox(), config.sandbox_timeout)
    policy = StrictImprovementPolicy()
    provider = _make_provider(config)
    seed_hash, seed_evidence = _seed_canonical(store, config, evaluator, seed_artifact_path)

    manifest = _base_manifest(config, fixtures_dir, seed_hash, policy.policy_id)
    store.append_event(
        "run_started",
        seed_score=seed_evidence.score,
        **{k: v for k, v in manifest.items() if k != "run_id"},
    )
    store.write_manifest(manifest)

    # single_persistent: the worker's memory is private and complete; it never
    # reads the store's failure records.
    private_history: list[dict[str, Any]] | None = (
        [] if config.condition == "single_persistent" else None
    )

    start = time.monotonic()
    provider_calls = 0
    cost = {"input_tokens": 0, "output_tokens": 0, "usd": 0.0}
    for episode in range(config.budget.max_episodes):
        if provider_calls >= config.budget.max_provider_calls:
            store.append_event("budget_exhausted", limit="max_provider_calls", episode=episode)
            break
        if time.monotonic() - start >= config.budget.max_wall_seconds:
            store.append_event("budget_exhausted", limit="max_wall_seconds", episode=episode)
            break
        outcome = run_episode(
            store, config, provider, evaluator, policy, episode, private_history
        )
        provider_calls += 1
        for key in ("input_tokens", "output_tokens", "usd"):
            cost[key] += outcome["cost"][key]
        if (
            config.budget.max_tokens > 0
            and cost["input_tokens"] + cost["output_tokens"] > config.budget.max_tokens
        ):
            store.append_event("budget_exhausted", limit="max_tokens", episode=episode)
            break
        if outcome["status"] == "no_proposal":
            break

    canonical = store.canonical()
    assert canonical is not None
    holdout_evidence = evaluator.evaluate(store, canonical["artifact_hash"], "holdout", config.k)
    store.append_event("holdout_evaluated", evidence=holdout_evidence.to_dict())

    summary = summarize(store)
    summary["condition"] = config.condition
    summary["seed_score_train"] = seed_evidence.score
    summary["holdout_score"] = holdout_evidence.score
    summary["holdout_metrics"] = holdout_evidence.metrics
    summary["provider_calls"] = provider_calls
    summary["wall_seconds"] = round(time.monotonic() - start, 3)
    summary["cost"] = cost
    store.append_event("run_finished", summary=summary)
    manifest["summary"] = summary
    store.write_manifest(manifest)
    return summary


def _run_best_of_n(
    config: RunConfig,
    runs_root: Path,
    seed_artifact_path: Path | None = None,
) -> dict[str, Any]:
    n = config.n_workers
    if n < 2:
        raise ValueError("best_of_n requires n_workers >= 2")
    per_episodes = config.budget.max_episodes // n
    per_calls = config.budget.max_provider_calls // n
    if per_episodes < 1:
        raise ValueError(
            f"budget too small: {config.budget.max_episodes} episodes across {n} workers"
        )

    fixtures_dir = _fixtures_dir(config)
    parent_dir = runs_root / config.run_id
    parent = RunStore.create(parent_dir)
    evaluator = TrendSelectEvaluator(fixtures_dir, SubprocessSandbox(), config.sandbox_timeout)
    policy = StrictImprovementPolicy()
    seed_hash, seed_evidence = _seed_canonical(parent, config, evaluator, seed_artifact_path)

    manifest = _base_manifest(config, fixtures_dir, seed_hash, policy.policy_id)
    parent.append_event(
        "run_started",
        seed_score=seed_evidence.score,
        **{k: v for k, v in manifest.items() if k != "run_id"},
    )
    parent.write_manifest(manifest)

    start = time.monotonic()
    worker_summaries: list[dict[str, Any]] = []
    for index in range(n):
        worker_config = replace(
            config,
            run_id=f"{config.run_id}.w{index}",
            condition="artifact_only",  # isolated single-chain search over its own store
            seed=config.seed + index,
            n_workers=1,
            budget=replace(
                config.budget,
                max_episodes=per_episodes,
                max_provider_calls=per_calls,
                max_tokens=config.budget.max_tokens // n,
                max_usd=config.budget.max_usd / n,
                max_wall_seconds=config.budget.max_wall_seconds / n,
            ),
        )
        worker_summary = _run_sequential(
            worker_config, parent_dir / "workers" / f"w{index}", seed_artifact_path
        )
        parent.append_event(
            "worker_finished", worker=index, seed=worker_config.seed, summary=worker_summary
        )
        worker_summaries.append(worker_summary)

    best_index = max(
        range(n), key=lambda i: (worker_summaries[i]["canonical"]["score"], -i)
    )
    best = worker_summaries[best_index]["canonical"]
    if best["artifact_hash"] != seed_hash:
        worker_store = RunStore.open(parent_dir / "workers" / f"w{best_index}")
        promoted_hash = parent.put_artifact(worker_store.get_artifact(best["artifact_hash"]))
        parent.set_canonical(promoted_hash, 1, best["score"])
        parent.append_event(
            "promoted",
            episode=-1,
            artifact_hash=promoted_hash,
            parent_hash=seed_hash,
            generation=1,
            mutation=f"best_of_n_select:w{best_index}",
            score=best["score"],
            reason=f"selected best of {n} isolated workers (w{best_index})",
            policy_id=policy.policy_id,
        )

    canonical = parent.canonical()
    assert canonical is not None
    holdout_evidence = evaluator.evaluate(parent, canonical["artifact_hash"], "holdout", config.k)
    parent.append_event("holdout_evaluated", evidence=holdout_evidence.to_dict())

    summary: dict[str, Any] = {
        "condition": "best_of_n",
        "n_workers": n,
        "selected_worker": best_index,
        "episodes": sum(w["episodes"] for w in worker_summaries),
        "proposed": sum(w["proposed"] for w in worker_summaries),
        "promoted": sum(w["promoted"] for w in worker_summaries),
        "rejected": sum(w["rejected"] for w in worker_summaries),
        "repeated_failure_attempts": sum(
            w["repeated_failure_attempts"] for w in worker_summaries
        ),
        "lineage_depth": worker_summaries[best_index]["lineage_depth"],
        "canonical": canonical,
        "seed_score_train": seed_evidence.score,
        "holdout_score": holdout_evidence.score,
        "holdout_metrics": holdout_evidence.metrics,
        "provider_calls": sum(w["provider_calls"] for w in worker_summaries),
        "wall_seconds": round(time.monotonic() - start, 3),
        "cost": {
            key: sum(w["cost"][key] for w in worker_summaries)
            for key in ("input_tokens", "output_tokens", "usd")
        },
        "workers": [
            {
                "worker": i,
                "seed": config.seed + i,
                "score": w["canonical"]["score"],
                "promoted": w["promoted"],
                "rejected": w["rejected"],
            }
            for i, w in enumerate(worker_summaries)
        ],
    }
    summary["accepted_ratio"] = (
        round(summary["promoted"] / summary["proposed"], 4) if summary["proposed"] else 0.0
    )
    parent.append_event("run_finished", summary=summary)
    manifest["summary"] = summary
    parent.write_manifest(manifest)
    return summary
