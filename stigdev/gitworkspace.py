"""GitWorktreeBackend: the M4 ``WorkspaceBackend`` contract on local Git worktrees (M5).

Each workspace is a worktree of a registered local repository, allocated at an
exact commit on its own ``stigdev/<workspace_id>`` branch under one root. A
JSON record per workspace (``<root>/.meta/<id>.json``) carries base commit,
branch, lease, checkpoints, quarantine reason, and cleanup outcome, so a new
backend instance can resolve workspaces after a restart.

Not a security boundary: a worktree separates files, not processes, network,
or credentials. The one-writer lease is a file-locked record enforced by this
backend only; the scheduler's ledger lease stays authoritative.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from .eventstore import SqliteEventStore, tree_digest
from .workspace import WorkspaceError, WorkspaceRef, WorkspaceSpec, WorkspaceState, valid_identifier

BACKEND_ID = "git-worktree/v1"
_SHA = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class Checkpoint:
    workspace_id: str
    revision: str  # HEAD commit at checkpoint time
    tree: str  # content-addressed tree digest stored in the event store
    patch_digest: str  # sha256 of ``git diff --binary HEAD``
    files: int


def _git(cwd: Path, *args: str, binary: bool = False) -> Any:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    completed = subprocess.run(["git", *args], cwd=cwd, capture_output=True, env=env)
    if completed.returncode != 0:
        raise WorkspaceError(f"git {args[0]} failed: {completed.stderr.decode('utf-8', 'replace').strip()}")
    return completed.stdout if binary else completed.stdout.decode("utf-8").strip()


class GitWorktreeBackend:
    backend_id = BACKEND_ID

    def __init__(
        self,
        repositories: dict[str, Path],
        root: Path,
        *,
        holder: str,
        lease_ttl: float = 900.0,
        clock: Callable[[], float] = time.time,
    ):
        if not valid_identifier(holder):
            raise ValueError("invalid lease holder")
        self.repositories = {key: Path(value).resolve() for key, value in repositories.items()}
        self.root = Path(root).resolve()
        self._meta = self.root / ".meta"
        self._meta.mkdir(parents=True, exist_ok=True)
        self.holder = holder
        self.lease_ttl = float(lease_ttl)
        self._clock = clock

    # -- contract ----------------------------------------------------------

    def create(self, spec: WorkspaceSpec) -> WorkspaceRef:
        if not isinstance(spec, WorkspaceSpec):
            raise WorkspaceError("workspace allocation failed")
        repository = self.repositories.get(spec.repository_id)
        if repository is None:
            raise WorkspaceError(f"unknown repository: {spec.repository_id}")
        base = spec.base_revision
        if base is None or not _SHA.fullmatch(base):
            raise WorkspaceError("base revision must be an exact 40-hex commit")
        if _git(repository, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}") != base:
            raise WorkspaceError("base revision not found in repository")
        record_path = self._record_path(spec.workspace_id)
        path = self.root / spec.workspace_id
        branch = f"stigdev/{spec.workspace_id}"
        with self._locked(spec.workspace_id):
            if record_path.exists() or path.exists():
                raise WorkspaceError(f"workspace already exists: {spec.workspace_id}")
            _git(repository, "worktree", "add", "-b", branch, str(path), base)
            self._write(
                {
                    "workspace_id": spec.workspace_id,
                    "repository_id": spec.repository_id,
                    "repository": str(repository),
                    "path": str(path),
                    "branch": branch,
                    "base_commit": base,
                    "revision": base,
                    "prepared": False,
                    "disposition": "active",
                    "lease": None,
                    "checkpoints": [],
                    "quarantine": None,
                    "cleanup": None,
                    "created_at": self._clock(),
                }
            )
        return WorkspaceRef(self.backend_id, spec.workspace_id, str(path))

    def resolve(self, workspace_id: str) -> WorkspaceRef:
        record = self._read(workspace_id)
        return WorkspaceRef(self.backend_id, record["workspace_id"], record["path"])

    def inspect(self, workspace: WorkspaceRef) -> WorkspaceState:
        record = self._record(workspace)
        if record["disposition"] != "disposed":
            record["revision"] = self._observe(record)
        return self._state(record)

    def prepare(self, workspace: WorkspaceRef) -> WorkspaceState:
        with self._locked(workspace.workspace_id):
            record = self._record(workspace)
            if record["disposition"] != "active":
                raise WorkspaceError(f"workspace is {record['disposition']}")
            self._acquire(record)
            if not Path(record["path"]).is_dir():
                raise WorkspaceError("worktree directory missing")
            record["revision"] = self._observe(record)
            record["prepared"] = True
            self._write(record)
        return self._state(record)

    def retain(self, workspace: WorkspaceRef) -> WorkspaceState:
        return self._retain(workspace, None)

    def quarantine(self, workspace: WorkspaceRef, reason: str) -> WorkspaceState:
        """Retain a failed workspace as evidence, with the reason on record."""
        return self._retain(workspace, {"reason": str(reason), "at": self._clock()})

    def checkpoint(self, workspace: WorkspaceRef, store: SqliteEventStore) -> Checkpoint:
        """Store every file as a blob plus a content-addressed tree (ADR 0006)."""
        with self._locked(workspace.workspace_id):
            record = self._record(workspace)
            if record["disposition"] == "disposed":
                raise WorkspaceError("workspace is disposed")
            self._acquire(record)
            path = Path(record["path"])
            files = self._files(path)
            entries = {rel: hashlib.sha256(data).hexdigest() for rel, data in files.items()}
            patch = _git(path, "diff", "--binary", "HEAD", binary=True)
            with store.transaction():
                for data in files.values():
                    store.put_blob(data)
                tree = store.put_tree(entries)
            if tree != tree_digest(entries):
                raise WorkspaceError("stored tree digest does not match local digest")
            checkpoint = Checkpoint(
                workspace.workspace_id,
                _git(path, "rev-parse", "HEAD"),
                tree,
                hashlib.sha256(patch).hexdigest(),
                len(files),
            )
            record["checkpoints"].append(
                {
                    "tree": tree,
                    "revision": checkpoint.revision,
                    "patch_digest": checkpoint.patch_digest,
                    "files": checkpoint.files,
                    "at": self._clock(),
                }
            )
            self._write(record)
        return checkpoint

    def dispose(self, workspace: WorkspaceRef, *, discard: bool = False) -> WorkspaceState:
        """Remove the worktree and branch; refuses uncheckpointed changes unless ``discard``."""
        with self._locked(workspace.workspace_id):
            record = self._record(workspace)
            if record["disposition"] == "disposed":
                raise WorkspaceError("workspace already disposed")
            self._acquire(record)
            path = Path(record["path"])
            cleanup: dict[str, str] = {}
            if path.exists():
                if not discard and _git(path, "status", "--porcelain"):
                    entries = {rel: hashlib.sha256(d).hexdigest() for rel, d in self._files(path).items()}
                    last = record["checkpoints"][-1]["tree"] if record["checkpoints"] else None
                    if tree_digest(entries) != last:
                        raise WorkspaceError(
                            "workspace has changes not captured by a checkpoint; "
                            "checkpoint, quarantine, or dispose(discard=True)"
                        )
                _git(Path(record["repository"]), "worktree", "remove", "--force", str(path))
                cleanup["worktree"] = "removed"
            else:
                _git(Path(record["repository"]), "worktree", "prune")
                cleanup["worktree"] = "missing"
            _git(Path(record["repository"]), "branch", "-D", record["branch"])
            cleanup["branch"] = "deleted"
            record.update(disposition="disposed", prepared=False, lease=None, cleanup=cleanup)
            self._write(record)
        return self._state(record)

    # -- internals ---------------------------------------------------------

    def _retain(self, workspace: WorkspaceRef, quarantine: dict[str, Any] | None) -> WorkspaceState:
        with self._locked(workspace.workspace_id):
            record = self._record(workspace)
            if record["disposition"] == "disposed":
                raise WorkspaceError("workspace is disposed")
            record["disposition"] = "retained"
            if quarantine is not None:
                record["quarantine"] = quarantine
            self._write(record)
        return self._state(record)

    def _acquire(self, record: dict[str, Any]) -> None:
        now = self._clock()
        lease = record.get("lease")
        if lease and lease["holder"] != self.holder and lease["expires_at"] > now:
            raise WorkspaceError(f"workspace leased by {lease['holder']} until {lease['expires_at']}")
        record["lease"] = {
            "holder": self.holder,
            "acquired_at": lease["acquired_at"] if lease and lease["holder"] == self.holder else now,
            "expires_at": now + self.lease_ttl,
        }

    def _observe(self, record: dict[str, Any]) -> str:
        path = Path(record["path"])
        head = _git(path, "rev-parse", "HEAD")
        if not _git(path, "status", "--porcelain"):
            return head
        entries = {rel: hashlib.sha256(d).hexdigest() for rel, d in self._files(path).items()}
        return f"{head}:{tree_digest(entries)}"

    def _files(self, path: Path) -> dict[str, bytes]:
        """All regular files under the worktree except .git; symlinks fail closed."""
        # ponytail: reads every file on each observation; hash-cache if worktrees grow large
        root = path.resolve()
        files: dict[str, bytes] = {}
        for current, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = sorted(d for d in dirnames if d != ".git")
            filenames = sorted(f for f in filenames if f != ".git")  # linked worktrees keep a .git file
            for name in dirnames + filenames:
                full = Path(current) / name
                if full.is_symlink():
                    raise WorkspaceError(f"symlink in workspace: {full.relative_to(root)}")
            for name in filenames:
                full = Path(current) / name
                if not full.is_file() or not full.resolve().is_relative_to(root):
                    raise WorkspaceError(f"unsafe path in workspace: {full.relative_to(root)}")
                files[full.relative_to(root).as_posix()] = full.read_bytes()
        return files

    def _record(self, workspace: WorkspaceRef) -> dict[str, Any]:
        if not isinstance(workspace, WorkspaceRef) or workspace.backend_id != self.backend_id:
            raise WorkspaceError("foreign workspace reference")
        return self._read(workspace.workspace_id)

    def _record_path(self, workspace_id: str) -> Path:
        if not valid_identifier(workspace_id) or "/" in workspace_id or ".." in workspace_id:
            raise WorkspaceError("workspace id is not a safe path segment")
        return self._meta / f"{workspace_id}.json"

    def _read(self, workspace_id: str) -> dict[str, Any]:
        path = self._record_path(workspace_id)
        if not path.exists():
            raise WorkspaceError(f"unknown workspace: {workspace_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, record: dict[str, Any]) -> None:
        path = self._record_path(record["workspace_id"])
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    @contextmanager
    def _locked(self, workspace_id: str) -> Iterator[None]:
        lock_path = self._record_path(workspace_id).with_suffix(".lock")
        with lock_path.open("a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _state(self, record: dict[str, Any]) -> WorkspaceState:
        workspace = WorkspaceRef(self.backend_id, record["workspace_id"], record["path"])
        return WorkspaceState(workspace, record["revision"], record["prepared"], record["disposition"])
