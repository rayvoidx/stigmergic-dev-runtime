from __future__ import annotations

from pathlib import Path

import pytest

from stigdev.model import RunConfig
from stigdev.runtime import run

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def demo_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict]:
    """One deterministic seed-42 run shared by e2e, replay, and CLI tests."""
    runs_root = tmp_path_factory.mktemp("runs")
    config = RunConfig(run_id="test-demo", seed=42)
    summary = run(config, runs_root)
    return runs_root / "test-demo", summary
