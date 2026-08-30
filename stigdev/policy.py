"""Promotion policy: the gate between candidate evidence and canonical state."""

from __future__ import annotations

from .model import Evidence, PromotionDecision

POLICY_ID = "strict-improve/v1"


class StrictImprovementPolicy:
    """Promote iff hard checks pass and the composite score strictly improves."""

    def __init__(self, epsilon: float = 1e-9):
        self.epsilon = epsilon
        self.policy_id = POLICY_ID

    def decide(self, candidate: Evidence, canonical_score: float | None) -> PromotionDecision:
        if not candidate.passed:
            return PromotionDecision(False, f"hard checks failed: {candidate.reason}", POLICY_ID)
        if canonical_score is None:
            return PromotionDecision(True, "seeding empty canonical state", POLICY_ID)
        if candidate.score > canonical_score + self.epsilon:
            return PromotionDecision(
                True, f"score improved {canonical_score:.6f} -> {candidate.score:.6f}", POLICY_ID
            )
        return PromotionDecision(
            False,
            f"score {candidate.score:.6f} did not improve on canonical {canonical_score:.6f}",
            POLICY_ID,
        )
