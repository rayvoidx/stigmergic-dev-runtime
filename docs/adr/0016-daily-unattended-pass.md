# ADR 0016: One bounded, unattended improvement pass a day

Status: proposed (2026-10-25). Implemented in `scripts/daily_pass.py` with
`deploy/launchd/dev.stigmergic.daily.plist`; pending user review.

## Context

The operator's standing goal is a system that improves every day with a
person supervising rather than driving, and a public record of that work on
GitHub. On 2026-10-25 a check of what actually ran unattended found that the
media side had a daily loop (production, a 06:40 pulse, performance snapshots,
a growth agent at 09:30) while this repository had none: between 2026-10-04 and
2026-10-23 nothing moved, and the one commit that closed the gap was made by
hand. "GitHub updates itself every day" was an assumption, not a fact.

The kernel already held every part of a daily pass except the caller. ADR 0014
put Claude Code behind `AgentExecutor` on the operator's subscription with the
billing routes stripped; ADR 0006 and the M5 work made worktrees and
checkpoints ordinary; CI defines what "green" means (pytest, the seed-42 demo,
replay). What was missing was the dull loop that branches, asks, gates, and
pushes — the same shape as the worker in ADR 0014, pointed at this repository.

Two tempting versions were rejected. A pass that commits something every day
to keep a contribution graph full would be a fabricated record, which the
research invariants forbid. A pass that lets the agent commit and push itself
would put the gates inside the thing they gate.

## Decision

`scripts/daily_pass.py` runs once a day under launchd and does exactly this:

1. **Branch.** Fetch `origin/main`, add a worktree at `state/daily/<date>` on
   branch `daily/<date>`. If that directory exists the pass steps aside
   (`already_ran`): either today's run is in progress or yesterday's was left
   for a human.
2. **Ask.** Run `ClaudeCodeExecutor` in the worktree with one instruction:
   read `AGENTS.md`, `PROJECT_STATE.md`, `ROADMAP.md` and the newest ADRs,
   then make exactly one small, complete, test-backed improvement a careful
   maintainer would merge without discussion, or reply `NO_CHANGE`. The agent
   is told not to touch git. The request carries `ECC_GATEGUARD=off` because
   the operator's interactive fact-forcing hook would deny every first edit;
   the CLI runs with permission prompts off and `WebFetch`/`WebSearch`
   disallowed, inside a worktree with every gate downstream.
3. **Gate** (pure, tested): the change may not touch `.github/`, `deploy/`,
   `scripts/daily_pass.py`, `tests/test_daily_pass.py` or `docs/adr/0016-*`
   — the agent does not edit what reviews it; at most 12 files and 600 changed
   lines; no added line matches a credential pattern (Anthropic, AWS, GitHub,
   Slack, Google keys, PEM blocks, `api_key = "…"`). Any hit is `gated`.
4. **Verify** in the worktree with the repository's interpreter: pyflakes on
   the changed Python files, `pytest`, `stigdev demo`, `stigdev replay`. The
   first failure is `verify_failed`.
5. **Record.** Commit with the agent's final message as a conventional
   subject and body, a footer naming this ADR and the gates, and a
   `Co-Authored-By: Claude` trailer. Push `HEAD:main`. A non-fast-forward
   rejection is `push_rejected`; nothing is force-pushed.

### State transitions

```
started ──already_ran
   │
   ├─ agent_failed                      (CLI error, timeout, malformed envelope)
   ├─ no_change                         (NO_CHANGE, or an empty diff)
   ├─ gated ── worktree kept            (guarded path, size, secret)
   ├─ verify_failed ── worktree kept    (pyflakes, pytest, demo, replay)
   ├─ committed                         (--no-push rehearsal)
   ├─ push_rejected ── worktree kept    (main moved underneath)
   └─ pushed ── worktree removed
```

Exit code 0 for `pushed`, `committed`, `no_change`; 2 for `already_ran`;
1 for everything else, so launchd's log shows a failed day as a failure.

### Observability

Every run writes `state/daily/<date>.json`: `status`, `summary`, `branch`,
`worktree`, `files`, `insertions`, `deletions`, `gate`, `verify`, `commit`,
`pushed`, `agent` (status, exit code, classification, tokens, `usd` which is
always 0.0 on a subscription, wall seconds), `agent_text` (the agent's final
message, so a failed day can still be read) and `finished_at`. One JSON line
goes to stdout. A steward outside this repository reads the file; nothing in
this repository depends on that steward.

### Acceptance tests

`tests/test_daily_pass.py`: the gates as pure functions (guarded paths, caps,
each credential pattern, the fake key already present in the Claude Code tests
is not a hit, only added lines are scanned), commit-message shaping, the
session-variable scrub, and the whole branch-to-push path against a temporary
bare origin with a fake executor: pushed, no-change, gated, verify-failed,
`--no-push`, agent failure, and the same-day second run.

## Conflicts and limits recorded, not resolved

1. **Not a security boundary.** The agent runs with permission checks off
   inside a worktree on the operator's machine. The gates review the diff, not
   the process; a hostile agent could read the operator's files. This is the
   same standing limit as the subprocess sandbox and ADR 0014's worker, and the
   reason the pass is offline (no web tools) and bounded (one run, 30 minutes).
2. **The gates are a blocklist.** The secret patterns and guarded prefixes
   name what is known; they are widened, never narrowed, and a false positive
   costs one skipped day.
3. **Quality is the agent's, verified only by tests.** A green pass proves
   the suite still holds, not that the change was worth making. The operator
   reads the daily commit; a bad day is reverted by hand and the prompt
   tightened.
4. **One repository.** The media repositories are private and local-only;
   pointing this pass at them is a separate decision with its own boundary
   review (`docs/integration_boundary.md`).
5. **Subscription limits apply.** The pass spends the operator's plan quota,
   not money (`usd` is pinned to 0 by ADR 0014). It runs at 05:30 KST so it
   does not compete with interactive sessions.
