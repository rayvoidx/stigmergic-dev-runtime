"""stigdev CLI: deterministic demo, config-driven runs, evaluation, replay,
lineage inspection, and canonical-state recovery."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from .evaluator import TrendSelectEvaluator
from .model import RunConfig
from .replay import recover, replay
from .runtime import default_fixtures_dir, run
from .sandbox import SubprocessSandbox
from .store import RunStore


def _print(obj: object) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True))


def cmd_demo(args: argparse.Namespace) -> int:
    config = RunConfig(run_id=args.run_id, seed=args.seed)
    summary = run(config, Path(args.runs_root))
    _print(summary)
    print(f"\nrun directory: {Path(args.runs_root) / config.run_id}", file=sys.stderr)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    raw = json.loads(Path(args.config).read_text(encoding="utf-8"))
    config = RunConfig.from_dict(raw)
    summary = run(config, Path(args.runs_root))
    _print(summary)
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    fixtures = Path(args.fixtures) if args.fixtures else default_fixtures_dir("v1")
    evaluator = TrendSelectEvaluator(fixtures, SubprocessSandbox())
    with tempfile.TemporaryDirectory() as tmp:
        store = RunStore.create(Path(tmp) / "eval")
        digest = store.put_artifact(Path(args.artifact).read_text(encoding="utf-8"))
        evidence = evaluator.evaluate(store, digest, args.split, args.k)
    _print(evidence.to_dict())
    return 0 if evidence.passed else 1


def cmd_replay(args: argparse.Namespace) -> int:
    report = replay(Path(args.run_dir))
    _print(report)
    return 0 if report["ok"] else 1


def cmd_recover(args: argparse.Namespace) -> int:
    report = recover(Path(args.run_dir))
    _print(report)
    return 0


def cmd_matrix(args: argparse.Namespace) -> int:
    from .matrix import format_table, run_matrix

    base = json.loads(Path(args.config).read_text(encoding="utf-8"))
    matrix = run_matrix(
        base,
        args.conditions.split(","),
        [int(s) for s in args.seeds.split(",")],
        Path(args.runs_root),
        args.label,
    )
    print(format_table(matrix))
    print(
        f"\nmatrix file: {Path(args.runs_root) / (args.label + '-matrix.json')}", file=sys.stderr
    )
    return 0


def cmd_lineage(args: argparse.Namespace) -> int:
    store = RunStore.open(Path(args.run_dir))
    started = store.events("run_started")[0]
    print(f"gen 0  {started['seed_artifact_hash'][:12]}  seed  score={started['seed_score']}")
    for edge in store.lineage_edges():
        print(
            f"gen {edge['generation']}  {edge['child_hash'][:12]}  "
            f"mutation={edge['mutation']}  score={edge['score']}  "
            f"parent={edge['parent_hash'][:12]}"
        )
    for event in store.failures():
        marker = " (repeated)" if event.get("repeated_failure") else ""
        print(
            f"rejected  ep{event['episode']}  {event['artifact_hash'][:12]}  "
            f"mutation={event['mutation']}  score={event['score']}{marker}  {event['reason']}"
        )
    canonical = store.canonical()
    if canonical:
        print(f"canonical: {canonical['artifact_hash'][:12]} gen={canonical['generation']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stigdev", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("demo", help="run the deterministic offline demo")
    p.add_argument("--runs-root", default="runs")
    p.add_argument("--run-id", default="demo-seed42")
    p.add_argument("--seed", type=int, default=42)
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("run", help="run from a JSON RunConfig file")
    p.add_argument("--config", required=True)
    p.add_argument("--runs-root", default="runs")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("evaluate", help="evaluate one artifact file against fixtures")
    p.add_argument("--artifact", required=True)
    p.add_argument("--split", choices=("train", "holdout"), default="train")
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--fixtures")
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("replay", help="re-derive all evidence and verify the run")
    p.add_argument("run_dir")
    p.set_defaults(func=cmd_replay)

    p = sub.add_parser("recover", help="restore canonical pointer from the event log")
    p.add_argument("run_dir")
    p.set_defaults(func=cmd_recover)

    p = sub.add_parser("matrix", help="run a conditions x seeds experiment matrix")
    p.add_argument("--config", required=True, help="base RunConfig JSON (run_id/condition/seed overridden)")
    p.add_argument("--conditions", required=True, help="comma-separated condition names")
    p.add_argument("--seeds", required=True, help="comma-separated integer seeds")
    p.add_argument("--label", required=True)
    p.add_argument("--runs-root", default="runs")
    p.set_defaults(func=cmd_matrix)

    p = sub.add_parser("lineage", help="print lineage, failures, and canonical state")
    p.add_argument("run_dir")
    p.set_defaults(func=cmd_lineage)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
