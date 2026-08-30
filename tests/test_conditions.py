"""The five experimental conditions are configurable with matched budgets;
unimplemented ones refuse to run instead of silently falling back."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stigdev.model import CONDITIONS, IMPLEMENTED_CONDITIONS, RunConfig
from stigdev.runtime import ConditionNotImplementedError, run

CONFIG_DIR = Path(__file__).parents[1] / "configs" / "conditions"


def _load(condition: str) -> RunConfig:
    raw = json.loads((CONFIG_DIR / f"{condition}.json").read_text(encoding="utf-8"))
    return RunConfig.from_dict(raw)


def test_all_five_conditions_have_configs():
    assert {p.stem for p in CONFIG_DIR.glob("*.json")} == set(CONDITIONS)


@pytest.mark.parametrize("condition", CONDITIONS)
def test_condition_configs_parse_with_matched_budgets(condition: str):
    config = _load(condition)
    assert config.condition == condition
    reference = _load("artifact_only")
    assert config.budget == reference.budget
    assert config.provider == reference.provider
    assert config.seed == reference.seed


@pytest.mark.parametrize("condition", sorted(set(CONDITIONS) - set(IMPLEMENTED_CONDITIONS)))
def test_unimplemented_conditions_fail_loudly(condition: str, tmp_path: Path):
    with pytest.raises(ConditionNotImplementedError):
        run(_load(condition), tmp_path)


def test_artifact_only_condition_runs_from_config(tmp_path: Path):
    summary = run(_load("artifact_only"), tmp_path)
    assert summary["promoted"] >= 1 and summary["rejected"] >= 1
