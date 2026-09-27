"""Offline tests for the Model Radar promotion gate and rollout ladder (ADR 0010)."""

import pytest

from stigdev.modelradar import (
    ROLLOUT_STAGES,
    BenchmarkResult,
    ModelSnapshot,
    PromotionBudget,
    RadarError,
    model_promotion_gate,
    next_rollout_stage,
    rollback_stage,
)
from stigdev.portfolio import GateDecision


def snapshot(**kw) -> ModelSnapshot:
    base = dict(
        alias="writer",
        model_id="local/synthetic-14b",
        revision="rev-2",
        runtime="mlx-lm",
        quantization="q4",
        prompt_bundle="archive-writer@3",
        license_state="commercial_ok",
    )
    base.update(kw)
    return ModelSnapshot(**base)


def result(**kw) -> BenchmarkResult:
    base = dict(
        model_id="local/synthetic-14b",
        revision="rev-2",
        suite_version="media-eval@1",
        quality=0.80,
        peak_memory_gb=28.0,
        p95_latency_s=12.0,
        human_edit_minutes=30.0,
        shadow_artifacts=20,
        critical_regressions=0,
    )
    base.update(kw)
    return BenchmarkResult(**base)


CURRENT = result(revision="rev-1", quality=0.75, human_edit_minutes=32.0)
BUDGET = PromotionBudget(max_peak_memory_gb=30.0, max_p95_latency_s=15.0)


@pytest.mark.parametrize("record", [snapshot(), result(), BUDGET])
def test_records_round_trip_through_dict(record):
    assert type(record).from_dict(record.to_dict()) == record


@pytest.mark.parametrize(
    "build",
    [
        lambda: snapshot(license_state="probably_fine"),
        lambda: snapshot(alias="../writer"),
        lambda: result(quality=float("nan")),
        lambda: result(shadow_artifacts=-1),
        lambda: PromotionBudget(max_peak_memory_gb=0.0, max_p95_latency_s=1.0),
        lambda: PromotionBudget(max_peak_memory_gb=1.0, max_p95_latency_s=1.0, min_shadow_artifacts=-5),
    ],
)
def test_invalid_records_are_rejected(build):
    with pytest.raises(RadarError):
        build()


def test_promotion_gate_passes_strict_improvement_within_budget_with_approval():
    decision = model_promotion_gate(CURRENT, result(), snapshot(), BUDGET, approved_by="operator")
    assert decision == GateDecision("model-promotion/v1", True, ())


def test_first_model_for_alias_still_needs_license_budget_shadow_and_approval():
    assert model_promotion_gate(None, result(), snapshot(), BUDGET, approved_by="operator").passed
    decision = model_promotion_gate(None, result(shadow_artifacts=3), snapshot(license_state="unknown"), BUDGET, approved_by="")
    assert decision.reasons == (
        "license not cleared for commercial use",
        "fewer than 20 shadow artifacts",
        "operator approval missing",
    )


def test_promotion_gate_reports_each_blocker():
    candidate = result(
        suite_version="media-eval@2",
        quality=0.75,
        peak_memory_gb=31.0,
        p95_latency_s=16.0,
        human_edit_minutes=33.0,
        shadow_artifacts=19,
        critical_regressions=1,
    )
    decision = model_promotion_gate(CURRENT, candidate, snapshot(revision="rev-9"), BUDGET, approved_by="")
    assert decision.reasons == (
        "benchmark does not cover snapshot local/synthetic-14b@rev-9",
        "benchmark suite mismatch: media-eval@2 vs media-eval@1",
        "quality 0.750000 did not improve on 0.750000",
        "peak memory 31.0 GB over budget 30.0 GB",
        "p95 latency 16.0 s over budget 15.0 s",
        "human edit time increased 32.0 -> 33.0 minutes",
        "fewer than 20 shadow artifacts",
        "critical regressions present",
        "operator approval missing",
    )


def test_rollout_ladder_is_sequential_and_ends_at_full():
    assert ROLLOUT_STAGES == (
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
    assert next_rollout_stage("discovered") == "quarantined"
    assert next_rollout_stage("canary_50") == "full"
    with pytest.raises(RadarError, match="already full"):
        next_rollout_stage("full")
    with pytest.raises(RadarError, match="unknown"):
        next_rollout_stage("prod")


def test_rollback_returns_any_stage_to_quarantine():
    assert rollback_stage("full") == "quarantined"
    assert rollback_stage("canary_5") == "quarantined"
    with pytest.raises(RadarError, match="unknown"):
        rollback_stage("nowhere")
