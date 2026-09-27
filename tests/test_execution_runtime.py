"""Offline execution evidence, fail-closed outcomes, and recovery integration.

All agents and workspaces here are in-process test doubles. The Provider demo
is the existing synthetic benchmark, not a coding-agent CLI or live model.
"""

from __future__ import annotations

import json
import shutil
import socket
from dataclasses import replace
from pathlib import Path

import pytest

from stigdev.execution import execute_agent, inspect_executions, recover_executions
from stigdev.executor import ContractError, ExecutionBudget, ExecutionRequest, ExecutionUsage
from stigdev.replay import recover, replay
from stigdev.store import RunStore
from stigdev.testing import DeterministicFakeExecutor, FakeWorkspaceBackend
from stigdev.workspace import WorkspaceSpec


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("execution contract tests must remain offline")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


@pytest.fixture
def execution_case(tmp_path):
    store = RunStore.create(tmp_path / "run-contract")
    store.write_manifest({"run_id": "run-contract"})
    backend = FakeWorkspaceBackend()
    workspace = backend.create(WorkspaceSpec("workspace-1", "synthetic-repo", "base-1"))
    executor = DeterministicFakeExecutor(backend)
    request = ExecutionRequest(
        run_id="run-contract",
        task_id="task-1",
        attempt_id="attempt-1",
        executor_id=executor.executor_id,
        workspace=workspace,
        instruction="Apply a synthetic, offline change.",
    )
    return store, backend, executor, request


def test_success_persists_inspectable_evidence_without_promotion(execution_case):
    store, backend, executor, request = execution_case
    seed_hash = store.put_artifact("VALUE = 1\n")
    store.set_canonical(seed_hash, 0, 0.0)
    candidate_hash = store.put_artifact("VALUE = 2\n")
    executor = DeterministicFakeExecutor(backend, artifact_hashes=(candidate_hash,))

    result = execute_agent(store, request, executor, backend)

    assert result.status == "success"
    assert result.exit_code == 0
    assert result.failure_classification == "none"
    assert result.started_at <= result.finished_at
    assert result.artifact_hashes == (candidate_hash,)
    assert result.revision_before == "base-1"
    assert result.revision_after != result.revision_before
    assert store.get_artifact(seed_hash) == "VALUE = 1\n"
    assert store.get_artifact(candidate_hash) == "VALUE = 2\n"
    assert store.canonical() == {"artifact_hash": seed_hash, "generation": 0, "score": 0.0}
    assert store.events("promoted") == []
    assert store.events("evaluated") == []

    (projection,) = inspect_executions(RunStore.open(store.root))
    assert projection["attempt_id"] == request.attempt_id
    assert projection["status"] == "success"
    assert projection["result"]["artifact_hashes"] == [candidate_hash]
    assert projection["result"]["revision_before"] == "base-1"
    assert projection["result"]["revision_after"] == result.revision_after


def test_budget_and_reported_usage_are_inspectable_metadata(execution_case, monkeypatch):
    store, backend, executor, request = execution_case
    request = replace(request, budget=ExecutionBudget(max_tokens=100, max_usd=0.0))
    usage = ExecutionUsage(input_tokens=12, output_tokens=7, usd=0.0)
    original_execute = executor.execute

    def reported_usage(received):
        return replace(original_execute(received), usage=usage)

    monkeypatch.setattr(executor, "execute", reported_usage)
    result = execute_agent(store, request, executor, backend)

    assert result.usage == usage
    (projection,) = inspect_executions(store)
    assert projection["budget"] == {"max_tokens": 100, "max_usd": 0.0}
    assert projection["result"]["usage"] == {
        "input_tokens": 12,
        "output_tokens": 7,
        "usd": 0.0,
    }


@pytest.mark.parametrize(
    ("scenario", "status", "event_type"),
    [
        ("nonzero_exit", "failed", "execution_failed"),
        ("timeout", "timed_out", "execution_timed_out"),
        ("cancelled", "cancelled", "execution_cancelled"),
        ("malformed", "failed", "execution_failed"),
        ("raise_error", "failed", "execution_failed"),
    ],
)
def test_fake_failures_are_terminal_and_never_promoted(
    execution_case, scenario, status, event_type
):
    store, backend, _, request = execution_case
    executor = DeterministicFakeExecutor(backend, scenario=scenario)

    result = execute_agent(store, request, executor, backend)

    assert result.status == status
    assert result.failure_classification != "none"
    assert store.events()[-1]["type"] == event_type
    assert store.events()[-1]["result"]["status"] == status
    assert inspect_executions(store)[0]["status"] == status
    assert store.canonical() is None
    assert store.events("promoted") == []
    if scenario == "nonzero_exit":
        assert result.exit_code not in (0, None)
    if scenario == "malformed":
        assert not result.retryable


def test_workspace_preparation_failure_never_starts_executor(execution_case, monkeypatch):
    store, backend, executor, request = execution_case
    backend.fail_prepare = True

    def forbidden_execute(_request):
        pytest.fail("executor must not start when workspace preparation fails")

    monkeypatch.setattr(executor, "execute", forbidden_execute)
    result = execute_agent(store, request, executor, backend)

    assert result.status == "failed"
    assert result.failure_classification != "none"
    assert [event["type"] for event in store.events()] == [
        "execution_requested",
        "execution_failed",
    ]
    assert store.canonical() is None


def test_event_order_and_causation_survive_unrelated_events(execution_case):
    store, backend, executor, request = execution_case
    store.append_event("unrelated_observation", note="synthetic")
    execute_agent(store, request, executor, backend)

    events = store.events()[1:]
    assert [event["type"] for event in events] == [
        "execution_requested",
        "workspace_prepared",
        "execution_started",
        "execution_completed",
    ]
    assert [event["seq"] for event in events] == [2, 3, 4, 5]
    for event in events:
        assert event["execution_version"] == 1
        assert event["run_id"] == request.run_id
        assert event["task_id"] == request.task_id
        assert event["attempt_id"] == request.attempt_id
        assert event["executor_id"] == request.executor_id
        assert event["workspace_id"] == request.workspace.workspace_id
        assert event["backend_id"] == request.workspace.backend_id
        assert event["parent_attempt_id"] is None
    assert events[0]["caused_by_seq"] is None
    for event in events[1:]:
        assert event["request_seq"] == events[0]["seq"]
    for previous, following in zip(events, events[1:]):
        assert following["caused_by_seq"] == previous["seq"]


def test_duplicate_attempt_cannot_execute_twice(execution_case, monkeypatch):
    store, backend, executor, request = execution_case
    execute_agent(store, request, executor, backend)
    original_events = store.events_path.read_bytes()

    def forbidden_execute(_request):
        pytest.fail("a duplicate attempt must not execute again")

    monkeypatch.setattr(executor, "execute", forbidden_execute)
    with pytest.raises(ContractError):
        execute_agent(RunStore.open(store.root), request, executor, backend)
    assert store.events_path.read_bytes() == original_events


def test_unknown_parent_attempt_is_rejected_before_side_effects(execution_case, monkeypatch):
    store, backend, executor, request = execution_case
    request = replace(request, parent_attempt_id="missing-attempt")

    def forbidden_prepare(_workspace):
        pytest.fail("a request without durable parent lineage must not prepare a workspace")

    monkeypatch.setattr(backend, "prepare", forbidden_prepare)
    with pytest.raises(ContractError):
        execute_agent(store, request, executor, backend)
    assert store.events() == []


def test_late_success_is_recorded_as_timeout(execution_case):
    store, backend, _, request = execution_case
    request = replace(request, timeout_seconds=1.0)
    executor = DeterministicFakeExecutor(backend, duration=2.0)

    result = execute_agent(store, request, executor, backend)

    assert result.status == "timed_out"
    assert result.failure_classification == "timeout"
    assert store.events("execution_completed") == []
    assert store.events()[-1]["type"] == "execution_timed_out"


def test_retry_has_new_attempt_and_preserves_artifact_revision_lineage(execution_case):
    store, backend, _, request = execution_case
    first_executor = DeterministicFakeExecutor(backend, scenario="nonzero_exit")
    first = execute_agent(store, request, first_executor, backend)
    original_events = store.events_path.read_bytes()
    candidate_hash = store.put_artifact("VALUE = 'synthetic retry'\n")
    retry = replace(request, attempt_id="attempt-2", parent_attempt_id=request.attempt_id)
    second_executor = DeterministicFakeExecutor(backend, artifact_hashes=(candidate_hash,))

    second = execute_agent(store, retry, second_executor, backend)

    assert first.status == "failed"
    assert second.status == "success"
    assert second.revision_before == first.revision_after
    assert store.events_path.read_bytes().startswith(original_events)
    attempts = inspect_executions(RunStore.open(store.root))
    assert [attempt["attempt_id"] for attempt in attempts] == ["attempt-1", "attempt-2"]
    assert attempts[1]["parent_attempt_id"] == "attempt-1"
    assert attempts[1]["result"]["artifact_hashes"] == [candidate_hash]
    for event in store.events():
        if event.get("attempt_id") == "attempt-2":
            assert event["parent_attempt_id"] == "attempt-1"
    assert store.events("promoted") == []


class SimulatedInterruption(BaseException):
    """Models an abrupt process loss after a durable started record."""


def test_recovery_marks_interrupted_attempt_once_without_reexecution(execution_case, monkeypatch):
    store, backend, executor, request = execution_case
    calls = []

    def interrupted(received):
        calls.append(received.attempt_id)
        backend.record_revision(received.workspace, "partial-change")
        raise SimulatedInterruption("synthetic process interruption")

    monkeypatch.setattr(executor, "execute", interrupted)
    with pytest.raises(SimulatedInterruption):
        execute_agent(store, request, executor, backend)
    assert inspect_executions(store)[0]["status"] == "running"
    before = store.events_path.read_bytes()

    reopened = RunStore.open(store.root)
    recover_executions(reopened)

    assert calls == ["attempt-1"]
    assert reopened.events_path.read_bytes().startswith(before)
    assert reopened.events()[-1]["type"] == "execution_interrupted"
    (recovered,) = inspect_executions(reopened)
    assert recovered["status"] == "interrupted"
    assert recovered["result"]["failure_classification"] != "none"
    assert recovered["result"]["revision_after"] is None
    terminal_events = reopened.events_path.read_bytes()
    recover_executions(RunStore.open(store.root))
    assert reopened.events_path.read_bytes() == terminal_events
    assert calls == ["attempt-1"]
    assert reopened.canonical() is None


def test_post_execution_inspection_failure_cannot_claim_success(execution_case, monkeypatch):
    store, backend, executor, request = execution_case
    original_execute = executor.execute

    def inaccessible_workspace(*args):
        raise RuntimeError("synthetic inspection outage")

    def lose_workspace(received):
        result = original_execute(received)
        monkeypatch.setattr(backend, "inspect", inaccessible_workspace)
        return result

    monkeypatch.setattr(executor, "execute", lose_workspace)
    result = execute_agent(store, request, executor, backend)

    assert result.status == "failed"
    assert result.failure_classification == "workspace_inspection"
    assert store.events("execution_completed") == []
    assert store.events()[-1]["type"] == "execution_failed"


@pytest.mark.parametrize("failure_at", ["prepare", "execute"])
def test_exception_messages_cannot_persist_secrets(execution_case, monkeypatch, failure_at):
    store, backend, executor, request = execution_case
    private_instruction = "PRIVATE synthetic task detail 4f5179"
    secret = "synthetic-secret-value-922d6d"
    request = replace(request, instruction=private_instruction, environment=(("TOKEN", secret),))

    def exploding(*args):
        raise RuntimeError(f"{private_instruction} TOKEN={secret}")

    monkeypatch.setattr(backend if failure_at == "prepare" else executor, failure_at, exploding)
    result = execute_agent(store, request, executor, backend)

    assert result.status == "failed"
    records = store.events_path.read_text(encoding="utf-8")
    assert private_instruction not in records
    assert secret not in records
    assert "TOKEN" not in records
    assert "RuntimeError" not in records


def test_echoed_output_and_host_environment_do_not_enter_durable_records(
    execution_case, monkeypatch
):
    store, backend, _, request = execution_case
    private_instruction = "PRIVATE synthetic instruction 490e37"
    secret = "synthetic-secret-166e02"
    host_secret = "synthetic-host-secret-a7af0b"
    monkeypatch.setenv("UNRELATED_HOST_SECRET", host_secret)
    request = replace(
        request,
        instruction=private_instruction,
        environment=(("TOKEN", secret),),
        workspace=replace(request.workspace, locator=f"private://{secret}/workspace"),
    )
    executor = DeterministicFakeExecutor(
        backend,
        stdout=f"{private_instruction}\nTOKEN={secret}\n{host_secret}",
        stderr=f"Failed transcript: {private_instruction}; {secret}",
    )
    original_execute = executor.execute
    received = []

    def observe_environment(received_request):
        received.append(received_request)
        return original_execute(received_request)

    monkeypatch.setattr(executor, "execute", observe_environment)
    result = execute_agent(store, request, executor, backend)

    assert result.status == "success"
    assert received[0].environment == (("TOKEN", secret),)
    assert host_secret not in repr(received[0].environment)
    public_records = store.events_path.read_text(encoding="utf-8")
    public_projection = json.dumps(inspect_executions(store))
    for sensitive in (private_instruction, secret, host_secret, "TOKEN", "UNRELATED_HOST_SECRET"):
        assert sensitive not in public_records
        assert sensitive not in public_projection


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "unrecognized"},
        {"exit_code": 7},
        {"attempt_id": "different-attempt"},
        {"finished_at": float("nan")},
        {"finished_at": 0.0},
        {"artifact_hashes": ("../not-an-artifact",)},
        {"artifact_hashes": ("f" * 64,)},
    ],
)
def test_malformed_executor_fields_fail_closed(execution_case, monkeypatch, changes):
    store, backend, executor, request = execution_case
    original_execute = executor.execute

    def malformed(received):
        return replace(original_execute(received), **changes)

    monkeypatch.setattr(executor, "execute", malformed)
    result = execute_agent(store, request, executor, backend)

    assert result.status == "failed"
    assert not result.retryable
    assert store.events()[-1]["type"] == "execution_failed"
    assert store.events("execution_completed") == []
    assert store.canonical() is None


def test_execution_events_preserve_provider_replay_and_canonical_recovery(demo_run, tmp_path: Path):
    demo_dir, _ = demo_run
    run_dir = tmp_path / "provider-compatibility"
    shutil.copytree(demo_dir, run_dir)
    store = RunStore.open(run_dir)
    canonical = store.canonical()
    manifest = store.manifest_path.read_bytes()
    old_events = store.events_path.read_bytes()
    old_lineage = store.lineage_edges()
    backend = FakeWorkspaceBackend()
    workspace = backend.create(WorkspaceSpec("workspace-compat", "synthetic-repo", "base-1"))
    executor = DeterministicFakeExecutor(backend)
    request = ExecutionRequest(
        run_id=store.manifest()["run_id"],
        task_id="task-compat",
        attempt_id="attempt-compat",
        executor_id=executor.executor_id,
        workspace=workspace,
        instruction="A separate synthetic execution must not change the research result.",
    )

    execute_agent(store, request, executor, backend)

    assert store.canonical() == canonical
    assert store.manifest_path.read_bytes() == manifest
    assert store.events_path.read_bytes().startswith(old_events)
    assert store.lineage_edges() == old_lineage
    replay_report = replay(run_dir)
    assert replay_report == {"ok": True, "checked": 9, "decisions": 8, "divergences": []}

    store.set_canonical("0" * 64, 99, -1.0)
    assert recover(run_dir)["recovered"]
    assert RunStore.open(run_dir).canonical() == canonical
    assert inspect_executions(RunStore.open(run_dir))[0]["status"] == "success"
    assert replay(run_dir)["ok"]
