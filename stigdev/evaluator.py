"""TrendEvoBench evaluator: scores a trend-selection artifact against
versioned synthetic fixtures, entirely through the sandbox boundary.

Fixture item schema (JSONL, one item per line):
    public fields (visible to artifacts):  id, text, source, ts, engagement
    truth fields (evaluator-only):         relevant (bool), dup_group (str)

Composite score = 0.7 * precision_at_k + 0.3 * unique_group_rate.
Comparable only within one evaluator version.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import Evidence
from .sandbox import Sandbox
from .store import RunStore

EVALUATOR_ID = "trendevobench.select"
EVALUATOR_VERSION = "1"

PUBLIC_FIELDS = ("id", "text", "source", "ts", "engagement")
TRUTH_FIELDS = ("relevant", "dup_group")
SPLITS = ("train", "holdout")


def load_items(fixtures_dir: Path, split: str) -> list[dict[str, Any]]:
    path = Path(fixtures_dir) / f"{split}.jsonl"
    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    for item in items:
        missing = [f for f in PUBLIC_FIELDS + TRUTH_FIELDS if f not in item]
        if missing:
            raise ValueError(f"fixture item {item.get('id')} missing fields {missing}")
    return items


def public_view(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{f: item[f] for f in PUBLIC_FIELDS} for item in items]


class TrendSelectEvaluator:
    def __init__(self, fixtures_dir: Path, sandbox: Sandbox, timeout: float = 10.0):
        self.fixtures_dir = Path(fixtures_dir)
        self.sandbox = sandbox
        self.timeout = timeout
        self.evaluator_id = EVALUATOR_ID
        self.evaluator_version = EVALUATOR_VERSION

    def evaluate(self, store: RunStore, artifact_hash: str, split: str, k: int) -> Evidence:
        items = load_items(self.fixtures_dir, split)
        result = self.sandbox.call(
            store.artifact_path(artifact_hash),
            "select_trends",
            [public_view(items), k],
            self.timeout,
        )

        def failure(reason: str) -> Evidence:
            return Evidence(
                EVALUATOR_ID, EVALUATOR_VERSION, artifact_hash, split, False, 0.0, {}, reason
            )

        if not result.ok:
            return failure(f"execution failed: {result.error}")
        selected = result.value
        known_ids = {item["id"] for item in items}
        if not isinstance(selected, list) or not all(isinstance(s, str) for s in selected):
            return failure(f"output is not a list of ids: {type(selected).__name__}")
        if len(selected) > k:
            return failure(f"returned {len(selected)} ids, k={k}")
        if len(set(selected)) != len(selected):
            return failure("duplicate ids in output")
        if not set(selected) <= known_ids:
            return failure(f"unknown ids in output: {sorted(set(selected) - known_ids)[:3]}")
        if not selected:
            return failure("empty selection")

        truth = {item["id"]: item for item in items}
        relevant_hits = sum(1 for sid in selected if truth[sid]["relevant"])
        precision_at_k = relevant_hits / k
        unique_groups = len({truth[sid]["dup_group"] for sid in selected})
        unique_group_rate = unique_groups / len(selected)
        score = round(0.7 * precision_at_k + 0.3 * unique_group_rate, 6)
        return Evidence(
            EVALUATOR_ID,
            EVALUATOR_VERSION,
            artifact_hash,
            split,
            True,
            score,
            # metrics must stay deterministic: no timings here (replay compares them)
            {
                "precision_at_k": round(precision_at_k, 6),
                "unique_group_rate": round(unique_group_rate, 6),
                "selected": float(len(selected)),
            },
        )
