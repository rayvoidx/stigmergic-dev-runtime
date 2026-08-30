"""Typed core data model shared by the runtime, evaluators, and CLI."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = 1

CONDITIONS = (
    "single_persistent",
    "best_of_n",
    "artifact_only",
    "full_communication",
    "orchestrator",
)
# Implemented conditions; full_communication and orchestrator remain config-only.
IMPLEMENTED_CONDITIONS = ("single_persistent", "best_of_n", "artifact_only")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_hash(path: Any) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class Budget:
    """Matched-budget fields shared by all experimental conditions."""

    max_episodes: int = 8
    max_provider_calls: int = 16
    max_tokens: int = 0  # 0 = no token budget (offline provider spends none anyway)
    max_usd: float = 0.0
    max_wall_seconds: float = 300.0


@dataclass(frozen=True)
class ProviderSpec:
    provider: str = "offline"
    model_id: str = "offline-deterministic/v1"
    effort: str | None = None
    temperature: float = 0.0
    max_output_tokens: int = 0
    use_failure_memory: bool = True  # RQ3 toggle: inherit failure records or not


@dataclass(frozen=True)
class RunConfig:
    run_id: str
    condition: str = "artifact_only"
    seed: int = 42
    k: int = 10
    fixture_version: str = "v1"
    fixtures_dir: str | None = None  # default: benchmarks/trendevobench/fixtures/<version>
    budget: Budget = field(default_factory=Budget)
    provider: ProviderSpec = field(default_factory=ProviderSpec)
    policy_id: str = "strict-improve/v1"
    sandbox_timeout: float = 10.0
    n_workers: int = 1  # best_of_n only: independent workers sharing nothing
    # RQ4 replacement schedule (-1 / None = never). Worker replacement wipes a
    # persistent worker's private memory; artifact_only workers are ephemeral
    # already, so for them it is logged but informationally a no-op.
    replace_at_episode: int = -1
    replacement_provider: ProviderSpec | None = None
    # Ablation (pilot 2026-08-30 confound): when true, the stigmergic medium
    # also exposes recent promotion history to workers, matching the
    # information richness a persistent worker gets from its own trajectory.
    observe_promotion_history: bool = False
    # Second ablation rung: medium carries attempt-level context — the actual
    # source of recent rejected candidates (truncated), not just summary
    # tuples. Tests whether the persistent worker's advantage is "seeing
    # prior attempt code" rather than "seeing outcomes".
    observe_failure_sources: bool = False

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "RunConfig":
        data = dict(raw)
        if isinstance(data.get("budget"), dict):
            data["budget"] = Budget(**data["budget"])
        if isinstance(data.get("provider"), dict):
            data["provider"] = ProviderSpec(**data["provider"])
        if isinstance(data.get("replacement_provider"), dict):
            data["replacement_provider"] = ProviderSpec(**data["replacement_provider"])
        return RunConfig(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Evidence:
    """Result of one evaluator applied to one artifact on one fixture split."""

    evaluator_id: str
    evaluator_version: str
    artifact_hash: str
    split: str
    passed: bool  # hard checks (ran, well-formed output, within contract)
    score: float  # composite; comparable only within one evaluator version
    metrics: dict[str, float]
    reason: str = ""  # populated when hard checks fail

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Evidence":
        return Evidence(**raw)


@dataclass(frozen=True)
class PromotionDecision:
    promote: bool
    reason: str
    policy_id: str
