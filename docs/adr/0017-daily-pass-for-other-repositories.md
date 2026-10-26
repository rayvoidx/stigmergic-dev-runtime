# ADR 0017: The daily pass runs on the operator's other repositories through flags

Status: proposed (2026-10-26). Implemented in `scripts/daily_pass.py`; the
targets themselves live outside this repository.

## Context

ADR 0016 limited the daily pass to this repository and named a second one "a
separate decision with its own boundary review". On 2026-10-26 the operator
made that decision: every part of the system — the media pipeline, the app
service and this kernel — should get one bounded, test-gated improvement pass
a day, applied to GitHub where a remote exists and to the machine that runs
the code either way.

The pass already had every piece but the knobs. What differed per repository
was small and enumerable: the instruction, the checks that define green, the
paths the agent must not edit, where the worktree and the report may live,
whether there is a remote at all, and what to restart afterwards. Copying the
script per repository would have copied its gates and its bugs.

## Decision

`scripts/daily_pass.py` stays one script with one `run_pass`. Flags make it
repository-agnostic; without them it behaves exactly as ADR 0016 describes.

- `--prompt FILE` replaces the instruction. Only `{python}`, `{max_files}` and
  `{max_lines}` are filled in, by replacement, so a prompt may hold braces.
- `--verify CMD` (repeatable) replaces the default pyflakes/pytest/demo/replay
  with the repository's own checks, run as shell commands in the worktree in
  order; the first failure is `verify_failed`. The secret scan, the size cap
  and the path blocklist still run before them and cannot be replaced.
- `--guard PREFIX` (repeatable) widens the blocklist; it never narrows it.
- `--state DIR` keeps the worktree and `<date>.json` outside the repository,
  for a checkout whose status an operator reads by hand.
- `--base REF` and `--branch NAME` default to `origin/main` and `main`; a
  repository without a remote starts from its own `main`.
- `--merge` fast-forwards the repository's checked-out branch to the commit
  after a green pass, so the machine runs what GitHub holds. Only a
  fast-forward of the branch that is checked out: another branch, a detached
  head or local edits in the way become `merge_note`, never a reset. With a
  push the status stays `pushed` and the note is a finding; without one
  (`--no-push --merge`, the remote-less case) success is `merged` and failure
  `merge_failed` with the worktree kept.
- `--after CMD` runs once in the repository after `pushed` or `merged`, for
  restarting whatever serves the code; its exit code and tail are recorded.

The private operations layer owns the targets: which repositories, with which
prompts, checks and restarts, in which order, under which launchd label. None
of that is in this repository (`docs/integration_boundary.md`), and this
repository's own daily run needs none of the flags.

### State transitions added to ADR 0016

```
committed ──(--merge, no remote)──► merged        worktree removed, --after runs
          └─(--merge, cannot ff)──► merge_failed  worktree kept
pushed ───(--merge)──► pushed + merged=true, or pushed + merge_note
```

Exit codes: `merged` joins the zero set; `merge_failed` is a failure.

### Acceptance tests

`tests/test_daily_pass.py`: a repository's own checks run in the worktree and
the first failure blocks the push; a remote-less repository merges into its
own `main`, runs `--after` and removes the worktree; push then merge brings
the local checkout to the pushed commit; a merge the checkout cannot take
(dirty file, other branch) is a note after a push and `merge_failed` without
one; extra guards, prompt placeholders and the gate footer; base selection
by remote presence.

## Conflicts and limits recorded, not resolved

1. **Every limit of ADR 0016 holds per target.** Not a security boundary; a
   blocklist; green proves the checks, not the worth; subscription quota, now
   spent up to three times a morning, in sequence so two agents never share
   the CPU.
2. **A pushed change can deploy.** A target whose `main` is wired to a host
   deploys the agent's commit unattended. That is the operator's choice per
   target, taken knowing the gates equal the target's CI and nothing more; one
   flag (`--branch dev`) turns it into a reviewed change instead.
3. **`--verify` runs the operator's shell.** The commands come from the
   private runner, not from the agent, and the agent cannot edit the runner
   (it is outside the worktree and the repository). A target's checks that
   need the network (a package install) make the verify step online even
   though the agent stays offline.
