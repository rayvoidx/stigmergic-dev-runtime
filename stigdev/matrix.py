"""Experiment matrix runner: conditions x seeds under one base config.

Implements the protocol's pilot mechanics: every cell is a full run() with
identical budgets, only condition and seed varying. Aggregates report mean,
sd, and a percentile bootstrap 95% CI per condition. Statistics here are
descriptive plumbing — inference rules (power, corrections, n floors) live in
docs/research_protocol.md and are not enforced by this module.
"""

from __future__ import annotations

import json
import random
import statistics
import time
from pathlib import Path
from typing import Any

from .model import RunConfig
from .runtime import run

METRICS = ("train", "holdout", "promoted", "rejected", "repeated", "tokens")


def _bootstrap_ci(values: list[float], resamples: int = 2000) -> list[float]:
    rng = random.Random(0)
    means = sorted(
        statistics.fmean(rng.choices(values, k=len(values))) for _ in range(resamples)
    )
    return [round(means[int(0.025 * resamples)], 4), round(means[int(0.975 * resamples)], 4)]


def run_matrix(
    base: dict[str, Any],
    conditions: list[str],
    seeds: list[int],
    runs_root: Path,
    label: str,
) -> dict[str, Any]:
    runs_root = Path(runs_root)
    rows: list[dict[str, Any]] = []
    started = time.time()
    for condition in conditions:
        for seed in seeds:
            run_id = f"{label}-{condition}-s{seed}"
            config = RunConfig.from_dict(
                {**base, "condition": condition, "seed": seed, "run_id": run_id}
            )
            summary = run(config, runs_root)
            rows.append(
                {
                    "condition": condition,
                    "seed": seed,
                    "run_id": run_id,
                    "promoted": summary["promoted"],
                    "rejected": summary["rejected"],
                    "repeated": summary["repeated_failure_attempts"],
                    "train": summary["canonical"]["score"],
                    "holdout": summary["holdout_score"],
                    "tokens": summary["cost"]["input_tokens"] + summary["cost"]["output_tokens"],
                }
            )

    aggregates: dict[str, dict[str, Any]] = {}
    for condition in conditions:
        cell = [r for r in rows if r["condition"] == condition]
        aggregates[condition] = {}
        for metric in METRICS:
            values = [float(r[metric]) for r in cell]
            aggregates[condition][metric] = {
                "mean": round(statistics.fmean(values), 4),
                "sd": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
                "ci95": _bootstrap_ci(values),
                "n": len(values),
            }

    matrix = {
        "label": label,
        "base_config": base,
        "conditions": conditions,
        "seeds": seeds,
        "rows": rows,
        "aggregates": aggregates,
        "wall_seconds": round(time.time() - started, 1),
    }
    out_path = runs_root / f"{label}-matrix.json"
    out_path.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return matrix


def format_table(matrix: dict[str, Any]) -> str:
    lines = [
        f"matrix {matrix['label']}: seeds {matrix['seeds']}",
        f"{'condition':20} {'holdout':>22} {'train':>22} {'promoted':>10} {'repeated':>10}",
    ]
    for condition, agg in matrix["aggregates"].items():
        ho, tr = agg["holdout"], agg["train"]
        lines.append(
            f"{condition:20} "
            f"{ho['mean']:>7} [{ho['ci95'][0]},{ho['ci95'][1]}] "
            f"{tr['mean']:>7} [{tr['ci95'][0]},{tr['ci95'][1]}] "
            f"{agg['promoted']['mean']:>10} {agg['repeated']['mean']:>10}"
        )
    return "\n".join(lines)
