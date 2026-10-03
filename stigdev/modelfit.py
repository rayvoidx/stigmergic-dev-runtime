"""Memory-fitted model shortlisting (ADR 0015).

A public leaderboard says which open models are good in general. This module
answers a narrower question the leaderboard cannot: which of them will fit in
the memory this machine is willing to give one job.

What it deliberately does not do is choose. A ranking is a third-party claim —
the same kind of evidence as an external revenue claim (ADR 0009) or a borrowed
metric hypothesis (ADR 0007) — so it produces *candidates to benchmark*, never
a deployment. `stigdev.modelradar` still decides, and it reads measurements.

Two safety rules fall out of that:

* The estimate errs high. Under-estimating on a 16 GB laptop means the machine
  swaps or the job is killed; over-estimating costs one skipped candidate.
* A model the operator could not sell with is never shortlisted by default.
  Channel work is commercial, and a licence is a rights question, not a
  performance one.

Nothing here touches the network. `scripts/fetch_model_rankings.py` is the
half that does.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable, Sequence

from .modelradar import LICENSE_STATES, ModelSnapshot
from .node import NodeProfile, ResourceClass
from .portfolio import EVIDENCE_GRADES
from .workspace import valid_identifier

# Bytes per parameter by quantisation. Planning figures for GGUF/MLX-style
# weights, not measurements.
# ponytail: a lookup table with a known ceiling — it ignores architecture,
# context length and KV cache growth. Replace an entry the first time a real
# `BenchmarkResult.peak_memory_gb` contradicts it.
BYTES_PER_PARAM: dict[str, float] = {
    "q3": 0.45,
    "q4": 0.60,
    "q5": 0.70,
    "q6": 0.85,
    "q8": 1.10,
    "f16": 2.10,
}
# Runtime, tokenizer, and a modest KV cache on top of the weights. Deliberately
# generous: the cost of guessing low is an OOM on the operator's only machine.
RUNTIME_OVERHEAD_GB = 1.5
# A leaderboard is someone else's measurement, so grade A is not available here.
LEADERBOARD_GRADES = tuple(g for g in EVIDENCE_GRADES if g != "A")


class ModelFitError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ModelFitError(message)


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _timestamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ModelFitError(f"invalid timestamp {value!r}") from exc
    _require(parsed.tzinfo is not None, f"timestamp {value!r} must be timezone-aware")
    return parsed


@dataclass(frozen=True)
class ModelCandidate:
    """One row of a public ranking, plus what is needed to size it."""

    model_id: str
    params_b: float
    quantization: str
    rank: int
    source: str
    captured_at: str
    license_state: str = "unknown"
    evidence_grade: str = "B"
    score: float | None = None

    def __post_init__(self) -> None:
        _require(valid_identifier(self.model_id), "invalid model_id")
        _require(_finite(self.params_b) and self.params_b > 0, "params_b must be a finite positive number")
        _require(self.quantization in BYTES_PER_PARAM, f"unknown quantization {self.quantization!r}")
        _require(
            isinstance(self.rank, int) and not isinstance(self.rank, bool) and self.rank >= 1,
            "rank must be an integer of at least 1",
        )
        _require(isinstance(self.source, str) and bool(self.source.strip()), "source missing")
        _timestamp(self.captured_at)
        _require(self.license_state in LICENSE_STATES, f"unknown license_state {self.license_state!r}")
        _require(
            self.evidence_grade in LEADERBOARD_GRADES,
            f"a leaderboard entry cannot be grade {self.evidence_grade!r}; "
            "grade A is a benchmark this repository ran",
        )
        _require(self.score is None or _finite(self.score), "score must be a finite number or None")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "ModelCandidate":
        return ModelCandidate(**raw)


def estimated_memory_gb(candidate: ModelCandidate) -> float:
    """Weights plus runtime overhead, sized to err high rather than to be exact."""
    return candidate.params_b * BYTES_PER_PARAM[candidate.quantization] + RUNTIME_OVERHEAD_GB


def fits(candidate: ModelCandidate, profile: NodeProfile, resource_class: ResourceClass) -> bool:
    """True when the estimate sits inside both the class budget and the node.

    The class budget is the tighter of the two by design: a job that declares
    `text_small` and then eats the whole machine defeats ADR 0012's admission.
    """
    if not profile.can_ever_run(resource_class):
        return False
    needed = estimated_memory_gb(candidate)
    return needed <= resource_class.memory_gb and needed <= profile.usable_memory_gb


def shortlist(
    candidates: Iterable[ModelCandidate],
    profile: NodeProfile,
    resource_class: ResourceClass,
    *,
    limit: int | None = None,
    require_commercial: bool = True,
) -> tuple[ModelCandidate, ...]:
    """Ranked candidates that fit, best first. An empty result is a real answer."""
    rows: Sequence[ModelCandidate] = tuple(candidates)
    ranks = [c.rank for c in rows]
    _require(len(set(ranks)) == len(ranks), "duplicate rank in the candidate list")
    _require(limit is None or (isinstance(limit, int) and limit >= 0), "limit must be a non-negative int")
    keep = [
        c
        for c in sorted(rows, key=lambda c: c.rank)
        if fits(c, profile, resource_class)
        and (not require_commercial or c.license_state == "commercial_ok")
    ]
    return tuple(keep if limit is None else keep[:limit])


def to_snapshot(
    candidate: ModelCandidate,
    *,
    alias: str,
    runtime: str,
    prompt_bundle: str,
    revision: str = "main",
) -> ModelSnapshot:
    """Hand a candidate to Model Radar as something to benchmark.

    The rank does not travel. Whatever a leaderboard thought, the promotion
    gate only ever sees what this machine measured.
    """
    _require(
        candidate.license_state == "commercial_ok",
        f"{candidate.model_id} is {candidate.license_state}; commercial use is not established",
    )
    return ModelSnapshot(
        alias=alias,
        model_id=candidate.model_id,
        revision=revision,
        runtime=runtime,
        quantization=candidate.quantization,
        prompt_bundle=prompt_bundle,
        license_state=candidate.license_state,
    )
