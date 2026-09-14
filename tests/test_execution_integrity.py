"""Execution evidence corruption and interruption boundaries, entirely offline."""

import json
from dataclasses import dataclass, replace

import pytest

from stigdev.cli import main
from stigdev.execution import (
    ExecutionIntegrityError,
    execute_agent,
    inspect_executions,
    recover_executions,
)
from stigdev.executor import ContractError, ExecutionBudget, ExecutionRequest
from stigdev.store import RunStore
from stigdev.testing import DeterministicFakeExecutor, FakeWorkspaceBackend
from stigdev.workspace import WorkspaceSpec


@pytest.fixture
def case(tmp_path):
    store = RunStore.create(tmp_path / "run")
    backend = FakeWorkspaceBackend()
    ref = backend.create(WorkspaceSpec("workspace-1", "synthetic"))
    executor = DeterministicFakeExecutor(backend)
    request = ExecutionRequest(
        "run-1", "task-1", "attempt-1", executor.executor_id, ref, "Synthetic change."
    )
    return store, backend, executor, request


def test_only_known_budget_fields_are_durable_and_safe_env_is_usable(case):
    @dataclass(frozen=True)
    class ExtendedBudget(ExecutionBudget):
        private_value: str = "synthetic-private-budget-extension"

    store, backend, executor, request = case
    request = replace(request, budget=ExtendedBudget(), environment=(("CI", "1"), ("LANG", "C")))
    result = execute_agent(store, request, executor, backend)
    assert result.status == "success"
    assert "synthetic-private-budget-extension" not in store.events_path.read_text()
    assert store.events()[0]["budget"] == {"max_tokens": None, "max_usd": 0.0}
    assert inspect_executions(store)[0]["status"] == "success"


@pytest.mark.parametrize("stage", ["workspace_prepared", "execution_started"])
def test_interrupted_before_agent_start_recovers_without_inventing_start(case, monkeypatch, stage):
    store, backend, executor, request = case
    original_append = store.append_event

    def interrupted(kind, **payload):
        if kind == stage:
            raise KeyboardInterrupt()
        return original_append(kind, **payload)

    monkeypatch.setattr(store, "append_event", interrupted)
    with pytest.raises(KeyboardInterrupt):
        execute_agent(store, request, executor, backend)
    assert executor.calls == 0
    (projection,) = recover_executions(RunStore.open(store.root))
    assert projection["status"] == "interrupted"
    assert projection["result"]["started_at"] is None
    assert projection["result"]["retryable"] is False


def test_failed_event_append_prevents_executor_start(case, monkeypatch):
    store, backend, executor, request = case
    original_append = store.append_event

    def disk_full(kind, **payload):
        if kind == "execution_started":
            raise OSError("simulated disk full")
        return original_append(kind, **payload)

    monkeypatch.setattr(store, "append_event", disk_full)
    with pytest.raises(OSError):
        execute_agent(store, request, executor, backend)
    assert executor.calls == 0
    assert inspect_executions(store)[0]["status"] == "prepared"


def test_unresolved_workspace_cannot_start_another_attempt(case, monkeypatch):
    store, backend, executor, request = case

    def interrupt(_request):
        raise KeyboardInterrupt()

    monkeypatch.setattr(executor, "execute", interrupt)
    with pytest.raises(KeyboardInterrupt):
        execute_agent(store, request, executor, backend)
    original = store.events_path.read_bytes()
    with pytest.raises(ContractError, match="unresolved"):
        execute_agent(store, replace(request, attempt_id="attempt-2"), executor, backend)
    assert store.events_path.read_bytes() == original


@pytest.mark.parametrize("scenario", ["native_timeout", "late_return", "missing_start"])
def test_runner_enforces_result_deadline_and_start_contract(case, monkeypatch, scenario):
    store, backend, executor, request = case
    original_execute = executor.execute
    if scenario == "native_timeout":

        def execute(_request):
            raise TimeoutError("private exception text")

        monkeypatch.setattr(executor, "execute", execute)
    elif scenario == "missing_start":

        def execute(received):
            return replace(
                original_execute(received),
                status="failed",
                exit_code=None,
                failure_classification="executor_error",
                started_at=None,
            )

        monkeypatch.setattr(executor, "execute", execute)
    else:
        values = iter([0.0, request.timeout_seconds + 1])
        monkeypatch.setattr("stigdev.execution.time.monotonic", lambda: next(values))
    result = execute_agent(store, request, executor, backend)
    assert result.status == ("failed" if scenario == "missing_start" else "timed_out")
    assert "private exception text" not in store.events_path.read_text()
    assert inspect_executions(store)[0]["status"] == result.status


def test_sensitive_artifact_reference_is_rejected_without_rewriting_content(case):
    store, backend, _, request = case
    secret = "synthetic-env-value-not-for-public-records"
    source = f'VALUE = "{secret}"\n'
    digest = store.put_artifact(source)  # Simulated pre-existing unsafe input.
    request = replace(request, environment=(("SYNTHETIC_TOKEN", secret),))
    result = execute_agent(
        store, request, DeterministicFakeExecutor(backend, artifact_hashes=(digest,)), backend
    )
    assert result.failure_classification == "malformed_result"
    assert result.artifact_hashes == ()
    assert store.get_artifact(digest) == source  # Never rewrite immutable input.
    assert secret not in store.events_path.read_text()
    assert digest not in store.events_path.read_text()


@pytest.mark.parametrize(
    "mutation",
    [
        "version",
        "causation",
        "revision",
        "timestamp",
        "raw_log",
        "sequence",
        "status",
        "deadline",
        "run_id",
    ],
)
def test_corrupt_execution_events_fail_closed_during_inspection_and_recovery(case, mutation):
    store, backend, executor, request = case
    execute_agent(store, request, executor, backend)
    events = store.events()
    store.write_manifest({"run_id": request.run_id})
    if mutation == "version":
        events[1]["execution_version"] = 99
    elif mutation == "causation":
        events[2]["caused_by_seq"] = 999
    elif mutation == "revision":
        events[1]["revision"] = {"not": "a revision"}
    elif mutation == "timestamp":
        events[2]["ts"] = float("nan")
    elif mutation == "raw_log":
        events[3]["result"]["stdout"] = "unapproved raw log"
    elif mutation == "sequence":
        events[2]["seq"] = events[1]["seq"]
    elif mutation == "deadline":
        events[3]["result"]["finished_at"] = (
            events[3]["result"]["started_at"] + request.timeout_seconds + 1
        )
    elif mutation == "run_id":
        for event in events:
            event["run_id"] = "foreign-run"
    else:
        events[3]["result"]["status"] = "cancelled"
    store.events_path.write_text("".join(json.dumps(e) + "\n" for e in events))
    original = store.events_path.read_bytes()
    with pytest.raises(ExecutionIntegrityError):
        inspect_executions(store)
    with pytest.raises(ExecutionIntegrityError):
        recover_executions(store)
    assert store.events_path.read_bytes() == original


def test_cli_inspection_and_interruption_recovery(case, monkeypatch, capsys):
    store, backend, executor, request = case

    def interrupt(_request):
        raise KeyboardInterrupt()

    monkeypatch.setattr(executor, "execute", interrupt)
    with pytest.raises(KeyboardInterrupt):
        execute_agent(store, request, executor, backend)
    original = store.events_path.read_bytes()
    assert main(["executions", str(store.root)]) == 0
    assert json.loads(capsys.readouterr().out)[0]["status"] == "running"
    assert store.events_path.read_bytes() == original
    assert main(["recover-executions", str(store.root)]) == 0
    assert json.loads(capsys.readouterr().out)[0]["status"] == "interrupted"
    assert main(["executions", str(store.root)]) == 0
    assert json.loads(capsys.readouterr().out)[0]["status"] == "interrupted"
