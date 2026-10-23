"""stigdev CLI: deterministic demo, config-driven runs, evaluation, replay,
lineage inspection, and canonical-state recovery."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

from .evaluator import TrendSelectEvaluator
from .model import RunConfig
from .replay import recover, replay
from .runtime import default_fixtures_dir, run
from .sandbox import SubprocessSandbox
from .store import RunStore


def _print(obj: object) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True))


def _claude_code(*, model: str | None):
    from .claudecode import ClaudeCodeExecutor

    return ClaudeCodeExecutor(model=model)


# Agent CLIs, not model endpoints. Each runs under the operator's own login;
# none of them takes an API key from this process.
EXECUTORS = {"claude-code": _claude_code}


def read_host_facts():
    """Measure the machine, or refuse to guess.

    `scripts/commission_node.py` is the macOS measurement half. If it cannot be
    imported the worker must not invent a calm machine, so this reports red
    pressure and no disk, which admission treats as "take no new work".
    """
    from .node import HostFacts

    scripts = str(Path(__file__).resolve().parents[1] / "scripts")
    if scripts not in sys.path:  # called every tick; never let sys.path grow
        sys.path.insert(0, scripts)
    try:
        import commission_node  # type: ignore[import-not-found]

        return HostFacts(
            memory_pressure=commission_node.memory_pressure(),
            swap_growth_mb_per_min=commission_node.swap_growth_mb_per_min(),
            free_disk_gb=commission_node.free_disk_gb(),
            thermal_throttled=commission_node.thermal_throttled(),
        )
    except Exception:  # noqa: BLE001 - an unmeasurable host is a stopped worker, not a crash
        return HostFacts(memory_pressure="red", free_disk_gb=0.0)


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


def cmd_executions(args: argparse.Namespace) -> int:
    from .execution import inspect_executions, recover_executions

    store = RunStore.open(Path(args.run_dir))
    operation = recover_executions if args.command == "recover-executions" else inspect_executions
    _print(operation(store))
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


def cmd_worker(args: argparse.Namespace) -> int:
    """Start the unattended loop. `claude-code` runs on the operator's
    subscription: `stigdev.claudecode` strips every known billing-route
    variable and refuses any request that sets one."""
    import os

    from .eventstore import SqliteEventStore
    from .node import PROFILES, RESOURCE_CLASSES
    from .scheduler import Budget, Scheduler
    from .workerd import WorkerLoop

    store = SqliteEventStore.open(Path(args.store_root))
    profile = PROFILES[args.node]
    resource_class = RESOURCE_CLASSES[args.resource_class]
    executor = EXECUTORS[args.executor](model=args.model)
    scheduler = Scheduler(
        store,
        run_id=args.run_id,
        budget=Budget(max_concurrency=1, max_usd=0.0),  # no paid work on this path
        started_at=time.time(),
    )
    loop = WorkerLoop(
        scheduler=scheduler,
        executor=executor,
        holder=args.holder or f"{profile.node_id}/{os.getpid()}",
        profile=profile,
        resource_class=resource_class,
        host_facts=read_host_facts,
        poll_seconds=args.poll_seconds,
    )
    if args.once:
        _print({"ticks": loop.run_until_idle(max_ticks=args.max_ticks)})
        return 0
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        return 0
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

    p = sub.add_parser("executions", help="inspect recorded execution attempts without rerunning agents")
    p.add_argument("run_dir")
    p.set_defaults(func=cmd_executions)

    p = sub.add_parser("recover-executions", help="mark interrupted attempts after their writer has stopped")
    p.add_argument("run_dir")
    p.set_defaults(func=cmd_executions)

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

    p = sub.add_parser("worker", help="run the unattended worker loop against an event store")
    p.add_argument("store_root", help="event store root directory")
    p.add_argument("--run-id", required=True)
    p.add_argument(
        "--executor",
        default="claude-code",
        choices=sorted(EXECUTORS),
        help="claude-code runs the CLI on the operator's subscription; never an API key",
    )
    p.add_argument("--model", default=None, help="model alias passed to the agent CLI")
    p.add_argument("--node", default="mobile-m4", help="node profile id for admission")
    p.add_argument("--resource-class", default="text_small")
    p.add_argument("--holder", default=None, help="lease holder id (default: <node>/<pid>)")
    p.add_argument("--poll-seconds", type=float, default=5.0)
    p.add_argument("--once", action="store_true", help="drain what is ready, then exit")
    p.add_argument("--max-ticks", type=int, default=1000)
    p.set_defaults(func=cmd_worker)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
