"""Run loop: seeds canonical state, executes worker episodes under an explicit
budget, and writes an auditable manifest.

Only the artifact_only condition is implemented. The other four experimental
conditions are representable in RunConfig (matched-budget fields) and refuse
to run rather than silently falling back.
"""

from __future__ import annotations

import platform
import sys
import time
from pathlib import Path
from typing import Any

from . import __version__
from .evaluator import EVALUATOR_ID, EVALUATOR_VERSION, TrendSelectEvaluator
from .model import CONDITIONS, IMPLEMENTED_CONDITIONS, RunConfig, content_hash, file_hash
from .policy import StrictImprovementPolicy
from .provider import OfflineTrendProvider
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
    if config.provider.provider != "offline":
        raise NotImplementedError(
            "only the offline deterministic provider is implemented; "
            "live adapters are future work and must never run inside tests"
        )

    fixtures_dir = (
        Path(config.fixtures_dir)
        if config.fixtures_dir
        else default_fixtures_dir(config.fixture_version)
    )
    seed_path = seed_artifact_path or default_seed_artifact()

    store = RunStore.create(Path(runs_root) / config.run_id)
    sandbox = SubprocessSandbox()
    evaluator = TrendSelectEvaluator(fixtures_dir, sandbox, config.sandbox_timeout)
    policy = StrictImprovementPolicy()
    provider = OfflineTrendProvider(config.provider, config.seed)

    seed_source = seed_path.read_text(encoding="utf-8")
    seed_hash = store.put_artifact(seed_source)
    seed_evidence = evaluator.evaluate(store, seed_hash, "train", config.k)
    if not seed_evidence.passed:
        raise RuntimeError(f"seed artifact failed hard checks: {seed_evidence.reason}")
    store.set_canonical(seed_hash, 0, seed_evidence.score)

    fixture_hashes = {p.name: file_hash(p) for p in sorted(fixtures_dir.glob("*.jsonl"))}
    environment = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "stigdev_version": __version__,
    }
    store.append_event(
        "run_started",
        config=config.to_dict(),
        environment=environment,
        fixture_hashes=fixture_hashes,
        seed_artifact_hash=seed_hash,
        seed_score=seed_evidence.score,
        evaluator_id=EVALUATOR_ID,
        evaluator_version=EVALUATOR_VERSION,
        policy_id=policy.policy_id,
        prompt_template_hash=content_hash(PROMPT_TEMPLATE),
    )
    manifest: dict[str, Any] = {
        "run_id": config.run_id,
        "config": config.to_dict(),
        "environment": environment,
        "fixture_hashes": fixture_hashes,
        "seed_artifact_hash": seed_hash,
        "evaluator_id": EVALUATOR_ID,
        "evaluator_version": EVALUATOR_VERSION,
        "policy_id": policy.policy_id,
        "prompt_template_hash": content_hash(PROMPT_TEMPLATE),
    }
    store.write_manifest(manifest)

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
        outcome = run_episode(store, config, provider, evaluator, policy, episode)
        provider_calls += 1
        for key in ("input_tokens", "output_tokens", "usd"):
            cost[key] += outcome["cost"][key]
        if cost["input_tokens"] + cost["output_tokens"] > config.budget.max_tokens:
            store.append_event("budget_exhausted", limit="max_tokens", episode=episode)
            break
        if outcome["status"] == "no_proposal":
            break

    canonical = store.canonical()
    assert canonical is not None
    holdout_evidence = evaluator.evaluate(store, canonical["artifact_hash"], "holdout", config.k)
    store.append_event("holdout_evaluated", evidence=holdout_evidence.to_dict())

    summary = summarize(store)
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
