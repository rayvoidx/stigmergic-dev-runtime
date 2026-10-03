"""Offline tests for memory-fitted model shortlisting (ADR 0015).

A public leaderboard ranks models; this module decides which of them a given
machine could physically hold. It never promotes anything — Model Radar
(ADR 0010) still does that, on measurements.
"""

import pytest

from stigdev.modelfit import (
    BYTES_PER_PARAM,
    RUNTIME_OVERHEAD_GB,
    ModelCandidate,
    ModelFitError,
    estimated_memory_gb,
    fits,
    shortlist,
    to_snapshot,
)
from stigdev.node import MOBILE_M4, RESOURCE_CLASSES, STUDIO_M5_ULTRA

NOW = "2026-09-29T00:00:00+00:00"
SMALL = RESOURCE_CLASSES["text_small"]
CODER = RESOURCE_CLASSES["text_coder"]


def candidate(**kw) -> ModelCandidate:
    base = dict(
        model_id="synthetic-org/synthetic-8b",
        params_b=8.0,
        quantization="q4",
        rank=1,
        source="huggingface/synthetic-leaderboard",
        captured_at=NOW,
        license_state="commercial_ok",
        evidence_grade="B",
    )
    base.update(kw)
    return ModelCandidate(**base)


# --- records -------------------------------------------------------------------


def test_a_candidate_round_trips_through_dict():
    c = candidate()
    assert ModelCandidate.from_dict(c.to_dict()) == c


@pytest.mark.parametrize(
    "kw",
    [
        dict(params_b=0),
        dict(params_b=-1.0),
        dict(params_b=float("inf")),
        dict(quantization="q99"),
        dict(rank=0),
        dict(license_state="whatever"),
        dict(captured_at="2026-09-29T00:00:00"),
        dict(model_id="../etc/passwd"),
        dict(evidence_grade="A+"),
        dict(source=" "),
    ],
)
def test_invalid_candidates_are_rejected_at_construction(kw):
    with pytest.raises(ModelFitError):
        candidate(**kw)


def test_a_leaderboard_entry_is_never_grade_a():
    """A third-party ranking is someone else's measurement. Grade A is reserved
    for a benchmark this repository ran itself."""
    with pytest.raises(ModelFitError, match="grade"):
        candidate(evidence_grade="A")


# --- memory estimate -----------------------------------------------------------


def test_the_estimate_is_weights_plus_overhead():
    c = candidate(params_b=8.0, quantization="q4")
    assert estimated_memory_gb(c) == pytest.approx(8.0 * BYTES_PER_PARAM["q4"] + RUNTIME_OVERHEAD_GB)


def test_heavier_quantisation_needs_more_memory():
    order = ["q3", "q4", "q5", "q6", "q8", "f16"]
    sizes = [estimated_memory_gb(candidate(quantization=q)) for q in order]
    assert sizes == sorted(sizes)


def test_the_estimate_errs_high_so_a_small_machine_does_not_oom():
    # 8B at q4 is roughly 4.4 GB of weights; the estimate must sit above that.
    assert estimated_memory_gb(candidate()) > 8.0 * 0.55


# --- fitting -------------------------------------------------------------------


def test_a_model_must_fit_the_class_budget_not_just_the_machine():
    small = candidate(params_b=8.0, quantization="q4")
    assert fits(small, MOBILE_M4, SMALL)
    # 70B at q4 is far past a 10 GB class and past the laptop entirely
    assert not fits(candidate(params_b=70.0, quantization="q4"), MOBILE_M4, SMALL)
    assert not fits(candidate(params_b=70.0, quantization="q4"), STUDIO_M5_ULTRA, SMALL)


def test_a_class_the_node_can_never_host_fits_nothing():
    # MOBILE_M4 has 16 GB usable; text_coder wants 28 GB.
    assert not fits(candidate(params_b=1.0), MOBILE_M4, CODER)
    assert fits(candidate(params_b=1.0), STUDIO_M5_ULTRA, CODER)


# --- shortlisting --------------------------------------------------------------


def ranked() -> tuple[ModelCandidate, ...]:
    return (
        candidate(model_id="org/huge-70b", params_b=70.0, rank=1),
        candidate(model_id="org/restricted-8b", params_b=8.0, rank=2, license_state="restricted"),
        candidate(model_id="org/good-8b", params_b=8.0, rank=3),
        candidate(model_id="org/unknown-7b", params_b=7.0, rank=4, license_state="unknown"),
        candidate(model_id="org/good-3b", params_b=3.0, rank=5),
    )


def test_the_shortlist_keeps_leaderboard_order_among_what_fits():
    picked = shortlist(ranked(), MOBILE_M4, SMALL)
    assert [c.model_id for c in picked] == ["org/good-8b", "org/good-3b"]


def test_a_model_the_operator_may_not_sell_with_is_never_shortlisted():
    picked = shortlist(ranked(), MOBILE_M4, SMALL)
    assert all(c.license_state == "commercial_ok" for c in picked)
    permissive = shortlist(ranked(), MOBILE_M4, SMALL, require_commercial=False)
    assert "org/restricted-8b" in [c.model_id for c in permissive]


def test_the_shortlist_can_be_capped():
    assert len(shortlist(ranked(), MOBILE_M4, SMALL, limit=1)) == 1


def test_an_empty_shortlist_is_a_real_answer_not_an_error():
    assert shortlist(ranked(), MOBILE_M4, CODER) == ()
    assert shortlist((), MOBILE_M4, SMALL) == ()


def test_duplicate_ranks_are_refused_rather_than_ordered_arbitrarily():
    with pytest.raises(ModelFitError, match="rank"):
        shortlist((candidate(rank=1), candidate(model_id="org/other", rank=1)), MOBILE_M4, SMALL)


# --- the handover into Model Radar ---------------------------------------------


def test_a_shortlisted_candidate_becomes_a_snapshot_to_benchmark_not_a_promotion():
    """The whole point: a leaderboard picks what to *try*. ADR 0010's gate still
    decides what runs, and it only reads measurements."""
    snapshot = to_snapshot(candidate(), alias="writer", runtime="mlx-lm", prompt_bundle="archive-writer@1")
    assert snapshot.alias == "writer"
    assert snapshot.model_id == "synthetic-org/synthetic-8b"
    assert snapshot.quantization == "q4"
    assert snapshot.license_state == "commercial_ok"
    # a snapshot carries no score, no verdict, and no rollout stage
    assert not hasattr(snapshot, "rank") and not hasattr(snapshot, "stage")


def test_a_non_commercial_candidate_cannot_be_turned_into_a_snapshot_silently():
    with pytest.raises(ModelFitError, match="commercial"):
        to_snapshot(candidate(license_state="restricted"), alias="writer", runtime="mlx-lm",
                    prompt_bundle="archive-writer@1")
