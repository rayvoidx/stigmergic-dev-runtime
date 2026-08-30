"""Matrix runner: conditions x seeds, aggregates, CLI."""

from __future__ import annotations

import json
from pathlib import Path

from stigdev.cli import main as cli_main
from stigdev.matrix import run_matrix

BASE = {
    "run_id": "overridden",
    "condition": "overridden",
    "seed": 0,
    "k": 10,
    "fixture_version": "v1",
    "n_workers": 2,
    "budget": {"max_episodes": 4, "max_provider_calls": 8},
}


def test_run_matrix_rows_and_aggregates(tmp_path: Path):
    matrix = run_matrix(BASE, ["artifact_only", "best_of_n"], [41, 42, 43], tmp_path, "t")
    assert len(matrix["rows"]) == 6
    assert {r["condition"] for r in matrix["rows"]} == {"artifact_only", "best_of_n"}
    for condition, agg in matrix["aggregates"].items():
        assert agg["holdout"]["n"] == 3
        lo, hi = agg["holdout"]["ci95"]
        assert 0.0 <= lo <= agg["holdout"]["mean"] <= hi <= 1.0
    # seeds actually vary the offline landscape (gene order is seed-derived)
    artifact_scores = {r["train"] for r in matrix["rows"] if r["condition"] == "artifact_only"}
    assert len(artifact_scores) > 1
    saved = json.loads((tmp_path / "t-matrix.json").read_text())
    assert saved["rows"] == matrix["rows"]


def test_matrix_cli(tmp_path: Path, capsys):
    config_path = tmp_path / "base.json"
    config_path.write_text(json.dumps(BASE))
    code = cli_main(
        [
            "matrix",
            "--config", str(config_path),
            "--conditions", "artifact_only",
            "--seeds", "41,42",
            "--label", "clitest",
            "--runs-root", str(tmp_path / "runs"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "artifact_only" in out and "holdout" in out
    assert (tmp_path / "runs" / "clitest-matrix.json").exists()
