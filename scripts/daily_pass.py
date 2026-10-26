#!/usr/bin/env python3
"""One bounded, unattended improvement pass over a repository (ADR 0016, ADR 0017).

The coding agent runs on the operator's subscription inside a throwaway git
worktree branched from origin/main. Its change reaches `main` only if every
gate holds: a path blocklist that keeps it away from the gates themselves, a
size cap, a secret scan over the added lines, and the repository's own checks
(here: pyflakes, the test suite, the offline demo plus replay — what CI runs).
Green means one commit and one push; anything else leaves the worktree behind
for a human and pushes nothing. A day with nothing worth changing is a recorded
outcome, never an invented commit.

    .venv/bin/python scripts/daily_pass.py              # this repository, the daily job
    .venv/bin/python scripts/daily_pass.py --no-push    # rehearse: commit on the branch only

Another repository takes the same pass through flags (ADR 0017): --repo and
--python name it, --prompt FILE replaces the instruction, --verify CMD (repeatable)
replaces the default checks with its own, --guard PREFIX widens the blocklist,
--state DIR keeps the worktree and report out of it, --merge fast-forwards the
checked-out branch so the machine runs the change, --after CMD restarts whatever
serves it, and --no-push --merge suits a repository without a remote.

Every run writes <state>/<date>.json so an operator's steward can read the
outcome without parsing logs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
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
DEFAULT_GATES = "pyflakes, pytest, demo, replay and a secret scan"
SUBJECT_PREFIXES = ("feat:", "fix:", "docs:", "test:", "refactor:", "perf:", "chore:")
# The agent may not edit what reviews it. A change under any of these fails the pass.
GUARDED_PREFIXES = (
    ".github/",
    "deploy/",
    "scripts/daily_pass.py",
    "tests/test_daily_pass.py",
    "docs/adr/0016-",
    "docs/adr/0017-",
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
tests/test_daily_pass.py, docs/adr/0016-* or docs/adr/0017-*: those are the
gates that review you. Stay inside the public/private boundary in AGENTS.md: no credentials,
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
    agent_text: str = ""  # the agent's final message, kept so a failed day can still be read
    merged: bool = False  # the repository's checked-out branch was fast-forwarded to the commit
    merge_note: str = ""  # why it was not
    after: dict[str, Any] = field(default_factory=dict)  # the --after command's exit code and tail
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


def render_prompt(template: str, *, python: str, max_files: int, max_lines: int) -> str:
    """Fill the three placeholders by replacement: a custom prompt may hold braces of its own."""
    return (template.replace("{python}", python)
            .replace("{max_files}", str(max_files)).replace("{max_lines}", str(max_lines)))


def gate(change: Change, *, max_files: int = MAX_FILES, max_lines: int = MAX_LINES,
         guarded_prefixes: tuple[str, ...] = GUARDED_PREFIXES) -> list[str]:
    """Why this change may not go to main; empty means it may."""
    problems: list[str] = []
    guarded = [f for f in change.files if f.startswith(guarded_prefixes)]
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


def commit_message(agent_text: str, date: str, gates: str = DEFAULT_GATES) -> str | None:
    """A conventional commit message, or None when the agent declared NO_CHANGE."""
    lines = [line.rstrip() for line in agent_text.strip().splitlines()]
    lines = [line for line in lines if line.strip() != "```"]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines or lines[0].strip().upper().startswith(NO_CHANGE):
        return None
    # An agent sometimes talks before the message ("Within limits. Final commit
    # message:"); the message starts at the first conventional subject line.
    starts = [i for i, line in enumerate(lines) if line.strip().strip("`").lower().startswith(SUBJECT_PREFIXES)]
    if starts:
        lines = lines[starts[0]:]
    subject = lines[0].strip().strip("`")
    if not subject.lower().startswith(SUBJECT_PREFIXES):
        subject = "chore: " + subject
    subject = subject[:72].rstrip()
    body = "\n".join(lines[1:]).strip()
    footer = f"Daily pass {date} (ADR 0016): gated by {gates}."
    return "\n\n".join(part for part in (subject, body, footer, TRAILER) if part)


# -- git and the agent --------------------------------------------------------


def git(*args: str, cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if proc.returncode:
        detail = (proc.stderr or proc.stdout).strip()
        raise PassError(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout


def prepare_worktree(repo: Path, date: str, *, state_dir: Path, base: str) -> tuple[Path, str]:
    branch = f"daily/{date}"
    path = state_dir / date
    if path.exists():
        raise AlreadyRan(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    if base.startswith("origin/"):
        git("fetch", "-q", "origin", base[len("origin/"):], cwd=repo)
    git("worktree", "add", "-q", "-B", branch, str(path), base, cwd=repo)
    return path, branch


def request_for(
    worktree: Path, date: str, *, python: str, max_files: int, max_lines: int, timeout: float,
    prompt: str = PROMPT,
) -> ExecutionRequest:
    return ExecutionRequest(
        run_id=f"daily-{date}",
        task_id="daily-pass",
        attempt_id=f"daily-{date}-1",
        executor_id=EXECUTOR_ID,
        workspace=WorkspaceRef(backend_id="git-worktree", workspace_id=f"daily-{date}", locator=str(worktree)),
        instruction=render_prompt(prompt, python=python, max_files=max_files, max_lines=max_lines),
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


def gate_commands(python: str, py_files: list[str], runs_root: str) -> list[tuple[str, list[str]]]:
    checks: list[tuple[str, list[str]]] = []
    if py_files:
        checks.append(("pyflakes", [python, "-m", "pyflakes", *py_files]))
    checks += [
        ("pytest", [python, "-m", "pytest", "-q", "-p", "no:cacheprovider"]),
        ("demo", [python, "-m", "stigdev.cli", "demo", "--runs-root", runs_root, "--run-id", "gate"]),
        ("replay", [python, "-m", "stigdev.cli", "replay", str(Path(runs_root) / "gate")]),
    ]
    return checks


def verify(worktree: Path, python: str, files: tuple[str, ...]) -> list[str]:
    """CI's checks, run in the worktree. Stops at the first failure.

    The demo writes into a fresh temporary directory: the agent is told to run
    the same demo under runs/gate, and a run store refuses an existing directory
    (the first rehearsal, 2026-10-25, failed on exactly that collision).
    """
    py_files = [f for f in files if f.endswith(".py") and (worktree / f).exists()]
    with tempfile.TemporaryDirectory(prefix="daily-gate-") as runs_root:
        for name, argv in gate_commands(python, py_files, runs_root):
            proc = subprocess.run(argv, cwd=worktree, capture_output=True, text=True, timeout=1800)
            if name == "pyflakes" and proc.returncode and "No module named" in proc.stderr:
                continue  # optional linter; its absence is not the agent's fault
            if proc.returncode:
                tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-8:])
                return [f"{name} failed ({proc.returncode}): {tail}"]
    return []


def shell_verifier(commands: list[str]) -> "Verifier":
    """Another repository's own checks: shell commands run in the worktree, in order, first failure stops."""

    def run_checks(worktree: Path, python: str, files: tuple[str, ...]) -> list[str]:
        for command in commands:
            proc = subprocess.run(command, shell=True, cwd=worktree, capture_output=True, text=True, timeout=1800)
            if proc.returncode:
                tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-8:])
                return [f"{command[:60]} failed ({proc.returncode}): {tail}"]
        return []

    return run_checks


def fast_forward(repo: Path, branch: str, commit: str) -> tuple[bool, str]:
    """Move the repository's checked-out branch to the commit so the machine runs it.

    Only a fast-forward of the branch that is checked out: another branch, a
    detached head or local edits in the way are a note for the operator, never
    a reset.
    """
    head = subprocess.run(["git", "symbolic-ref", "-q", "--short", "HEAD"], cwd=repo, capture_output=True, text=True)
    checked_out = head.stdout.strip()
    if checked_out != branch:
        return False, f"skipped: {checked_out or 'a detached HEAD'} is checked out, not {branch}"
    proc = subprocess.run(["git", "merge", "-q", "--ff-only", commit], cwd=repo, capture_output=True, text=True)
    if proc.returncode:
        return False, (proc.stderr or proc.stdout).strip()[-300:]
    return True, ""


def run_after(command: str, repo: Path) -> dict[str, Any]:
    proc = subprocess.run(command, shell=True, cwd=repo, capture_output=True, text=True, timeout=600)
    tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-5:])
    return {"command": command, "exit_code": proc.returncode, "tail": tail[-500:]}


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
    merge: bool = False,
    branch: str = "main",
    base: str | None = None,
    state_dir: Path | None = None,
    prompt: str = PROMPT,
    guarded_prefixes: tuple[str, ...] = GUARDED_PREFIXES,
    gates: str = DEFAULT_GATES,
    after: str | None = None,
    max_files: int = MAX_FILES,
    max_lines: int = MAX_LINES,
    timeout: float = TIMEOUT_SECONDS,
    verifier: Verifier = verify,
) -> Outcome:
    state_dir = state_dir or repo / "state" / "daily"
    outcome = Outcome(date=date, status="started")
    try:
        worktree, outcome.branch = prepare_worktree(repo, date, state_dir=state_dir, base=base or f"origin/{branch}")
    except AlreadyRan as exc:
        outcome.status, outcome.summary = "already_ran", f"worktree exists: {exc}"
        return outcome
    outcome.worktree = str(worktree)

    started = time.time()
    result = executor.execute(
        request_for(worktree, date, python=python, max_files=max_files, max_lines=max_lines, timeout=timeout,
                    prompt=prompt)
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
    outcome.agent_text = text[:4000]
    if result.status != "success":
        outcome.status = "agent_failed"
        outcome.summary = (result.stderr or text or "")[-500:]
        return outcome

    change = staged_change(worktree)
    outcome.files, outcome.insertions, outcome.deletions = list(change.files), change.insertions, change.deletions
    message = commit_message(text, date, gates)
    if not change.files or message is None:
        outcome.status = "no_change"
        outcome.summary = text[:500] or "agent changed nothing"
        if not change.files:
            discard_worktree(repo, worktree, outcome.branch)
        return outcome

    outcome.gate = gate(change, max_files=max_files, max_lines=max_lines, guarded_prefixes=guarded_prefixes)
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
    if push:
        pushed = subprocess.run(["git", "push", "-q", "origin", f"HEAD:{branch}"], cwd=worktree, capture_output=True, text=True)
        if pushed.returncode:
            outcome.status, outcome.summary = "push_rejected", pushed.stderr.strip()[-500:]
            return outcome
        outcome.pushed = True
    if merge:
        outcome.merged, outcome.merge_note = fast_forward(repo, branch, outcome.commit)
        if not outcome.merged and not outcome.pushed:
            outcome.status = "merge_failed"  # the commit sits on daily/<date>; a human merges or drops it
            return outcome
    if not (outcome.pushed or outcome.merged):
        outcome.status = "committed"
        return outcome
    outcome.status = "pushed" if outcome.pushed else "merged"
    if after:
        outcome.after = run_after(after, repo)
    discard_worktree(repo, worktree, outcome.branch)
    return outcome


def write_report(repo: Path, outcome: Outcome, state_dir: Path | None = None) -> Path:
    outcome.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
    path = (state_dir or repo / "state" / "daily") / f"{outcome.date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(outcome), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


EXIT_CODES = {"pushed": 0, "merged": 0, "committed": 0, "no_change": 0, "already_ran": 2}


def has_remote(repo: Path) -> bool:
    return subprocess.run(["git", "remote", "get-url", "origin"], cwd=repo, capture_output=True).returncode == 0


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
    parser.add_argument("--merge", action="store_true", help="after a green pass, fast-forward the checked-out branch")
    parser.add_argument("--branch", default="main", help="branch the pass pushes to and merges into")
    parser.add_argument("--base", default=None, help="start point (default: origin/<branch>, or <branch> without a remote)")
    parser.add_argument("--state", default=None, help="directory for the worktree and <date>.json (default: <repo>/state/daily)")
    parser.add_argument("--prompt", default=None, metavar="FILE", help="instruction; {python} {max_files} {max_lines} are filled in")
    parser.add_argument("--verify", action="append", default=None, metavar="CMD",
                        help="shell check run in the worktree, in order; given at all, replaces pyflakes/pytest/demo/replay")
    parser.add_argument("--guard", action="append", default=[], metavar="PREFIX", help="extra path prefix the agent may not touch")
    parser.add_argument("--after", default=None, metavar="CMD", help="shell command run in the repository after a pushed or merged pass")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    python = args.python or str(repo / ".venv" / "bin" / "python")
    date = args.date or datetime.now(KST).strftime("%Y-%m-%d")
    state_dir = Path(args.state).resolve() if args.state else repo / "state" / "daily"
    base = args.base or (f"origin/{args.branch}" if has_remote(repo) else args.branch)
    verifier: Verifier = shell_verifier(args.verify) if args.verify else verify
    gates = f"{len(args.verify)} repository checks and a secret scan" if args.verify else DEFAULT_GATES
    outcome = run_pass(
        repo,
        date=date,
        python=python,
        executor=default_executor(args.model),
        push=not args.no_push,
        merge=args.merge,
        branch=args.branch,
        base=base,
        state_dir=state_dir,
        prompt=Path(args.prompt).read_text(encoding="utf-8") if args.prompt else PROMPT,
        guarded_prefixes=GUARDED_PREFIXES + tuple(args.guard),
        gates=gates,
        after=args.after,
        max_files=args.max_files,
        max_lines=args.max_lines,
        timeout=args.timeout,
        verifier=verifier,
    )
    report = write_report(repo, outcome, state_dir)
    print(json.dumps({"status": outcome.status, "summary": outcome.summary[:200], "report": str(report)}, ensure_ascii=False))
    return EXIT_CODES.get(outcome.status, 1)


if __name__ == "__main__":
    raise SystemExit(main())
