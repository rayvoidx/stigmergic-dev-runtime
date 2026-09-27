"""Model Radar promotion gate and rollout ladder (ADR 0010).

New local models may be discovered automatically but never promoted
automatically (Blueprint v2 §10.3, §22.6): same benchmark suite, strict quality
gain, memory and latency inside budget, no extra human editing, enough shadow
artifacts, zero critical regressions, cleared license, and a named approver.
Pure functions; no model is loaded here.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any

from .portfolio import GateDecision
from .workspace import valid_identifier

LICENSE_STATES = ("unknown", "restricted", "commercial_ok")
ROLLOUT_STAGES = (
    "discovered",
    "quarantined",
    "licensed",
    "smoke",
    "private_eval",
    "shadow",
    "canary_5",
    "canary_25",
    "canary_50",
    "full",
)
PROMOTION_GATE_ID = "model-promotion/v1"
_LABEL = re.compile(r"\S{1,128}")


class RadarError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RadarError(message)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _label(value: object) -> bool:
    return isinstance(value, str) and _LABEL.fullmatch(value) is not None


class _Record:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[call-overload]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]):
        return cls(**raw)


@dataclass(frozen=True)
class ModelSnapshot(_Record):
    """What an attempt actually ran (Blueprint v2 §10.2), minus sampling which lives on the attempt."""

    alias: str
    model_id: str
    revision: str
    runtime: str
    quantization: str
    prompt_bundle: str
    license_state: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.alias, "alias"),
            (self.model_id, "model_id"),
            (self.revision, "revision"),
            (self.runtime, "runtime"),
            (self.quantization, "quantization"),
        ):
            _require(valid_identifier(value), f"invalid {name}")
        _require(_label(self.prompt_bundle), "invalid prompt_bundle")
        _require(self.license_state in LICENSE_STATES, f"unknown license_state {self.license_state!r}")


@dataclass(frozen=True)
class BenchmarkResult(_Record):
    """One model revision measured on one versioned suite; metrics carry no timings from live runs."""

    model_id: str
    revision: str
    suite_version: str
    quality: float
    peak_memory_gb: float
    p95_latency_s: float
    human_edit_minutes: float
    shadow_artifacts: int
    critical_regressions: int

    def __post_init__(self) -> None:
        _require(valid_identifier(self.model_id), "invalid model_id")
        _require(valid_identifier(self.revision), "invalid revision")
        _require(_label(self.suite_version), "invalid suite_version")
        for value, name in (
            (self.quality, "quality"),
            (self.peak_memory_gb, "peak_memory_gb"),
            (self.p95_latency_s, "p95_latency_s"),
            (self.human_edit_minutes, "human_edit_minutes"),
        ):
            _require(_finite(value) and value >= 0, f"{name} must be a finite non-negative number")
        _require(_count(self.shadow_artifacts), "shadow_artifacts must be a non-negative int")
        _require(_count(self.critical_regressions), "critical_regressions must be a non-negative int")


@dataclass(frozen=True)
class PromotionBudget(_Record):
    max_peak_memory_gb: float
    max_p95_latency_s: float
    min_shadow_artifacts: int = 20
    min_quality_gain: float = 0.0

    def __post_init__(self) -> None:
        _require(_finite(self.max_peak_memory_gb) and self.max_peak_memory_gb > 0, "max_peak_memory_gb must be positive")
        _require(_finite(self.max_p95_latency_s) and self.max_p95_latency_s > 0, "max_p95_latency_s must be positive")
        _require(_count(self.min_shadow_artifacts), "min_shadow_artifacts must be a non-negative int")
        _require(_finite(self.min_quality_gain) and self.min_quality_gain >= 0, "min_quality_gain must be >= 0")


def model_promotion_gate(
    current: BenchmarkResult | None,
    candidate: BenchmarkResult,
    snapshot: ModelSnapshot,
    budget: PromotionBudget,
    approved_by: str,
) -> GateDecision:
    """Every Blueprint §10.3 condition at once; any reason blocks. `current is None` seeds an alias."""
    reasons: list[str] = []
    if (candidate.model_id, candidate.revision) != (snapshot.model_id, snapshot.revision):
        reasons.append(f"benchmark does not cover snapshot {snapshot.model_id}@{snapshot.revision}")
    if current is not None and candidate.suite_version != current.suite_version:
        reasons.append(f"benchmark suite mismatch: {candidate.suite_version} vs {current.suite_version}")
    if snapshot.license_state != "commercial_ok":
        reasons.append("license not cleared for commercial use")
    if current is not None and candidate.quality <= current.quality + budget.min_quality_gain:
        reasons.append(f"quality {candidate.quality:.6f} did not improve on {current.quality:.6f}")
    if candidate.peak_memory_gb > budget.max_peak_memory_gb:
        reasons.append(f"peak memory {candidate.peak_memory_gb:.1f} GB over budget {budget.max_peak_memory_gb:.1f} GB")
    if candidate.p95_latency_s > budget.max_p95_latency_s:
        reasons.append(f"p95 latency {candidate.p95_latency_s:.1f} s over budget {budget.max_p95_latency_s:.1f} s")
    if current is not None and candidate.human_edit_minutes > current.human_edit_minutes:
        reasons.append(
            f"human edit time increased {current.human_edit_minutes:.1f} -> {candidate.human_edit_minutes:.1f} minutes"
        )
    if candidate.shadow_artifacts < budget.min_shadow_artifacts:
        reasons.append(f"fewer than {budget.min_shadow_artifacts} shadow artifacts")
    if candidate.critical_regressions > 0:
        reasons.append("critical regressions present")
    if not approved_by.strip():
        reasons.append("operator approval missing")
    return GateDecision(PROMOTION_GATE_ID, not reasons, tuple(reasons))


def next_rollout_stage(stage: str) -> str:
    """Strictly sequential ladder; skipping a rung is not a valid transition."""
    _require(stage in ROLLOUT_STAGES, f"unknown rollout stage {stage!r}")
    _require(stage != "full", "rollout already full")
    return ROLLOUT_STAGES[ROLLOUT_STAGES.index(stage) + 1]


def rollback_stage(stage: str) -> str:
    """Any rung can drop straight back to quarantine; that is what makes promotion reversible."""
    _require(stage in ROLLOUT_STAGES, f"unknown rollout stage {stage!r}")
    return "quarantined"
