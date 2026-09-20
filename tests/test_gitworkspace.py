"""GitWorktreeBackend (M5): exact-base worktrees, one-writer lease, tree checkpoints, safe disposal."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from stigdev.eventstore import SqliteEventStore, tree_digest
from stigdev.gitworkspace import GitWorktreeBackend
from stigdev.workspace import WorkspaceError, WorkspaceRef, WorkspaceSpec, validate_state


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "origin"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    (path / "a.txt").write_text("alpha\n")
    _git(path, "add", ".")
    _git(path, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "base")
    return path, _git(path, "rev-parse", "HEAD")


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def backend(repo: tuple[Path, str], tmp_path: Path, clock: Clock) -> GitWorktreeBackend:
    return GitWorktreeBackend({"origin": repo[0]}, tmp_path / "ws", holder="a", lease_ttl=100.0, clock=clock)


def _spec(repo: tuple[Path, str], workspace_id: str = "ws1") -> WorkspaceSpec:
    return WorkspaceSpec(workspace_id, "origin", repo[1])


def _record(backend: GitWorktreeBackend, workspace_id: str) -> dict:
    return json.loads((backend.root / ".meta" / f"{workspace_id}.json").read_text())


def test_create_allocates_a_worktree_branch_at_the_exact_base(backend, repo):
    ref = backend.create(_spec(repo))
    path = Path(ref.locator)
    assert ref.backend_id == "git-worktree/v1" and path.is_dir()
    assert _git(path, "rev-parse", "HEAD") == repo[1]
    assert _git(path, "rev-parse", "--abbrev-ref", "HEAD") == "stigdev/ws1"
    state = backend.inspect(ref)
    validate_state(state, ref)
    assert state.revision == repo[1] and not state.prepared and state.disposition == "active"
    record = _record(backend, "ws1")
    assert record["base_commit"] == repo[1] and record["branch"] == "stigdev/ws1"


def test_create_rejects_inexact_unknown_or_missing_base(backend, repo):
    for spec in (
        WorkspaceSpec("ws1", "origin", "main"),
        WorkspaceSpec("ws1", "origin", "0" * 40),
        WorkspaceSpec("ws1", "origin", repo[1][:12]),
        WorkspaceSpec("ws1", "origin", None),
        WorkspaceSpec("ws1", "elsewhere", repo[1]),
    ):
        with pytest.raises(WorkspaceError):
            backend.create(spec)
    assert not (backend.root / "ws1").exists()


def test_workspaces_never_share_paths_and_ids_cannot_escape_root(backend, repo):
    one = backend.create(_spec(repo, "ws1"))
    two = backend.create(_spec(repo, "ws2"))
    assert one.locator != two.locator
    assert all(Path(r.locator).resolve().is_relative_to(backend.root) for r in (one, two))
    with pytest.raises(WorkspaceError):
        backend.create(_spec(repo, "ws1"))
    with pytest.raises(WorkspaceError):
        backend.create(_spec(repo, "a/../b"))
    with pytest.raises(WorkspaceError):
        backend.resolve("a/../b")
    with pytest.raises(WorkspaceError):
        backend.resolve("unknown")


def test_lifecycle_matches_the_workspace_contract(backend, repo, tmp_path, clock):
    ref = backend.create(_spec(repo))
    prepared = backend.prepare(ref)
    validate_state(prepared, ref)
    assert prepared.prepared and prepared.disposition == "active"
    assert backend.retain(ref).disposition == "retained"
    with pytest.raises(WorkspaceError):
        backend.prepare(ref)
    disposed = backend.dispose(ref)
    validate_state(disposed, ref)
    assert disposed.disposition == "disposed" and not disposed.prepared
    assert backend.inspect(ref) == disposed
    with pytest.raises(WorkspaceError):
        backend.dispose(ref)
    with pytest.raises(WorkspaceError):
        backend.create(_spec(repo))
    with pytest.raises(WorkspaceError):
        backend.prepare(WorkspaceRef("another-backend", "ws1"))
    again = GitWorktreeBackend({"origin": repo[0]}, tmp_path / "ws", holder="a", clock=clock)
    assert again.resolve("ws1") == ref and again.inspect(ref) == disposed


def test_inspect_reports_uncommitted_content_in_the_revision(backend, repo):
    ref = backend.create(_spec(repo))
    backend.prepare(ref)
    path = Path(ref.locator)
    (path / "a.txt").write_text("beta\n")
    assert backend.inspect(ref).revision == f"{repo[1]}:{tree_digest({'a.txt': _h('beta\n')})}"
    (path / "a.txt").write_text("alpha\n")
    assert backend.inspect(ref).revision == repo[1]


def test_one_writer_lease_is_enforced_and_fences_the_previous_holder(backend, repo, tmp_path, clock):
    ref = backend.create(_spec(repo))
    backend.prepare(ref)
    other = GitWorktreeBackend({"origin": repo[0]}, tmp_path / "ws", holder="b", lease_ttl=100.0, clock=clock)
    clock.now = 50.0
    with pytest.raises(WorkspaceError):
        other.prepare(ref)
    clock.now = 150.0
    assert other.prepare(ref).prepared
    clock.now = 160.0
    store = SqliteEventStore.create(tmp_path / "s", store_id="s")
    with pytest.raises(WorkspaceError):
        backend.checkpoint(ref, store)
    with pytest.raises(WorkspaceError):
        backend.dispose(ref, discard=True)
    assert Path(ref.locator).is_dir()


def test_checkpoint_stores_a_content_addressed_tree_and_patch_digest(backend, repo, tmp_path):
    ref = backend.create(_spec(repo))
    backend.prepare(ref)
    path = Path(ref.locator)
    (path / "a.txt").write_text("beta\n")
    (path / "b.txt").write_text("new\n")
    (path / "sub").mkdir()
    (path / "sub" / "c.txt").write_text("deep\n")
    store = SqliteEventStore.create(tmp_path / "s", store_id="s")
    checkpoint = backend.checkpoint(ref, store)
    assert checkpoint.workspace_id == "ws1" and checkpoint.revision == repo[1] and checkpoint.files == 3
    expected = {"a.txt": _h("beta\n"), "b.txt": _h("new\n"), "sub/c.txt": _h("deep\n")}
    assert store.get_tree(checkpoint.tree) == expected
    assert store.get_blob(expected["b.txt"]) == b"new\n"
    diff = subprocess.run(["git", "diff", "--binary", "HEAD"], cwd=path, check=True, capture_output=True).stdout
    assert checkpoint.patch_digest == hashlib.sha256(diff).hexdigest()
    assert _record(backend, "ws1")["checkpoints"][0]["tree"] == checkpoint.tree


def test_dispose_never_silently_discards_uncheckpointed_changes(backend, repo, tmp_path):
    ref = backend.create(_spec(repo))
    backend.prepare(ref)
    path = Path(ref.locator)
    (path / "a.txt").write_text("beta\n")
    with pytest.raises(WorkspaceError):
        backend.dispose(ref)
    assert path.is_dir()
    store = SqliteEventStore.create(tmp_path / "s", store_id="s")
    backend.checkpoint(ref, store)
    assert backend.dispose(ref).disposition == "disposed"
    assert not path.exists() and _git(repo[0], "branch", "--list", "stigdev/ws1") == ""
    assert _record(backend, "ws1")["cleanup"] == {"worktree": "removed", "branch": "deleted"}
    second = backend.create(_spec(repo, "ws2"))
    backend.prepare(second)
    (Path(second.locator) / "a.txt").write_text("gamma\n")
    assert backend.dispose(second, discard=True).disposition == "disposed"
    assert not Path(second.locator).exists()


def test_quarantine_retains_the_workspace_with_a_reason(backend, repo):
    ref = backend.create(_spec(repo))
    backend.prepare(ref)
    (Path(ref.locator) / "a.txt").write_text("broken\n")
    state = backend.quarantine(ref, "tests failed")
    assert state.disposition == "retained" and Path(ref.locator).is_dir()
    assert _record(backend, "ws1")["quarantine"]["reason"] == "tests failed"
    with pytest.raises(WorkspaceError):
        backend.prepare(ref)


def test_symlink_escape_fails_closed(backend, repo, tmp_path):
    ref = backend.create(_spec(repo))
    backend.prepare(ref)
    path = Path(ref.locator)
    secret = tmp_path / "secret.txt"
    secret.write_text("hunter2\n")
    os.symlink(secret, path / "link.txt")
    store = SqliteEventStore.create(tmp_path / "s", store_id="s")
    with pytest.raises(WorkspaceError):
        backend.checkpoint(ref, store)
    assert store.blobs() == []
    with pytest.raises(WorkspaceError):
        backend.inspect(ref)
    os.unlink(path / "link.txt")
    os.symlink(tmp_path, path / "dirlink", target_is_directory=True)
    with pytest.raises(WorkspaceError):
        backend.checkpoint(ref, store)
    with pytest.raises(WorkspaceError):
        backend.dispose(ref)
    assert backend.dispose(ref, discard=True).disposition == "disposed"
