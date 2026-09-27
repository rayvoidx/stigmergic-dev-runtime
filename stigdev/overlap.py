"""Cross-channel overlap heuristic (ADR 0011, v3.3 §5.16.5).

A weighted score over six similarity components. It is an internal review
priority heuristic, not a platform threshold and not an automatic verdict:
blocking is decided by the rights gate, exact asset fingerprints, and human
review. :func:`review_queue` therefore returns an ordering, never a decision.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .workspace import valid_identifier

# v3.3 §5.16.5. Weights sum to 1.0; asserted here so a future edit cannot
# silently rescale the score.
OVERLAP_WEIGHTS: dict[str, float] = {
    "audience": 0.25,
    "viewer_job": 0.20,
    "script": 0.20,
    "asset_fingerprint": 0.15,
    "visual_voice": 0.10,
    "monetization": 0.10,
}
COMPONENTS = tuple(OVERLAP_WEIGHTS)
REVIEW_THRESHOLD = 0.60


class OverlapError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise OverlapError(message)


def _unit(value: object, name: str) -> float:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    _require(ok and 0.0 <= float(value) <= 1.0, f"{name} must be within [0, 1]")
    return float(value)


@dataclass(frozen=True)
class ChannelOverlap:
    left_channel_id: str
    right_channel_id: str
    components: Mapping[str, float]
    reviewed_at: str | None = None

    def __post_init__(self) -> None:
        for name in ("left_channel_id", "right_channel_id"):
            _require(valid_identifier(getattr(self, name)), f"invalid {name}")
        _require(self.left_channel_id != self.right_channel_id, "a channel does not overlap itself")
        _require(set(self.components) == set(COMPONENTS), f"components must be exactly {COMPONENTS}")
        for name, value in self.components.items():
            _unit(value, name)
        # frozen=True does not stop the caller mutating the dict it handed us,
        # which would change this object's score after construction.
        object.__setattr__(self, "components", MappingProxyType(dict(self.components)))

    def to_dict(self) -> dict[str, Any]:
        return {"left_channel_id": self.left_channel_id, "right_channel_id": self.right_channel_id,
                "components": dict(self.components), "reviewed_at": self.reviewed_at}

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "ChannelOverlap":
        return ChannelOverlap(**raw)

    @property
    def score(self) -> float:
        return overlap_score(self.components)

    @property
    def needs_review(self) -> bool:
        return self.score >= REVIEW_THRESHOLD


def overlap_score(components: dict[str, float]) -> float:
    """Weighted similarity in [0, 1]. Higher means review sooner, never 'block'."""
    _require(set(components) == set(COMPONENTS), f"components must be exactly {COMPONENTS}")
    return round(sum(OVERLAP_WEIGHTS[k] * _unit(v, k) for k, v in components.items()), 6)


def review_queue(overlaps: Iterable[ChannelOverlap]) -> list[ChannelOverlap]:
    """Pairs that reached the review threshold, worst first, then by channel id."""
    flagged = [o for o in overlaps if o.needs_review]
    return sorted(flagged, key=lambda o: (-o.score, o.left_channel_id, o.right_channel_id))
