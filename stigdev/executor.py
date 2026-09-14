"""Typed coding-agent execution boundary, separate from model ``Provider``.

Instructions, the complete explicitly supplied environment, workspace locators,
and stdout/stderr are transient. Never serialize these dataclasses wholesale
into a public event. There is no inherited host environment. The workspace,
environment, timeout and budget describe the attempt's scope; general tool,
network and credential capabilities require later enforcement mechanisms.

These synchronous contracts do not supervise processes, enforce paid budgets,
or contain untrusted code. Executors must honor their timeout; a caller can
reject late results but cannot forcibly interrupt an arbitrary Python call.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Literal, Protocol

from .workspace import WorkspaceRef, valid_identifier

ExecutionStatus = Literal["success", "failed", "timed_out", "cancelled", "interrupted"]
FailureClassification = Literal[
    "none",
    "nonzero_exit",
    "timeout",
    "cancelled",
    "malformed_result",
    "workspace_preparation",
    "workspace_inspection",
    "executor_error",
    "interrupted",
]


class ContractError(ValueError):
    """An execution request/result violates the public contract."""


def _nonnegative_number(value: object) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


@dataclass(frozen=True)
class ExecutionBudget:
    """Attempt metadata only; not reservation, payment authority or enforcement."""

    max_tokens: int | None = None
    max_usd: float = 0.0

    def __post_init__(self) -> None:
        if (
            self.max_tokens is not None and not _nonnegative_int(self.max_tokens)
        ) or not _nonnegative_number(self.max_usd):
            raise ContractError("invalid execution budget")


@dataclass(frozen=True)
class ExecutionUsage:
    """Executor-reported evidence, not independently verified accounting."""

    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0

    def __post_init__(self) -> None:
        if (
            not _nonnegative_int(self.input_tokens)
            or not _nonnegative_int(self.output_tokens)
            or not _nonnegative_number(self.usd)
        ):
            raise ContractError("invalid execution usage")


@dataclass(frozen=True)
class ExecutionRequest:
    run_id: str
    task_id: str
    attempt_id: str
    executor_id: str
    workspace: WorkspaceRef
    instruction: str = field(repr=False)
    environment: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    timeout_seconds: float = 60.0
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)
    parent_attempt_id: str | None = None

    def __post_init__(self) -> None:
        validate_request(self)


@dataclass(frozen=True)
class ExecutionResult:
    """Untrusted adapter outcome, validated by ``validate_result`` before use.

    Timestamps are finite nonnegative UNIX seconds. ``started_at=None`` means
    the executor was never invoked or its start was not durably observed.
    Revisions are backend-defined immutable identities. Artifact hashes refer
    to existing RunStore objects; generic file/blob ingestion is not provided.
    Raw output remains transient even when it contains secrets.
    """

    attempt_id: str
    workspace: WorkspaceRef
    status: ExecutionStatus
    started_at: float | None
    finished_at: float
    exit_code: int | None = None
    stdout: str = field(default="", repr=False)
    stderr: str = field(default="", repr=False)
    artifact_hashes: tuple[str, ...] = ()
    revision_before: str | None = None
    revision_after: str | None = None
    failure_classification: FailureClassification = "none"
    retryable: bool = False
    usage: ExecutionUsage | None = None


def validate_request(request: object) -> None:
    """Validate request metadata without including rejected values in errors."""
    if not isinstance(request, ExecutionRequest):
        raise ContractError("invalid execution request")
    if any(
        not valid_identifier(value)
        for value in (
            request.run_id,
            request.task_id,
            request.attempt_id,
            request.executor_id,
        )
    ):
        raise ContractError("invalid execution request")
    if (
        not isinstance(request.workspace, WorkspaceRef)
        or not isinstance(request.instruction, str)
        or not request.instruction.strip()
        or not _nonnegative_number(request.timeout_seconds)
        or request.timeout_seconds == 0
        or not isinstance(request.budget, ExecutionBudget)
        or (
            request.budget.max_tokens is not None
            and not _nonnegative_int(request.budget.max_tokens)
        )
        or not _nonnegative_number(request.budget.max_usd)
        or (
            request.parent_attempt_id is not None
            and (
                not valid_identifier(request.parent_attempt_id)
                or request.parent_attempt_id == request.attempt_id
            )
        )
    ):
        raise ContractError("invalid execution request")
    if not isinstance(request.environment, tuple):
        raise ContractError("invalid execution environment")
    names = set()
    for pair in request.environment:
        if (
            not isinstance(pair, tuple)
            or len(pair) != 2
            or not isinstance(pair[0], str)
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", pair[0]) is None
            or not isinstance(pair[1], str)
            or "\x00" in pair[1]
            or pair[0] in names
        ):
            raise ContractError("invalid execution environment")
        names.add(pair[0])


def validate_result(result: object, request: ExecutionRequest) -> None:
    """Fail closed on malformed, foreign, or inconsistent executor outcomes."""
    if not isinstance(result, ExecutionResult):
        raise ContractError("invalid executor result")
    if (
        result.attempt_id != request.attempt_id
        or not isinstance(result.workspace, WorkspaceRef)
        or result.workspace != request.workspace
        or result.status not in ("success", "failed", "timed_out", "cancelled", "interrupted")
        or not _nonnegative_number(result.finished_at)
        or (
            result.started_at is not None
            and (
                not _nonnegative_number(result.started_at) or result.finished_at < result.started_at
            )
        )
        or (result.exit_code is not None and type(result.exit_code) is not int)
        or not isinstance(result.stdout, str)
        or not isinstance(result.stderr, str)
        or type(result.retryable) is not bool
        or not isinstance(result.artifact_hashes, tuple)
        or any(
            not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            for digest in result.artifact_hashes
        )
        or len(set(result.artifact_hashes)) != len(result.artifact_hashes)
        or any(
            revision is not None and not valid_identifier(revision)
            for revision in (result.revision_before, result.revision_after)
        )
        or (result.usage is not None and not isinstance(result.usage, ExecutionUsage))
        or (
            result.usage is not None
            and (
                not _nonnegative_int(result.usage.input_tokens)
                or not _nonnegative_int(result.usage.output_tokens)
                or not _nonnegative_number(result.usage.usd)
            )
        )
    ):
        raise ContractError("invalid executor result")
    allowed_failures = {
        "success": ("none",),
        "failed": (
            "nonzero_exit",
            "malformed_result",
            "workspace_preparation",
            "workspace_inspection",
            "executor_error",
        ),
        "timed_out": ("timeout",),
        "cancelled": ("cancelled",),
        "interrupted": ("interrupted",),
    }
    if (
        result.failure_classification not in allowed_failures[result.status]
        or (
            result.status == "success"
            and (result.exit_code not in (None, 0) or result.retryable or result.started_at is None)
        )
        or (
            result.failure_classification == "nonzero_exit"
            and (result.exit_code is None or result.exit_code == 0 or result.started_at is None)
        )
        or (result.status in ("timed_out", "cancelled", "interrupted") and result.exit_code == 0)
    ):
        raise ContractError("invalid executor result")


class AgentExecutor(Protocol):
    """Execute one assigned attempt; never schedule, promote, or publish it."""

    executor_id: str

    def execute(self, request: ExecutionRequest) -> ExecutionResult: ...
