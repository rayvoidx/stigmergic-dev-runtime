# GitWorktreeBackend (M5)

Status: implemented and verified offline on 2026-09-20. 188 tests pass (10 new).
`stigdev.gitworkspace.GitWorktreeBackend` implements the M4 `WorkspaceBackend`
contract (`docs/execution_contracts.md`) on local Git worktrees and produces
the content-addressed tree checkpoints fixed in ADR 0006.

**Worktrees are not a security boundary.** A worktree separates files, not
processes, network, or credentials. Untrusted agents still need the isolation
backend chosen under ADR 0005 deferred decision 3 before they run in one.

## Public interface

| Call | Behavior |
|---|---|
| `GitWorktreeBackend(repositories, root, holder=, lease_ttl=900, clock=time.time)` | `repositories` maps `repository_id` to a local Git repository path; every workspace lives under `root/<workspace_id>`; `holder` names this writer for the lease |
| `create(WorkspaceSpec)` | `base_revision` must be an exact 40-hex commit present in the repository; allocates `git worktree add -b stigdev/<id> <root>/<id> <sha>`; refuses an existing id or path |
| `resolve(workspace_id)` | reads the workspace record; works from a new backend instance |
| `prepare(ref)` | acquires the lease, verifies the worktree, marks prepared; only `active` workspaces |
| `inspect(ref)` | observed revision: `HEAD` when clean, `HEAD:<tree digest>` when the worktree has uncommitted or untracked changes |
| `retain(ref)` / `quarantine(ref, reason)` | keep the worktree on disk as evidence; quarantine records the reason |
| `checkpoint(ref, store) -> Checkpoint` | stores every file as a blob and a content-addressed tree in a `SqliteEventStore`; returns tree digest, `HEAD`, `git diff --binary HEAD` digest, and file count |
| `dispose(ref, discard=False)` | removes worktree and branch; refuses changes not captured by the last checkpoint unless `discard=True`; records the cleanup outcome |

Records live in `root/.meta/<workspace_id>.json`: repository, path, branch,
base commit, last observed revision, prepared flag, disposition, lease,
checkpoints, quarantine, cleanup. Writes go through a per-workspace
`flock` and an atomic replace.

## One-writer lease

Every mutating call (`prepare`, `checkpoint`, `quarantine`, `retain`, `dispose`)
acquires or renews a lease for the backend's `holder` with `lease_ttl`
seconds from `clock()`. A call from another holder while the lease is
unexpired raises `WorkspaceError`; after expiry the other holder takes the
lease and the previous holder's later calls are fenced out. Read-only
`inspect`/`resolve` never take the lease.

## Fail-closed paths

- workspace ids containing `/` or `..` are rejected even though the generic
  identifier grammar allows them;
- any symlink inside the worktree (file or directory) makes `inspect`,
  `checkpoint`, and non-discarding `dispose` raise;
- files resolving outside the worktree root are rejected;
- the `.git` link file of a linked worktree is never part of a checkpoint.

## Limits

- Not a security boundary (above). No process, network, or credential control.
- Observation hashes every file on each `inspect`; large worktrees need a
  hash cache before this backend serves them.
- The lease is file-based and host-local; the scheduler's ledger lease (M6)
  remains the authoritative fencing token for attempts.
- Checkpoints store file contents only; modes, empty directories, and
  submodules are not captured.
- No agent executor uses this backend yet; OpenCode/Codex adapters are M9.
- Requires a `git` executable on the host.
