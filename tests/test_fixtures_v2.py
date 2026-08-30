"""Fixtures v2: locked-in dynamic range and adversarial properties.

v2 exists to give pilot experiments discrimination the v1 toy lacks:
a low floor, intermediate rungs for simple heuristics, and a high ceiling
reachable only by combining source/duplicate/keyword/recency reasoning.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stigdev.evaluator import TrendSelectEvaluator, load_items
from stigdev.model import Evidence
from stigdev.provider import render_artifact
from stigdev.runtime import default_fixtures_dir
from stigdev.sandbox import SubprocessSandbox
from stigdev.store import RunStore

BENCH = Path(__file__).parents[1] / "benchmarks" / "trendevobench"
FIXTURES_V2 = default_fixtures_dir("v2")


@pytest.fixture(scope="module")
def score(tmp_path_factory: pytest.TempPathFactory):
    store = RunStore.create(tmp_path_factory.mktemp("v2") / "s")
    evaluator = TrendSelectEvaluator(FIXTURES_V2, SubprocessSandbox())

    def _score(source: str, split: str) -> Evidence:
        return evaluator.evaluate(store, store.put_artifact(source), split, 10)

    return _score


def test_v2_fixture_schema_and_split_sizes():
    train = load_items(FIXTURES_V2, "train")
    holdout = load_items(FIXTURES_V2, "holdout")
    assert len(train) >= 40 and len(holdout) >= 20
    assert {i["source"] for i in train} <= {"synth-feed-a", "synth-feed-b", "synth-feed-c"}


def test_v2_floor_is_low(score):
    seed = (BENCH / "seed_artifact.py").read_text()
    evidence = score(seed, "train")
    assert evidence.passed
    assert evidence.score <= 0.45  # engagement-only ranks the traps first


def test_v2_prefix_dedup_gene_gains_nothing(score):
    """Paraphrased duplicates share no 40-char prefix: the v1 dedup gene is
    useless on v2 — the adversarial property that forces smarter artifacts."""
    seed = (BENCH / "seed_artifact.py").read_text()
    dedup = render_artifact({"dedup"}, "probe")
    assert score(dedup, "train").score == pytest.approx(score(seed, "train").score)


def test_v2_v1_strategies_plateau_mid_range(score):
    combo = render_artifact({"dedup", "recency", "keyword"}, "probe")
    evidence = score(combo, "train")
    assert 0.5 <= evidence.score <= 0.8  # a real rung, far from the ceiling


def test_v2_ceiling_needs_combined_reasoning(score):
    reference = (BENCH / "reference_artifact_v2.py").read_text()
    combo = render_artifact({"dedup", "recency", "keyword"}, "probe")
    for split in ("train", "holdout"):
        ref_evidence = score(reference, split)
        assert ref_evidence.passed
        assert ref_evidence.score >= 0.9
        assert ref_evidence.score >= score(combo, split).score + 0.1
