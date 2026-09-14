"""Deterministic test doubles, never production agent/workspace adapters.

No subprocess, filesystem workspace, environment lookup, model or network call
is performed. State and revisions exist only in memory; reopening a RunStore
recovers evidence, not these workspaces. Configured artifacts must already be
stored by the test in its RunStore.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Literal, cast

from .executor import (
    ContractError,
    ExecutionRequest,
    ExecutionResult,
    ExecutionUsage,
    validate_request,
)
from .model import content_hash
from .workspace import (
    WorkspaceError,
    WorkspaceRef,
    WorkspaceSpec,
    WorkspaceState,
    valid_identifier,
)


class FakeWorkspaceBackend:
    """In-memory lifecycle fixture with deterministic revision identities."""

    backend_id = "fake-workspace/v1"

    def __init__(self, *, fail_prepare: bool = False):
        self.fail_prepare = fail_prepare
        self._states: dict[str, WorkspaceState] = {}

    def create(self, spec: WorkspaceSpec) -> WorkspaceRef:
        if not isinstance(spec, WorkspaceSpec) or spec.workspace_id in self._states:
            raise WorkspaceError("workspace allocation failed")
        workspace = WorkspaceRef(self.backend_id, spec.workspace_id)
        revision = spec.base_revision or content_hash("fake-base:" + spec.repository_id)
        self._states[spec.workspace_id] = WorkspaceState(workspace, revision)
        return workspace

    def resolve(self, workspace_id: str) -> WorkspaceRef:
        if not valid_identifier(workspace_id) or workspace_id not in self._states:
            raise WorkspaceError("workspace resolution failed")
        return self._states[workspace_id].workspace

    def inspect(self, workspace: WorkspaceRef) -> WorkspaceState:
        if not isinstance(workspace, WorkspaceRef) or workspace.backend_id != self.backend_id:
            raise WorkspaceError("workspace inspection failed")
        state = self._states.get(workspace.workspace_id)
        if state is None or state.workspace != workspace:
            raise WorkspaceError("workspace inspection failed")
        return state

    def prepare(self, workspace: WorkspaceRef) -> WorkspaceState:
        state = self.inspect(workspace)
        if self.fail_prepare or state.disposition != "active":
            raise WorkspaceError("workspace preparation failed")
        return self._set(replace(state, prepared=True))

    def retain(self, workspace: WorkspaceRef) -> WorkspaceState:
        state = self.inspect(workspace)
        if state.disposition == "disposed":
            raise WorkspaceError("workspace retention failed")
        return self._set(replace(state, disposition="retained"))

    def dispose(self, workspace: WorkspaceRef) -> WorkspaceState:
        state = self.inspect(workspace)
        return self._set(replace(state, disposition="disposed", prepared=False))

    def record_revision(self, workspace: WorkspaceRef, revision: str) -> WorkspaceState:
        """Test-only simulated edit; not part of ``WorkspaceBackend``."""
        state = self.inspect(workspace)
        if not state.prepared or state.disposition != "active" or not valid_identifier(revision):
            raise WorkspaceError("workspace revision update failed")
        return self._set(replace(state, revision=revision))

    def _set(self, state: WorkspaceState) -> WorkspaceState:
        self._states[state.workspace.workspace_id] = state
        return state


class DeterministicFakeExecutor:
    """Scripted success/failure fixture; no external or installed agent is used.

    Repeated fresh fixtures produce identical results. Success changes only
    the fake backend revision. ``timeout`` returns immediately with a terminal
    deadline outcome, while ``malformed`` deliberately violates the Protocol.
    This is evidence of lifecycle behavior, not real process supervision.
    """

    executor_id = "fake-executor/v1"

    def __init__(
        self,
        backend: FakeWorkspaceBackend,
        scenario: Literal[
            "success", "nonzero_exit", "timeout", "cancelled", "malformed", "raise_error"
        ] = "success",
        *,
        artifact_hashes: tuple[str, ...] = (),
        stdout: str = "",
        stderr: str = "",
        started_at: float = 1000.0,
        duration: float = 1.0,
    ):
        if scenario not in (
            "success",
            "nonzero_exit",
            "timeout",
            "cancelled",
            "malformed",
            "raise_error",
        ):
            raise ValueError("invalid fake executor scenario")
        self.backend = backend
        self.scenario = scenario
        self.artifact_hashes = artifact_hashes
        self.stdout = stdout
        self.stderr = stderr
        self.started_at = started_at
        self.duration = duration
        self.calls = 0

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        validate_request(request)
        if request.executor_id != self.executor_id:
            raise ContractError("executor identity mismatch")
        state = self.backend.inspect(request.workspace)
        if not state.prepared or state.disposition != "active":
            raise WorkspaceError("workspace is not ready for execution")
        self.calls += 1
        if self.scenario == "raise_error":
            raise RuntimeError("simulated executor error")
        if self.scenario == "malformed":
            return cast(ExecutionResult, {"status": "success"})
        result = ExecutionResult(
            attempt_id=request.attempt_id,
            workspace=request.workspace,
            status="success",
            started_at=self.started_at,
            finished_at=self.started_at + self.duration,
            exit_code=0,
            stdout=self.stdout,
            stderr=self.stderr,
            revision_before=state.revision,
            revision_after=state.revision,
            usage=ExecutionUsage(),
        )
        if self.scenario == "timeout" or self.duration > request.timeout_seconds:
            return replace(
                result,
                status="timed_out",
                exit_code=None,
                finished_at=self.started_at + request.timeout_seconds,
                failure_classification="timeout",
                retryable=True,
            )
        if self.scenario == "nonzero_exit":
            return replace(
                result, status="failed", exit_code=1, failure_classification="nonzero_exit"
            )
        if self.scenario == "cancelled":
            return replace(
                result, status="cancelled", exit_code=None, failure_classification="cancelled"
            )
        revision = content_hash(f"fake-edit:{state.revision}:{request.attempt_id}")
        self.backend.record_revision(request.workspace, revision)
        return replace(result, artifact_hashes=self.artifact_hashes, revision_after=revision)
