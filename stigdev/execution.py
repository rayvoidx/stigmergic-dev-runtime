"""Opt-in execution evidence over RunStore, independent of Provider experiments.

Single writer only. No task selection, promotion, process supervision, or cleanup.
Replay projects complete recorded events; recovery never invokes an executor.
Instructions, environments, workspace locators and raw logs are never serialized.
"""

from __future__ import annotations

import math
import time
from dataclasses import replace
from typing import Any

from .executor import (
    AgentExecutor,
    ContractError,
    ExecutionBudget,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    ExecutionUsage,
    FailureClassification,
    validate_request,
    validate_result,
)
from .store import RunStore, StoreIntegrityError
from .workspace import WorkspaceBackend, WorkspaceRef, valid_identifier, validate_state

EXECUTION_VERSION = 1
_TERMINAL: dict[ExecutionStatus, str] = {
    "success": "execution_completed",
    "failed": "execution_failed",
    "timed_out": "execution_timed_out",
    "cancelled": "execution_cancelled",
    "interrupted": "execution_interrupted",
}
_IDENTITY = (
    "run_id",
    "task_id",
    "attempt_id",
    "executor_id",
    "backend_id",
    "workspace_id",
    "parent_attempt_id",
)
_EVENTS = {"execution_requested", "workspace_prepared", "execution_started", *_TERMINAL.values()}
_OMITTED = "[output omitted]"


class ExecutionIntegrityError(StoreIntegrityError):
    """Execution evidence is inconsistent; do not run or recover through it."""


def _workspace(ref: WorkspaceRef) -> WorkspaceRef:
    return WorkspaceRef(backend_id=ref.backend_id, workspace_id=ref.workspace_id)


def _identity(request: ExecutionRequest) -> dict[str, Any]:
    return {
        "run_id": request.run_id,
        "task_id": request.task_id,
        "attempt_id": request.attempt_id,
        "executor_id": request.executor_id,
        "backend_id": request.workspace.backend_id,
        "workspace_id": request.workspace.workspace_id,
        "parent_attempt_id": request.parent_attempt_id,
    }


def _public_strings(value: Any, request: ExecutionRequest) -> None:
    """Conservatively reject known transient values in free-form public metadata.

    This is defense in depth, not a secret detector. Callers must supply public
    opaque IDs/revisions and reviewed artifacts. Values shorter than eight
    characters match whole fields only, so CI=1/LANG=C remain usable. Embedded
    short values and encoded secrets are not detected.
    """
    forbidden = [request.instruction, request.workspace.locator]
    forbidden.extend(value for _, value in request.environment)
    if isinstance(value, str):
        if any(
            secret and (secret == value or (len(secret) >= 8 and secret in value))
            for secret in forbidden
        ):
            raise ContractError("sensitive execution metadata")
    elif isinstance(value, dict):
        for entry in value.values():
            _public_strings(entry, request)
    elif isinstance(value, (tuple, list)):
        for entry in value:
            _public_strings(entry, request)


def _safe_result(result: ExecutionResult) -> ExecutionResult:
    return replace(
        result,
        workspace=_workspace(result.workspace),
        stdout=_OMITTED if result.stdout else "",
        stderr=_OMITTED if result.stderr else "",
    )


def _result_dict(result: ExecutionResult) -> dict[str, Any]:
    # Never asdict an executor-supplied object: only explicit validated fields.
    return {
        "attempt_id": result.attempt_id,
        "workspace": {
            "backend_id": result.workspace.backend_id,
            "workspace_id": result.workspace.workspace_id,
        },
        "status": result.status,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "exit_code": result.exit_code,
        "stdout": _OMITTED if result.stdout else "",
        "stderr": _OMITTED if result.stderr else "",
        "artifact_hashes": list(result.artifact_hashes),
        "revision_before": result.revision_before,
        "revision_after": result.revision_after,
        "failure_classification": result.failure_classification,
        "retryable": result.retryable,
        "usage": (
            None
            if result.usage is None
            else {
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "usd": result.usage.usd,
            }
        ),
    }


def _record_request(record: dict[str, Any]) -> ExecutionRequest:
    return ExecutionRequest(
        run_id=record["run_id"],
        task_id=record["task_id"],
        attempt_id=record["attempt_id"],
        executor_id=record["executor_id"],
        workspace=WorkspaceRef(record["backend_id"], record["workspace_id"]),
        instruction="[not recorded]",
        timeout_seconds=record["timeout_seconds"],
        budget=ExecutionBudget(**record["budget"]),
        parent_attempt_id=record["parent_attempt_id"],
    )


def _read_result(raw: dict[str, Any], request: ExecutionRequest) -> ExecutionResult:
    data = dict(raw)
    data["workspace"] = WorkspaceRef(**data["workspace"])
    data["artifact_hashes"] = tuple(data["artifact_hashes"])
    if data["usage"] is not None:
        data["usage"] = ExecutionUsage(**data["usage"])
    result = ExecutionResult(**data)
    validate_result(result, request)
    if raw != _result_dict(result):
        raise ExecutionIntegrityError("invalid execution result projection")
    return result


def inspect_executions(store: RunStore) -> list[dict[str, Any]]:
    """Validate and project execution events without repeating any side effects.

    Works with execution-only stores and benchmark stores. Verifies referenced
    .py artifact bytes; it does not re-run a coding agent or attest Git revisions.
    Unknown versions and illegal transitions fail closed.
    """
    records: dict[str, dict[str, Any]] = {}
    last_sequence = 0
    try:
        manifest = store.manifest() if store.manifest_path.exists() else None
        for event in store.events():
            seq = event["seq"]
            if type(seq) is not int or seq <= last_sequence:
                raise ExecutionIntegrityError("invalid event sequence")
            last_sequence = seq
            if "execution_version" not in event:
                if event["type"] in _EVENTS:
                    raise ExecutionIntegrityError("execution version missing")
                continue
            kind = event["type"]
            if (
                type(event["execution_version"]) is not int
                or event["execution_version"] != EXECUTION_VERSION
                or kind not in _EVENTS
            ):
                raise ExecutionIntegrityError("unsupported execution event")
            if (
                type(event["ts"]) not in (float, int)
                or not math.isfinite(event["ts"])
                or event["ts"] < 0
            ):
                raise ExecutionIntegrityError("invalid execution timestamp")
            identity = {key: event[key] for key in _IDENTITY}
            attempt_id = identity["attempt_id"]
            if kind == "execution_requested":
                if attempt_id in records or event["caused_by_seq"] is not None:
                    raise ExecutionIntegrityError("duplicate execution request")
                record = {
                    **identity,
                    "status": "requested",
                    "result": None,
                    "event_seqs": [seq],
                    "request_seq": seq,
                    "last_seq": seq,
                    "timeout_seconds": event["timeout_seconds"],
                    "budget": event["budget"],
                    "revision_before": None,
                    "started_at": None,
                }
                validate_request(_record_request(record))
                if manifest is not None and manifest.get("run_id") != record["run_id"]:
                    raise ExecutionIntegrityError("execution run identity mismatch")
                if records and any(r["run_id"] != record["run_id"] for r in records.values()):
                    raise ExecutionIntegrityError("mixed execution run identities")
                parent_id = record["parent_attempt_id"]
                if parent_id is not None:
                    parent = records.get(parent_id)
                    if (
                        parent is None
                        or parent["result"] is None
                        or (parent["run_id"], parent["task_id"])
                        != (record["run_id"], record["task_id"])
                    ):
                        raise ExecutionIntegrityError("invalid execution lineage")
                records[attempt_id] = record
                continue
            record = records[attempt_id]
            if (
                identity != {key: record[key] for key in _IDENTITY}
                or event["request_seq"] != record["request_seq"]
                or event["caused_by_seq"] != record["last_seq"]
                or record["result"] is not None
            ):
                raise ExecutionIntegrityError("broken execution lineage or ordering")
            if kind == "workspace_prepared":
                if record["status"] != "requested":
                    raise ExecutionIntegrityError("workspace prepared out of order")
                if event["revision"] is not None and not valid_identifier(event["revision"]):
                    raise ExecutionIntegrityError("invalid workspace revision")
                record["revision_before"] = event["revision"]
                record["status"] = "prepared"
            elif kind == "execution_started":
                if record["status"] != "prepared":
                    raise ExecutionIntegrityError("execution started out of order")
                record["started_at"] = event["ts"]
                record["status"] = "running"
            else:
                result = _read_result(event["result"], _record_request(record))
                if (
                    _TERMINAL[result.status] != kind
                    or result.revision_before != record["revision_before"]
                ):
                    raise ExecutionIntegrityError("execution terminal evidence mismatch")
                if (
                    record["status"] != "running"
                    and result.status != "interrupted"
                    and not (
                        record["status"] == "requested"
                        and result.failure_classification == "workspace_preparation"
                    )
                ):
                    raise ExecutionIntegrityError("execution terminal out of order")
                if record["status"] != "running" and result.started_at is not None:
                    raise ExecutionIntegrityError("unstarted execution has start time")
                if record["status"] == "running" and result.started_at is None:
                    raise ExecutionIntegrityError("started execution has no start time")
                if result.status == "success" and (
                    result.started_at is None
                    or result.finished_at - result.started_at > record["timeout_seconds"]
                ):
                    raise ExecutionIntegrityError("successful execution exceeded deadline")
                for digest in result.artifact_hashes:
                    store.get_artifact(digest)
                record["status"] = result.status
                record["result"] = _result_dict(result)
            record["event_seqs"].append(seq)
            record["last_seq"] = seq
    except ExecutionIntegrityError:
        raise
    except (ValueError, TypeError, KeyError, OSError, OverflowError, StoreIntegrityError):
        raise ExecutionIntegrityError("invalid execution evidence") from None
    return list(records.values())


def _failed(
    request: ExecutionRequest,
    classification: FailureClassification,
    started_at: float | None,
    before: str | None = None,
    after: str | None = None,
) -> ExecutionResult:
    status: ExecutionStatus = (
        "timed_out"
        if classification == "timeout"
        else "interrupted" if classification == "interrupted" else "failed"
    )
    return ExecutionResult(
        attempt_id=request.attempt_id,
        workspace=_workspace(request.workspace),
        status=status,
        started_at=started_at,
        finished_at=time.time(),
        revision_before=before,
        revision_after=after,
        failure_classification=classification,
        retryable=False,
    )


def execute_agent(
    store: RunStore,
    request: ExecutionRequest,
    executor: AgentExecutor,
    workspace_backend: WorkspaceBackend,
) -> ExecutionResult:
    """Record one already selected attempt; preserve canonical state.

    The caller allocates/resolves the workspace. Budgets describe intent, not
    reservations. The adapter must honor timeout_seconds; checking a returned
    result cannot stop arbitrary blocking Python code. Failures preserve the
    workspace for caller inspection, retention, or explicit disposal.
    """
    validate_request(request)
    if (
        executor.executor_id != request.executor_id
        or workspace_backend.backend_id != request.workspace.backend_id
    ):
        raise ContractError("execution adapter identity mismatch")
    identity = _identity(request)
    _public_strings(identity, request)
    previous = inspect_executions(store)
    if any(r["attempt_id"] == request.attempt_id for r in previous):
        raise ContractError("attempt already recorded; use a new attempt id")
    if any(r["run_id"] != request.run_id for r in previous):
        raise ContractError("execution run identity mismatch")
    if any(
        r["result"] is None
        and (r["backend_id"], r["workspace_id"])
        == (request.workspace.backend_id, request.workspace.workspace_id)
        for r in previous
    ):
        raise ContractError("workspace has an unresolved execution")
    if request.parent_attempt_id is not None:
        parents = [r for r in previous if r["attempt_id"] == request.parent_attempt_id]
        if not parents or parents[0]["result"] is None or parents[0]["task_id"] != request.task_id:
            raise ContractError("invalid execution parent")
    if store.manifest_path.exists() and store.manifest().get("run_id") != request.run_id:
        raise ContractError("execution run identity mismatch")
    first = store.append_event(
        "execution_requested",
        execution_version=EXECUTION_VERSION,
        **identity,
        timeout_seconds=request.timeout_seconds,
        budget={"max_tokens": request.budget.max_tokens, "max_usd": request.budget.max_usd},
        caused_by_seq=None,
    )
    last_seq = first["seq"]

    def append(kind: str, **payload: Any) -> None:
        nonlocal last_seq
        event = store.append_event(
            kind,
            execution_version=EXECUTION_VERSION,
            **identity,
            request_seq=first["seq"],
            caused_by_seq=last_seq,
            **payload,
        )
        last_seq = event["seq"]

    def finish(result: ExecutionResult) -> ExecutionResult:
        safe = _safe_result(result)
        validate_result(safe, request)
        append(_TERMINAL[safe.status], result=_result_dict(safe))
        return safe

    try:
        prepared = workspace_backend.prepare(request.workspace)
        validate_state(prepared, request.workspace)
        inspected = workspace_backend.inspect(request.workspace)
        validate_state(inspected, request.workspace)
        if (
            not prepared.prepared
            or not inspected.prepared
            or prepared.disposition != "active"
            or inspected.disposition != "active"
            or prepared.revision != inspected.revision
        ):
            raise ContractError("workspace is not prepared")
        _public_strings(inspected.revision, request)
    except Exception:
        return finish(_failed(request, "workspace_preparation", None))
    before = inspected.revision
    append("workspace_prepared", revision=before)
    append("execution_started")
    started_at = time.time()
    clock_start = time.monotonic()
    try:
        raw_result = executor.execute(request)
    except TimeoutError:
        raw_result = _failed(request, "timeout", started_at, before)
    except Exception:
        raw_result = _failed(request, "executor_error", started_at, before)
    # BaseException (process interruption) deliberately leaves an open attempt.
    elapsed = time.monotonic() - clock_start
    try:
        inspected = workspace_backend.inspect(request.workspace)
        validate_state(inspected, request.workspace)
        if not inspected.prepared or inspected.disposition != "active":
            raise ContractError("workspace changed lifecycle during execution")
        _public_strings(inspected.revision, request)
        after = inspected.revision
    except Exception:
        return finish(_failed(request, "workspace_inspection", started_at, before))
    try:
        validate_result(raw_result, request)
        if raw_result.started_at is None:
            raise ContractError("executor start time missing")
        if raw_result.revision_before != before or (
            raw_result.revision_after is not None and raw_result.revision_after != after
        ):
            raise ContractError("workspace revision mismatch")
        if raw_result.status == "success" and raw_result.revision_after != after:
            raise ContractError("missing workspace revision")
        _public_strings(
            (raw_result.revision_before, raw_result.revision_after, raw_result.artifact_hashes),
            request,
        )
        for digest in raw_result.artifact_hashes:
            _public_strings(store.get_artifact(digest), request)
        result = replace(raw_result, revision_after=after)
        if elapsed > request.timeout_seconds or (
            result.started_at is not None
            and result.finished_at - result.started_at > request.timeout_seconds
        ):
            result = _failed(request, "timeout", started_at, before, after)
    except Exception:
        result = _failed(request, "malformed_result", started_at, before, after)
    return finish(result)


def recover_executions(store: RunStore) -> list[dict[str, Any]]:
    """Mark interrupted attempts with unknown outcomes; never rerun or dispose.

    Call only after the former writer is stopped. No lease/fencing system is
    implemented. Unknown outcomes are not automatically retryable; explicit
    retries must use a new attempt ID and reference their parent attempt.
    """
    for record in inspect_executions(store):
        if record["result"] is not None:
            continue
        result = _failed(
            _record_request(record),
            "interrupted",
            record["started_at"],
            record["revision_before"],
        )
        store.append_event(
            "execution_interrupted",
            execution_version=EXECUTION_VERSION,
            **{key: record[key] for key in _IDENTITY},
            request_seq=record["request_seq"],
            caused_by_seq=record["last_seq"],
            result=_result_dict(result),
        )
    return inspect_executions(store)
