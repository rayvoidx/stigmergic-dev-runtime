"""Offline tests for the daily unattended pass (ADR 0016).

No real agent, no network. The end-to-end cases drive `run_pass` against a
temporary bare "origin" with a fake executor that edits the worktree, so what
is tested is the whole path from branch to push, minus the model.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from stigdev.executor import ExecutionResult, ExecutionUsage

spec = importlib.util.spec_from_file_location(
    "daily_pass", Path(__file__).resolve().parents[1] / "scripts" / "daily_pass.py"
)
daily_pass = importlib.util.module_from_spec(spec)
sys.modules["daily_pass"] = daily_pass  # dataclasses resolve annotations through sys.modules
spec.loader.exec_module(daily_pass)

DATE = "2026-10-25"


# --- pure parts ----------------------------------------------------------------


def change(files, insertions=10, deletions=2, added=""):
    return daily_pass.Change(tuple(files), insertions, deletions, added)


def test_the_agent_may_not_edit_the_gates_that_review_it():
    for guarded in (".github/workflows/ci.yml", "deploy/launchd/x.plist", "scripts/daily_pass.py",
                    "tests/test_daily_pass.py", "docs/adr/0016-daily-pass.md"):
        assert daily_pass.gate(change([guarded, "stigdev/cli.py"])), guarded
    assert daily_pass.gate(change(["stigdev/cli.py", "docs/adr/0017-next.md"])) == []


def test_size_caps_are_enforced_on_files_and_lines():
    assert daily_pass.gate(change([f"f{i}.py" for i in range(13)]), max_files=12)
    assert daily_pass.gate(change(["a.py"], insertions=500, deletions=101), max_lines=600)
    assert daily_pass.gate(change(["a.py"], insertions=500, deletions=100), max_lines=600) == []


@pytest.mark.parametrize("leak", [
    "ANTHROPIC_API_KEY = 'sk-ant-api03-abcdefghijklmnop'",
    "aws = 'AKIAABCDEFGHIJKLMNOP'",
    "token = 'ghp_" + "a" * 36 + "'",
    "-----BEGIN RSA PRIVATE KEY-----",
    'api_key: "0123456789abcdefXYZ"',
])
def test_a_credential_in_the_added_lines_fails_the_gate(leak):
    problems = daily_pass.gate(change(["stigdev/x.py"], added="before\n" + leak + "\nafter"))
    assert any("secret pattern" in p for p in problems)


def test_the_existing_fake_key_in_the_claude_code_tests_is_not_a_hit():
    added = 'executor(runner, base_environment={"ANTHROPIC_API_KEY": "sk-not-real", "PATH": "/usr/bin"})'
    assert daily_pass.gate(change(["tests/test_claudecode.py"], added=added)) == []


def test_only_added_lines_are_scanned():
    diff = "--- a/x\n+++ b/x\n-old = 'AKIAABCDEFGHIJKLMNOP'\n+new = 1\n"
    assert daily_pass.added_lines(diff) == "new = 1"


def test_numstat_parsing_tolerates_binary_files():
    files, ins, dele = daily_pass.parse_numstat("3\t1\tstigdev/a.py\n-\t-\timg.png\n")
    assert files == ("stigdev/a.py", "img.png") and (ins, dele) == (3, 1)


def test_commit_messages_get_a_conventional_subject_a_footer_and_a_trailer():
    message = daily_pass.commit_message("```\nTighten the lease check\n\nIt was off by one.\n```", DATE)
    lines = message.splitlines()
    assert lines[0] == "chore: Tighten the lease check"
    assert "It was off by one." in message
    assert f"Daily pass {DATE}" in message and lines[-1] == daily_pass.TRAILER
    kept = daily_pass.commit_message("fix: " + "x" * 100, DATE).splitlines()[0]
    assert kept.startswith("fix: ") and len(kept) <= 72


def test_no_change_means_no_message():
    assert daily_pass.commit_message("NO_CHANGE: nothing to improve today.", DATE) is None
    assert daily_pass.commit_message("   \n\n", DATE) is None


def test_the_gate_demo_never_collides_with_the_agents_own_demo_run():
    """The prompt tells the agent to demo into runs/gate; the gate must use its own directory."""
    commands = dict(daily_pass.gate_commands("py", ["a.py"], "/tmp/gate-x"))
    assert commands["demo"][-3:] == ["/tmp/gate-x", "--run-id", "gate"]
    assert commands["replay"][-1] == "/tmp/gate-x/gate" and "runs" not in commands["demo"]
    assert commands["pyflakes"][-1] == "a.py" and "pyflakes" not in dict(daily_pass.gate_commands("py", [], "/t"))


def test_the_subprocess_is_not_told_it_runs_inside_a_session():
    env = daily_pass.clean_env({"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli", "PATH": "/usr/bin", "HOME": "/h"})
    assert env == {"PATH": "/usr/bin", "HOME": "/h"}


# --- end to end against a temporary origin -------------------------------------


def sh(*argv, cwd):
    return subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True).stdout


def make_repo(tmp_path: Path) -> tuple[Path, Path]:
    origin = tmp_path / "origin.git"
    origin.mkdir()
    sh("git", "init", "-q", "--bare", "-b", "main", cwd=origin)
    repo = tmp_path / "repo"
    repo.mkdir()
    sh("git", "init", "-q", "-b", "main", cwd=repo)
    sh("git", "config", "user.name", "t", cwd=repo)
    sh("git", "config", "user.email", "t@example.com", cwd=repo)
    (repo / "README.md").write_text("hello\n")
    sh("git", "add", "README.md", cwd=repo)
    sh("git", "commit", "-q", "-m", "init", cwd=repo)
    sh("git", "remote", "add", "origin", str(origin), cwd=repo)
    sh("git", "push", "-q", "-u", "origin", "main", cwd=repo)
    return repo, origin


class EditingExecutor:
    """Stands in for Claude Code: edits the worktree, then reports a final message."""

    executor_id = "fake-agent/v1"

    def __init__(self, message: str, edit=None, status: str = "success"):
        self.message, self.edit, self.status = message, edit, status
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
        if self.edit is not None:
            self.edit(Path(request.workspace.locator))
        return ExecutionResult(
            attempt_id=request.attempt_id,
            workspace=request.workspace,
            status=self.status,  # type: ignore[arg-type]
            started_at=1.0,
            finished_at=2.0,
            exit_code=0 if self.status == "success" else 1,
            stdout=json.dumps({"type": "result", "result": self.message}),
            usage=ExecutionUsage(input_tokens=5, output_tokens=7, usd=0.0),
        )


def run(repo, executor, **kw):
    kw.setdefault("verifier", lambda worktree, python, files: [])
    return daily_pass.run_pass(repo, date=DATE, python=sys.executable, executor=executor, **kw)


def origin_subject(origin):
    return sh("git", "log", "-1", "--format=%s", "main", cwd=origin).strip()


def test_a_green_change_is_committed_pushed_and_the_worktree_is_gone(tmp_path):
    repo, origin = make_repo(tmp_path)
    agent = EditingExecutor("fix: say goodbye\n\nhello was wrong.",
                            edit=lambda wt: (wt / "README.md").write_text("goodbye\n"))
    outcome = run(repo, agent)
    assert outcome.status == "pushed" and outcome.pushed and outcome.files == ["README.md"]
    assert origin_subject(origin) == "fix: say goodbye"
    assert not Path(outcome.worktree).exists()
    assert agent.requests[0].workspace.locator == outcome.worktree
    assert dict(agent.requests[0].environment) == {"ECC_GATEGUARD": "off"}
    report = daily_pass.write_report(repo, outcome)
    assert json.loads(report.read_text())["commit"] == outcome.commit


def test_no_change_pushes_nothing_and_cleans_up(tmp_path):
    repo, origin = make_repo(tmp_path)
    outcome = run(repo, EditingExecutor("NO_CHANGE nothing worth doing."))
    assert outcome.status == "no_change" and origin_subject(origin) == "init"
    assert not Path(outcome.worktree).exists()


def test_a_change_to_the_gates_is_kept_for_a_human_and_never_pushed(tmp_path):
    repo, origin = make_repo(tmp_path)

    def edit(wt):
        (wt / ".github" / "workflows").mkdir(parents=True)
        (wt / ".github" / "workflows" / "ci.yml").write_text("on: push\n")

    outcome = run(repo, EditingExecutor("chore: loosen ci", edit=edit))
    assert outcome.status == "gated" and "guarded" in outcome.summary
    assert origin_subject(origin) == "init" and Path(outcome.worktree).exists()


def test_a_failed_verification_blocks_the_push(tmp_path):
    repo, origin = make_repo(tmp_path)
    agent = EditingExecutor("fix: x", edit=lambda wt: (wt / "README.md").write_text("x\n"))
    outcome = run(repo, agent, verifier=lambda wt, py, files: ["pytest failed (1): 1 failed"])
    assert outcome.status == "verify_failed" and origin_subject(origin) == "init"


def test_no_push_commits_on_the_branch_only(tmp_path):
    repo, origin = make_repo(tmp_path)
    agent = EditingExecutor("fix: x", edit=lambda wt: (wt / "README.md").write_text("x\n"))
    outcome = run(repo, agent, push=False)
    assert outcome.status == "committed" and outcome.commit and origin_subject(origin) == "init"
    assert sh("git", "log", "-1", "--format=%s", outcome.branch, cwd=repo).strip() == "fix: x"


def test_an_agent_failure_is_recorded_and_nothing_moves(tmp_path):
    repo, origin = make_repo(tmp_path)
    outcome = run(repo, EditingExecutor("", status="failed"))
    assert outcome.status == "agent_failed" and origin_subject(origin) == "init"
    assert outcome.agent["status"] == "failed" and outcome.agent["usd"] == 0.0


def test_a_second_run_on_the_same_day_steps_aside(tmp_path):
    repo, _ = make_repo(tmp_path)

    def edit(wt):
        (wt / "deploy").mkdir()
        (wt / "deploy" / "x").write_text("x")

    first = run(repo, EditingExecutor("chore: loosen ci", edit=edit))
    assert first.status == "gated"
    again = run(repo, EditingExecutor("fix: x"))
    assert again.status == "already_ran"
