"""Workspace lifecycle contract; no filesystem or production backend.

Identity is backend-owned and independent of location. ``locator`` is transient
and must not be copied into public execution evidence. IDs and revisions are
caller-supplied public metadata, never credentials or private repository URLs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal, Protocol


def valid_identifier(value: object) -> bool:
    """Check a bounded opaque identifier, not a filesystem path or a secret."""
    return (
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", value) is not None
    )


@dataclass(frozen=True)
class WorkspaceRef:
    backend_id: str
    workspace_id: str
    locator: str | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not valid_identifier(self.backend_id) or not valid_identifier(self.workspace_id):
            raise ValueError("invalid workspace identity")
        if self.locator is not None and not isinstance(self.locator, str):
            raise ValueError("invalid workspace locator")


@dataclass(frozen=True)
class WorkspaceSpec:
    """Backend-resolved repository identity and optional immutable base revision."""

    workspace_id: str
    repository_id: str
    base_revision: str | None = None

    def __post_init__(self) -> None:
        if not valid_identifier(self.workspace_id) or not valid_identifier(self.repository_id):
            raise ValueError("invalid workspace specification")
        if self.base_revision is not None and not valid_identifier(self.base_revision):
            raise ValueError("invalid workspace base revision")


@dataclass(frozen=True)
class WorkspaceState:
    workspace: WorkspaceRef
    revision: str | None
    prepared: bool = False
    disposition: Literal["active", "retained", "disposed"] = "active"


class WorkspaceError(RuntimeError):
    """A backend could not complete or verify a lifecycle operation."""


def validate_state(state: object, workspace: WorkspaceRef) -> None:
    """Reject malformed/foreign backend state without echoing backend content."""
    if (
        not isinstance(state, WorkspaceState)
        or not isinstance(state.workspace, WorkspaceRef)
        or state.workspace != workspace
        or (state.revision is not None and not valid_identifier(state.revision))
        or type(state.prepared) is not bool
        or state.disposition not in ("active", "retained", "disposed")
        or (state.disposition == "disposed" and state.prepared)
    ):
        raise WorkspaceError("invalid workspace state")


class WorkspaceBackend(Protocol):
    """Own allocation and lifecycle, never task selection or agent execution.

    ``prepare`` must establish readiness, and ``inspect`` must report the
    observed revision independently of executor claims. Retention/disposal are
    explicit caller decisions. Backend-specific setup and cleanup policy belongs
    in the backend configuration. General checkpoint storage remains deferred.
    """

    backend_id: str

    def create(self, spec: WorkspaceSpec) -> WorkspaceRef: ...

    def resolve(self, workspace_id: str) -> WorkspaceRef: ...

    def prepare(self, workspace: WorkspaceRef) -> WorkspaceState: ...

    def inspect(self, workspace: WorkspaceRef) -> WorkspaceState: ...

    def retain(self, workspace: WorkspaceRef) -> WorkspaceState: ...

    def dispose(self, workspace: WorkspaceRef) -> WorkspaceState: ...
