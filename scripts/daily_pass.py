#!/usr/bin/env python3
"""One bounded, unattended improvement pass over this repository (ADR 0016).

The coding agent runs on the operator's subscription inside a throwaway git
worktree branched from origin/main. Its change reaches `main` only if every
gate holds: a path blocklist that keeps it away from the gates themselves, a
size cap, a secret scan over the added lines, pyflakes, the test suite, and
the offline demo plus replay — the same checks CI runs. Green means one commit
and one push; anything else leaves the worktree behind for a human and pushes
nothing. A day with nothing worth changing is a recorded outcome, never an
invented commit.

    .venv/bin/python scripts/daily_pass.py              # the daily job
    .venv/bin/python scripts/daily_pass.py --no-push    # rehearse: commit on the branch only

Every run writes state/daily/<date>.json so an operator's steward can read the
outcome without parsing logs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from stigdev.claudecode import EXECUTOR_ID, ClaudeCodeExecutor  # noqa: E402
from stigdev.executor import ExecutionRequest, ExecutionResult  # noqa: E402
from stigdev.workspace import WorkspaceRef  # noqa: E402

KST = timezone(timedelta(hours=9))
MAX_FILES = 12
MAX_LINES = 600
TIMEOUT_SECONDS = 1800.0
NO_CHANGE = "NO_CHANGE"
TRAILER = "Co-Authored-By: Claude <noreply@anthropic.com>"
SUBJECT_PREFIXES = ("feat:", "fix:", "docs:", "test:", "refactor:", "perf:", "chore:")
# The agent may not edit what reviews it. A change under any of these fails the pass.
GUARDED_PREFIXES = (
    ".github/",
    "deploy/",
    "scripts/daily_pass.py",
    "tests/test_daily_pass.py",
    "docs/adr/0016-",
)
# Added lines are scanned; a hit fails the pass. Widen, never narrow: a false
# positive costs one skipped day, a false negative publishes a credential.
SECRET_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"sk-ant-[A-Za-z0-9_-]{10,}",
        r"sk-[A-Za-z0-9]{20,}",
        r"AKIA[0-9A-Z]{16}",
        r"gh[pousr]_[A-Za-z0-9]{30,}",
        r"xox[abprs]-[A-Za-z0-9-]{10,}",
        r"AIza[0-9A-Za-z_-]{30,}",
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"(?i)(api[_-]?key|auth[_-]?token|secret)\s*[=:]\s*['\"][^'\"\s]{12,}['\"]",
    )
)

PROMPT = """You are the daily unattended improvement pass for this repository (ADR 0016).
You work alone in a throwaway git worktree branched from origin/main. A script
will review, gate, commit and push your change: do not commit, push, create
branches, or touch git state yourself.

Read AGENTS.md, PROJECT_STATE.md (especially "Known gaps / next actions"),
ROADMAP.md and the newest ADRs first. Then make exactly one small, complete,
test-backed improvement that a careful maintainer would merge without
discussion: a defect found by reading the newest code, a missing test for a
stated invariant, a document corrected against the implementation, or the
smallest next step of a listed gap. Prefer correctness over features. Never add
a dependency. Never call a live model, paid API, or the network from code or
tests. Never touch .github/, deploy/, scripts/daily_pass.py,
tests/test_daily_pass.py or docs/adr/0016-*: those are the gates that review
you. Stay inside the public/private boundary in AGENTS.md: no credentials,
prompts, production data, or private infrastructure details. Keep the diff
under {max_files} files and {max_lines} changed lines.

Verify with:
  {python} -m pytest -q
and, if you touched stigdev/, also:
  {python} -m stigdev.cli demo --runs-root runs --run-id gate && {python} -m stigdev.cli replay runs/gate

Add a short dated entry to PROJECT_STATE.md only when the change deserves one;
never renumber existing decisions.

If nothing is worth changing, change nothing and reply with the single word
NO_CHANGE followed by one sentence saying why.

Otherwise your final message must be only the commit message: one subject line
under 72 characters starting with feat:, fix:, docs:, test:, refactor: or
chore:, a blank line, then a short body saying what was wrong and how you
verified the fix.
"""


class PassError(RuntimeError):
    """The pass itself could not proceed. Never a judgement on the agent's work."""


class AlreadyRan(PassError):
    """Today's worktree exists: a run is in progress or was left for a human."""


@dataclass(frozen=True)
class Change:
    files: tuple[str, ...]
    insertions: int
    deletions: int
    added_text: str


@dataclass
class Outcome:
    date: str
    status: str
    summary: str = ""
    branch: str = ""
    worktree: str = ""
    files: list[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    gate: list[str] = field(default_factory=list)
    verify: list[str] = field(default_factory=list)
    commit: str | None = None
    pushed: bool = False
    agent: dict[str, Any] = field(default_factory=dict)
    finished_at: str = ""


# -- pure parts ---------------------------------------------------------------


def clean_env(env: dict[str, str]) -> dict[str, str]:
    """Drop the variables that mark a running Claude Code session.

    Launched from inside another session the CLI would see itself as nested;
    launched from launchd none of these exist. Billing-route variables are the
    executor's job, not this function's.
    """
    return {k: v for k, v in env.items() if not k.startswith("CLAUDE")}


def parse_numstat(text: str) -> tuple[tuple[str, ...], int, int]:
    files: list[str] = []
    insertions = deletions = 0
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        files.append(path)
        insertions += int(added) if added.isdigit() else 0  # binary files show '-'
        deletions += int(removed) if removed.isdigit() else 0
    return tuple(files), insertions, deletions


def added_lines(diff: str) -> str:
    return "\n".join(
        line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")
    )


def gate(change: Change, *, max_files: int = MAX_FILES, max_lines: int = MAX_LINES) -> list[str]:
    """Why this change may not go to main; empty means it may."""
    problems: list[str] = []
    guarded = [f for f in change.files if f.startswith(GUARDED_PREFIXES)]
    if guarded:
        problems.append("touches guarded paths: " + ", ".join(guarded))
    if len(change.files) > max_files:
        problems.append(f"{len(change.files)} files changed, cap is {max_files}")
    lines = change.insertions + change.deletions
    if lines > max_lines:
        problems.append(f"{lines} lines changed, cap is {max_lines}")
    hits = sorted({p.pattern for p in SECRET_PATTERNS if p.search(change.added_text)})
    if hits:
        problems.append("added text matches secret pattern(s): " + "; ".join(hits))
    return problems


def agent_summary(result: ExecutionResult) -> str:
    """The agent's final message out of the CLI's JSON envelope, or '' if unreadable."""
    try:
        report = json.loads(result.stdout or "")
    except ValueError:
        return ""
    text = report.get("result") if isinstance(report, dict) else None
    return text.strip() if isinstance(text, str) else ""


def commit_message(agent_text: str, date: str) -> str | None:
    """A conventional commit message, or None when the agent declared NO_CHANGE."""
    lines = [line.rstrip() for line in agent_text.strip().splitlines()]
    lines = [line for line in lines if line.strip() != "```"]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines or lines[0].strip().upper().startswith(NO_CHANGE):
        return None
    subject = lines[0].strip().strip("`")
    if not subject.lower().startswith(SUBJECT_PREFIXES):
        subject = "chore: " + subject
    subject = subject[:72].rstrip()
    body = "\n".join(lines[1:]).strip()
    footer = f"Daily pass {date} (ADR 0016): gated by pyflakes, pytest, demo, replay and a secret scan."
    return "\n\n".join(part for part in (subject, body, footer, TRAILER) if part)


# -- git and the agent --------------------------------------------------------


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode:
        detail = (proc.stderr or proc.stdout).strip()
        raise PassError(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout


def prepare_worktree(repo: Path, date: str) -> tuple[Path, str]:
    branch = f"daily/{date}"
    path = repo / "state" / "daily" / date
    if path.exists():
        raise AlreadyRan(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    git("fetch", "-q", "origin", "main", cwd=repo)
    git("worktree", "add", "-q", "-B", branch, str(path), "origin/main", cwd=repo)
    return path, branch


def request_for(
    worktree: Path, date: str, *, python: str, max_files: int, max_lines: int, timeout: float
) -> ExecutionRequest:
    return ExecutionRequest(
        run_id=f"daily-{date}",
        task_id="daily-pass",
        attempt_id=f"daily-{date}-1",
        executor_id=EXECUTOR_ID,
        workspace=WorkspaceRef(backend_id="git-worktree", workspace_id=f"daily-{date}", locator=str(worktree)),
        instruction=PROMPT.format(python=python, max_files=max_files, max_lines=max_lines),
        # The operator's fact-forcing hook would deny the agent's first edit of
        # every file; it is for interactive sessions and is switched off here.
        environment=(("ECC_GATEGUARD", "off"),),
        timeout_seconds=timeout,
    )


def default_executor(model: str | None) -> ClaudeCodeExecutor:
    return ClaudeCodeExecutor(
        model=model,
        base_environment=clean_env(dict(os.environ)),
        # Inside a throwaway worktree with every gate downstream, prompts would
        # only turn into denials. Network tools stay off: the pass is offline.
        extra_args=("--dangerously-skip-permissions", "--disallowedTools", "WebFetch", "WebSearch"),
    )


def staged_change(worktree: Path) -> Change:
    git("add", "-A", cwd=worktree)
    files, insertions, deletions = parse_numstat(
        git("diff", "--cached", "--numstat", "--no-renames", cwd=worktree)
    )
    diff = git("diff", "--cached", "--no-renames", cwd=worktree) if files else ""
    return Change(files, insertions, deletions, added_lines(diff))


def verify(worktree: Path, python: str, files: tuple[str, ...]) -> list[str]:
    """CI's checks, run in the worktree. Stops at the first failure."""
    py_files = [f for f in files if f.endswith(".py") and (worktree / f).exists()]
    checks: list[tuple[str, list[str]]] = []
    if py_files:
        checks.append(("pyflakes", [python, "-m", "pyflakes", *py_files]))
    checks += [
        ("pytest", [python, "-m", "pytest", "-q", "-p", "no:cacheprovider"]),
        ("demo", [python, "-m", "stigdev.cli", "demo", "--runs-root", "runs", "--run-id", "gate"]),
        ("replay", [python, "-m", "stigdev.cli", "replay", "runs/gate"]),
    ]
    for name, argv in checks:
        proc = subprocess.run(argv, cwd=worktree, capture_output=True, text=True, timeout=1800)
        if name == "pyflakes" and proc.returncode and "No module named" in proc.stderr:
            continue  # optional linter; its absence is not the agent's fault
        if proc.returncode:
            tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-8:])
            return [f"{name} failed ({proc.returncode}): {tail}"]
    return []


def discard_worktree(repo: Path, worktree: Path, branch: str) -> None:
    subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=repo, capture_output=True)
    subprocess.run(["git", "branch", "-q", "-D", branch], cwd=repo, capture_output=True)


Verifier = Callable[[Path, str, tuple[str, ...]], list[str]]


def run_pass(
    repo: Path,
    *,
    date: str,
    python: str,
    executor: Any,
    push: bool = True,
    max_files: int = MAX_FILES,
    max_lines: int = MAX_LINES,
    timeout: float = TIMEOUT_SECONDS,
    verifier: Verifier = verify,
) -> Outcome:
    outcome = Outcome(date=date, status="started")
    try:
        worktree, outcome.branch = prepare_worktree(repo, date)
    except AlreadyRan as exc:
        outcome.status, outcome.summary = "already_ran", f"worktree exists: {exc}"
        return outcome
    outcome.worktree = str(worktree)

    started = time.time()
    result = executor.execute(
        request_for(worktree, date, python=python, max_files=max_files, max_lines=max_lines, timeout=timeout)
    )
    usage = result.usage
    outcome.agent = {
        "status": result.status,
        "exit_code": result.exit_code,
        "classification": result.failure_classification,
        "input_tokens": 0 if usage is None else usage.input_tokens,
        "output_tokens": 0 if usage is None else usage.output_tokens,
        "usd": 0.0 if usage is None else usage.usd,
        "wall_seconds": round(time.time() - started, 1),
    }
    text = agent_summary(result)
    if result.status != "success":
        outcome.status = "agent_failed"
        outcome.summary = (result.stderr or text or "")[-500:]
        return outcome

    change = staged_change(worktree)
    outcome.files, outcome.insertions, outcome.deletions = list(change.files), change.insertions, change.deletions
    message = commit_message(text, date)
    if not change.files or message is None:
        outcome.status = "no_change"
        outcome.summary = text[:500] or "agent changed nothing"
        if not change.files:
            discard_worktree(repo, worktree, outcome.branch)
        return outcome

    outcome.gate = gate(change, max_files=max_files, max_lines=max_lines)
    if outcome.gate:
        outcome.status, outcome.summary = "gated", "; ".join(outcome.gate)
        return outcome
    outcome.verify = verifier(worktree, python, change.files)
    if outcome.verify:
        outcome.status, outcome.summary = "verify_failed", outcome.verify[0][:500]
        return outcome

    subprocess.run(["git", "commit", "-q", "-F", "-"], cwd=worktree, input=message, text=True, check=True)
    outcome.commit = git("rev-parse", "HEAD", cwd=worktree).strip()
    outcome.summary = message.splitlines()[0]
    if not push:
        outcome.status = "committed"
        return outcome
    pushed = subprocess.run(["git", "push", "-q", "origin", "HEAD:main"], cwd=worktree, capture_output=True, text=True)
    if pushed.returncode:
        outcome.status, outcome.summary = "push_rejected", pushed.stderr.strip()[-500:]
        return outcome
    outcome.status, outcome.pushed = "pushed", True
    discard_worktree(repo, worktree, outcome.branch)
    return outcome


def write_report(repo: Path, outcome: Outcome) -> Path:
    outcome.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
    path = repo / "state" / "daily" / f"{outcome.date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(outcome), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


EXIT_CODES = {"pushed": 0, "committed": 0, "no_change": 0, "already_ran": 2}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=str(REPO))
    parser.add_argument("--python", default=None, help="interpreter with pytest (default: <repo>/.venv/bin/python)")
    parser.add_argument("--model", default=None, help="model alias for the agent CLI")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: today in KST)")
    parser.add_argument("--timeout", type=float, default=TIMEOUT_SECONDS)
    parser.add_argument("--max-files", type=int, default=MAX_FILES)
    parser.add_argument("--max-lines", type=int, default=MAX_LINES)
    parser.add_argument("--no-push", action="store_true", help="commit on the daily branch, push nothing")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    python = args.python or str(repo / ".venv" / "bin" / "python")
    date = args.date or datetime.now(KST).strftime("%Y-%m-%d")
    outcome = run_pass(
        repo,
        date=date,
        python=python,
        executor=default_executor(args.model),
        push=not args.no_push,
        max_files=args.max_files,
        max_lines=args.max_lines,
        timeout=args.timeout,
    )
    report = write_report(repo, outcome)
    print(json.dumps({"status": outcome.status, "summary": outcome.summary[:200], "report": str(report)}, ensure_ascii=False))
    return EXIT_CODES.get(outcome.status, 1)


if __name__ == "__main__":
    raise SystemExit(main())
