"""Offline contract validation and deterministic workspace lifecycle fixtures."""

from dataclasses import replace

import pytest

from stigdev.executor import (
    ContractError,
    ExecutionBudget,
    ExecutionRequest,
    ExecutionUsage,
    validate_result,
)
from stigdev.model import content_hash
from stigdev.testing import DeterministicFakeExecutor, FakeWorkspaceBackend
from stigdev.workspace import WorkspaceError, WorkspaceRef, WorkspaceSpec, validate_state


def make_fixture(**executor_kwargs):
    backend = FakeWorkspaceBackend()
    workspace = backend.create(WorkspaceSpec("workspace-1", "synthetic-repository"))
    executor = DeterministicFakeExecutor(backend, **executor_kwargs)
    request = ExecutionRequest(
        "run-1", "task-1", "attempt-1", executor.executor_id, workspace, "Synthetic task"
    )
    return backend, executor, request


def test_success_is_deterministic_and_revision_identity_is_backend_observed():
    outcomes = []
    for _ in range(2):
        backend, executor, request = make_fixture(
            artifact_hashes=(content_hash("synthetic artifact"),)
        )
        before = backend.prepare(request.workspace)
        result = executor.execute(request)
        validate_result(result, request)
        assert result.status == "success"
        assert result.revision_before == before.revision
        assert result.revision_after == backend.inspect(request.workspace).revision
        assert result.revision_before != result.revision_after
        assert result.artifact_hashes == (content_hash("synthetic artifact"),)
        outcomes.append(result)
    assert outcomes[0] == outcomes[1]


@pytest.mark.parametrize(
    "scenario,status,classification,exit_code",
    [
        ("nonzero_exit", "failed", "nonzero_exit", 1),
        ("timeout", "timed_out", "timeout", None),
        ("cancelled", "cancelled", "cancelled", None),
    ],
)
def test_terminal_failures_do_not_produce_a_revision(scenario, status, classification, exit_code):
    backend, executor, request = make_fixture(scenario=scenario)
    backend.prepare(request.workspace)
    result = executor.execute(request)
    validate_result(result, request)
    assert (result.status, result.failure_classification, result.exit_code) == (
        status,
        classification,
        exit_code,
    )
    assert result.revision_before == result.revision_after
    assert not result.artifact_hashes


def test_workspace_requires_preparation_and_disposal_preserves_inspectable_identity():
    backend, executor, request = make_fixture()
    with pytest.raises(WorkspaceError):
        executor.execute(request)
    assert backend.resolve(request.workspace.workspace_id) == request.workspace
    backend.prepare(request.workspace)
    backend.retain(request.workspace)
    with pytest.raises(WorkspaceError):
        backend.prepare(request.workspace)
    disposed = backend.dispose(request.workspace)
    validate_state(disposed, request.workspace)
    assert disposed.disposition == "disposed" and not disposed.prepared
    assert backend.inspect(request.workspace) == disposed
    with pytest.raises(WorkspaceError):
        executor.execute(request)
    with pytest.raises(WorkspaceError):
        backend.create(WorkspaceSpec(request.workspace.workspace_id, "synthetic-repository"))


def test_unknown_and_foreign_workspace_references_are_rejected():
    backend, _, request = make_fixture()
    for workspace in (
        WorkspaceRef("another-backend", request.workspace.workspace_id),
        WorkspaceRef(backend.backend_id, "unknown"),
    ):
        with pytest.raises(WorkspaceError):
            backend.prepare(workspace)
    with pytest.raises(WorkspaceError):
        backend.resolve("unknown")


def test_malformed_result_fails_closed_with_safe_error():
    backend, executor, request = make_fixture(scenario="malformed")
    backend.prepare(request.workspace)
    with pytest.raises(ContractError, match="^invalid executor result$"):
        validate_result(executor.execute(request), request)


@pytest.mark.parametrize(
    "changes",
    [
        {"attempt_id": "another-attempt"},
        {"status": "unknown"},
        {"exit_code": True},
        {"exit_code": 1},
        {"finished_at": float("nan")},
        {"finished_at": 10**1000},
        {"started_at": 2000.0},
        {"artifact_hashes": ("../private",)},
        {"artifact_hashes": (content_hash("a"), content_hash("a"))},
        {"retryable": True},
        {"failure_classification": "timeout"},
        {"usage": {"input_tokens": -1}},
    ],
)
def test_result_validation_rejects_inconsistent_adapter_evidence(changes):
    backend, executor, request = make_fixture()
    backend.prepare(request.workspace)
    malformed = replace(executor.execute(request), **changes)
    with pytest.raises(ContractError, match="^invalid executor result$"):
        validate_result(malformed, request)


@pytest.mark.parametrize(
    "changes",
    [
        {"timeout_seconds": 0},
        {"timeout_seconds": True},
        {"timeout_seconds": float("inf")},
        {"instruction": " "},
        {"parent_attempt_id": "attempt-1"},
        {"environment": {"SAFE": "value"}},
        {"environment": (("SAFE", "value"), ("SAFE", "other"))},
        {"environment": (("NOT=VALID", "value"),)},
        {"environment": (("SAFE", "value\x00"),)},
    ],
)
def test_request_rejects_invalid_scope_metadata(changes):
    _, _, request = make_fixture()
    with pytest.raises(ContractError):
        replace(request, **changes)


def test_scope_uses_only_explicit_environment_and_hides_transient_fields(monkeypatch):
    monkeypatch.setenv("SYNTHETIC_HOST_SECRET", "host-only-synthetic-secret")
    _, _, request = make_fixture()
    assert request.environment == ()
    request = replace(
        request,
        instruction="synthetic-private-instruction",
        environment=(("ALLOWED", "synthetic-secret"),),
        workspace=replace(request.workspace, locator="synthetic-private-location"),
    )
    assert request.environment == (("ALLOWED", "synthetic-secret"),)
    for private in (
        "synthetic-private-instruction",
        "synthetic-secret",
        "synthetic-private-location",
        "host-only-synthetic-secret",
    ):
        assert private not in repr(request)


@pytest.mark.parametrize(
    "constructor,kwargs",
    [
        (ExecutionBudget, {"max_tokens": True}),
        (ExecutionBudget, {"max_tokens": -1}),
        (ExecutionBudget, {"max_usd": float("inf")}),
        (ExecutionUsage, {"input_tokens": -1}),
        (ExecutionUsage, {"output_tokens": False}),
        (ExecutionUsage, {"usd": float("nan")}),
    ],
)
def test_budget_and_usage_must_be_finite_nonnegative_metadata(constructor, kwargs):
    with pytest.raises(ContractError):
        constructor(**kwargs)
