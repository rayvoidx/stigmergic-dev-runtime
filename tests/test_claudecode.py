"""Offline tests for the Claude Code agent executor (ADR 0014).

The real CLI is never invoked: every test injects a fake runner. The point of
most of them is the billing route — Claude Code runs on the operator's
subscription, and this executor must refuse to become a metered API call.
"""

import json

import pytest

from stigdev.claudecode import (
    BILLING_ROUTE_VARS,
    SUBSCRIPTION_USD,
    ClaudeCodeError,
    ClaudeCodeExecutor,
)
from stigdev.executor import ExecutionBudget, ExecutionRequest, validate_result
from stigdev.workspace import WorkspaceRef

WORKSPACE = WorkspaceRef(backend_id="fake-backend", workspace_id="ws-1", locator="/tmp/ws-1")


class FakeRun:
    """Stands in for subprocess.run; records what the executor would have launched."""

    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = "", raises=None):
        self.stdout, self.returncode, self.stderr, self.raises = stdout, returncode, stderr, raises
        self.calls: list[dict] = []

    def __call__(self, argv, *, cwd, env, timeout, capture_output, text, check):
        self.calls.append({"argv": argv, "cwd": cwd, "env": env, "timeout": timeout})
        if self.raises is not None:
            raise self.raises
        return type("Completed", (), {
            "returncode": self.returncode, "stdout": self.stdout, "stderr": self.stderr
        })()


def result_json(**kw) -> str:
    base = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "done",
        "session_id": "s-1",
        "total_cost_usd": 0.42,
        "usage": {"input_tokens": 120, "output_tokens": 45},
    }
    base.update(kw)
    return json.dumps(base)


def request(**kw) -> ExecutionRequest:
    base = dict(
        run_id="run-1",
        task_id="task-1",
        attempt_id="attempt-1",
        executor_id="claude-code/v1",
        workspace=WORKSPACE,
        instruction="summarise the failing test",
        timeout_seconds=30.0,
        budget=ExecutionBudget(),
    )
    base.update(kw)
    return ExecutionRequest(**base)


def executor(runner, **kw) -> ClaudeCodeExecutor:
    return ClaudeCodeExecutor(runner=runner, binary="/usr/local/bin/claude", **kw)


# --- the billing route is the whole point -------------------------------------


def test_the_subprocess_never_inherits_an_api_key():
    runner = FakeRun(stdout=result_json())
    executor(runner, base_environment={"ANTHROPIC_API_KEY": "sk-not-real", "PATH": "/usr/bin"}).execute(request())
    passed = runner.calls[0]["env"]
    assert "ANTHROPIC_API_KEY" not in passed
    assert passed["PATH"] == "/usr/bin"


@pytest.mark.parametrize("var", sorted(BILLING_ROUTE_VARS))
def test_a_request_that_asks_for_a_metered_route_is_refused(var: str):
    runner = FakeRun(stdout=result_json())
    with pytest.raises(ClaudeCodeError, match="billing route"):
        executor(runner).execute(request(environment=((var, "x"),)))
    assert runner.calls == [], "nothing may be launched once a billing variable is present"


def test_every_known_billing_route_is_stripped_not_just_the_api_key():
    runner = FakeRun(stdout=result_json())
    leaky = {v: "x" for v in BILLING_ROUTE_VARS} | {"HOME": "/Users/x"}
    executor(runner, base_environment=leaky).execute(request())
    assert set(runner.calls[0]["env"]) == {"HOME"}


def test_subscription_usage_is_never_recorded_as_money_spent():
    """The CLI reports an API-equivalent estimate; no cash moves on a subscription,
    so reporting it as `usd` would corrupt every budget that reads this field."""
    runner = FakeRun(stdout=result_json(total_cost_usd=12.5))
    result = executor(runner).execute(request())
    assert result.usage is not None
    assert result.usage.usd == SUBSCRIPTION_USD == 0.0
    assert result.usage.input_tokens == 120 and result.usage.output_tokens == 45


# --- invocation ---------------------------------------------------------------


def test_it_runs_headless_in_the_workspace_and_asks_for_json():
    runner = FakeRun(stdout=result_json())
    executor(runner).execute(request())
    call = runner.calls[0]
    assert call["argv"][0] == "/usr/local/bin/claude"
    assert "-p" in call["argv"] and "--output-format" in call["argv"]
    assert call["argv"][call["argv"].index("--output-format") + 1] == "json"
    assert call["cwd"] == "/tmp/ws-1"
    assert call["timeout"] == 30.0


def test_a_workspace_without_a_locator_cannot_be_entered():
    runner = FakeRun(stdout=result_json())
    with pytest.raises(ClaudeCodeError, match="locator"):
        executor(runner).execute(request(workspace=WorkspaceRef("fake-backend", "ws-2")))


def test_the_model_alias_is_passed_through_when_asked():
    runner = FakeRun(stdout=result_json())
    executor(runner, model="sonnet").execute(request())
    argv = runner.calls[0]["argv"]
    assert argv[argv.index("--model") + 1] == "sonnet"
    plain = FakeRun(stdout=result_json())
    executor(plain).execute(request())
    assert "--model" not in plain.calls[0]["argv"]


# --- outcomes -----------------------------------------------------------------


def test_a_clean_run_is_a_validated_success():
    result = executor(FakeRun(stdout=result_json())).execute(request())
    assert result.status == "success" and result.exit_code == 0
    assert result.failure_classification == "none" and not result.retryable
    assert result.attempt_id == "attempt-1" and result.workspace == WORKSPACE
    validate_result(result, request())


def test_a_reported_error_is_a_failure_even_with_exit_zero():
    runner = FakeRun(stdout=result_json(is_error=True, subtype="error_during_execution"))
    result = executor(runner).execute(request())
    assert result.status == "failed" and result.failure_classification == "executor_error"
    nonzero = FakeRun(stdout=result_json(), returncode=2)
    assert executor(nonzero).execute(request()).failure_classification == "nonzero_exit"


def test_a_timeout_is_retryable_and_classified():
    import subprocess

    runner = FakeRun(raises=subprocess.TimeoutExpired(cmd="claude", timeout=30.0))
    result = executor(runner).execute(request())
    assert result.status == "timed_out" and result.retryable
    assert result.failure_classification == "timeout"
    validate_result(result, request())


def test_unparseable_output_fails_closed_rather_than_inventing_a_result():
    result = executor(FakeRun(stdout="not json at all")).execute(request())
    assert result.status == "failed"
    assert result.failure_classification == "malformed_result"
    assert result.usage is None


def test_a_missing_binary_is_an_executor_failure_not_an_agent_failure():
    runner = FakeRun(raises=FileNotFoundError("claude"))
    result = executor(runner).execute(request())
    assert result.status == "failed" and result.failure_classification == "executor_error"
    assert not result.retryable


def test_timestamps_are_recorded_for_every_outcome():
    for runner in (FakeRun(stdout=result_json()), FakeRun(stdout="junk", returncode=1)):
        result = executor(runner).execute(request())
        assert result.started_at is not None
        assert result.finished_at >= result.started_at
