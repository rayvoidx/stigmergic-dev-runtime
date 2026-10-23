# ADR 0014: The laptop bridge — worker loop and a subscription Claude Code executor

Status: proposed (2026-09-29). Implemented offline in `stigdev/workerd.py`,
`stigdev/claudecode.py`, the `stigdev worker` command, and
`deploy/launchd/dev.stigmergic.worker.plist`; pending user review.

## Context

The Mac Studio is about seven weeks out. Until it lands the operator wants
unattended operation on the MacBook Pro M4 (24 GB), with open-source models
carrying as much as possible and Claude Code carrying the parts that need
strong reasoning — explicitly **on the subscription, not the API**.

Three facts shaped the design.

**The laptop is small, and the repository already knew it.** `MOBILE_M4`
reserves 8 GB of 24, leaving 16 GB usable against one Metal slot. Of the six
resource classes in ADR 0012, exactly two can ever run there:

| Class | Memory | Fits on the laptop |
|---|---:|---|
| `text_small` | 10 GB | yes |
| `render_cpu` | 12 GB | yes |
| `text_coder` | 28 GB | no |
| `vision` | 30 GB | no |
| `image_final` | 40 GB | no |
| `video_heavy` | 72 GB | no |

So "open source to the maximum" on this machine means one small text model
plus CPU rendering. Local image generation, vision and video are not
constrained-but-slow here; they are impossible, and they wait for the Studio.

**Nothing ran unattended, because nothing called the scheduler.** ADR 0006's
`TaskLedger` and the M7 `Scheduler` were complete and had no production
caller. That was gap 10's first item and the actual blocker for 24/7.

**Claude Code is not a model endpoint.** ADR 0005 separates `Provider` (model
inference) from `AgentExecutor` (a coding agent working in a workspace), and
`AGENTS.md` says not to force CLI coding agents into `Provider`. Claude Code
belongs behind `AgentExecutor`. That also keeps the local-first rule intact:
the rule bans commercial inference APIs on the 24/7 path, and a subscription
CLI is not one — provided it stays a subscription CLI.

## Decision

### `stigdev/claudecode.py` — `ClaudeCodeExecutor`

Implements the `AgentExecutor` protocol by running
`claude -p <instruction> --output-format json` in the workspace directory,
with an injected `runner` so tests never touch the real binary (the rule the
Ollama adapter already follows).

Two invariants carry the operator's "이건 api아님" requirement into code:

1. **No billing route reaches the subprocess.** `BILLING_ROUTE_VARS` lists
   every variable that moves Claude Code onto metered billing. As of 2.1.261
   that was seven names: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`,
   `ANTHROPIC_BASE_URL`, `ANTHROPIC_BEDROCK_BASE_URL`,
   `ANTHROPIC_VERTEX_BASE_URL`, `CLAUDE_CODE_USE_BEDROCK`,
   `CLAUDE_CODE_USE_VERTEX`. Re-pinned to 2.1.310 on 2026-10-23 from the
   names the installed binary carries, it is twenty: the same seven plus
   Mantle (`CLAUDE_CODE_USE_MANTLE`, `ANTHROPIC_BEDROCK_MANTLE_BASE_URL`),
   "Anthropic on AWS" (`CLAUDE_CODE_USE_ANTHROPIC_AWS`,
   `ANTHROPIC_AWS_API_KEY`, `ANTHROPIC_AWS_BASE_URL`), "Anthropic on Google
   Cloud" (`CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD`,
   `ANTHROPIC_GOOGLE_CLOUD_BASE_URL`), Microsoft Foundry
   (`CLAUDE_CODE_USE_FOUNDRY`, `ANTHROPIC_FOUNDRY_API_KEY`,
   `ANTHROPIC_FOUNDRY_AUTH_TOKEN`, `ANTHROPIC_FOUNDRY_BASE_URL`,
   `ANTHROPIC_FOUNDRY_RESOURCE`) and the gateway switch
   (`CLAUDE_CODE_USE_GATEWAY`). Ambient ones are stripped; a request that
   *sets* one is refused before anything launches. The set is deliberately
   wide: a false positive costs one refused run, a false negative costs money
   and breaks the local-first rule.
2. **Subscription usage is never money.** The CLI reports an API-equivalent
   `total_cost_usd`. Recording it as `ExecutionUsage.usd` would tell every
   budget that reads that field that cash moved when none did, so `usd` is
   fixed at `SUBSCRIPTION_USD = 0.0` and tokens are passed through. The
   estimate stays in stdout for a human.

Outcomes map onto the existing vocabulary: unreadable JSON is
`malformed_result` (fail closed whatever the exit code), a non-zero exit is
`nonzero_exit`, an `is_error` envelope with exit 0 is `executor_error`, a
missing binary is `executor_error` and not retryable, a timeout is `timeout`
and retryable.

### `stigdev/workerd.py` — `WorkerLoop`

The first production caller of `Scheduler`. Deliberately dull: it owns no
policy, decides no retries, reserves no budget. One tick is
`recover → admit → acquire → execute → finish`.

Two rules it does own:

- **Admission precedes the lease.** Asking the machine before the queue means
  a hot laptop leaves tasks `pending` instead of stranding them `leased`. A
  class the node can never host fails at construction, not mid-run.
- **Every exit path finishes.** An adapter that raises is a failed attempt,
  not a dead worker holding a lease the ledger cannot see until it expires.

`task_payload` validates the work spec at submission, so a malformed task is
caught by whoever submits it rather than by a worker at three in the morning.
`Scheduler.submit` gained an optional `payload` stored under a namespaced
`work` key so a work spec can never shadow the scheduling fields.

### `stigdev worker` and the launchd agent

`stigdev worker <store> --run-id <id>` runs the loop; `--once` drains and
exits, which is what manual checks use. The launchd agent keeps it alive, runs
it at `Background` QoS with `Nice 5` so the operator's own editor and Claude
Code session stay responsive, and logs to `state/logs/`.

Host facts come from `scripts/commission_node.py`. If that import fails the
worker reports red memory pressure rather than inventing a calm machine, so an
unmeasurable host takes no work.

## Conflicts and limits recorded, not resolved

1. **`BILLING_ROUTE_VARS` is a blocklist, not a proof.** It is pinned to one
   Claude Code version (2.1.261 at acceptance, 2.1.310 since 2026-10-23). A
   future release could add a new route and this executor would not know;
   between those two pins that happened thirteen times, which is why the pin
   is re-read from the installed binary rather than from memory. The
   compensating control is that the list is asserted by test and that `usd`
   is hard-zero, so an escape would show up as unexpected billing, not as
   silently accepted spend.
2. **Nothing verifies the subscription positively.** The executor proves the
   absence of known API routes; it cannot prove the presence of a valid
   subscription login. A logged-out CLI fails as `executor_error`.
3. **No workspace backend is wired in.** The loop takes the workspace from the
   task payload. Pointing it at `GitWorktreeBackend` is separate work, and
   until then the submitter is trusted to name a real directory.
4. **Concurrency is one.** The loop leases one task at a time. On 16 GB
   usable that is the honest ceiling; `max_concurrency` stays 1.
5. **The 7-week bridge is not a plan for the Studio.** Everything here assumes
   the small profile. The `text_coder`, `vision`, `image_final` and
   `video_heavy` classes remain unreachable until the Studio arrives.
6. **`ProcessType Background` is a request, not a guarantee.** macOS may still
   schedule the agent against interactive work; `node.admit` backing off on
   yellow or red pressure is the real protection.

## Failure behavior

`ClaudeCodeError` and `WorkerLoopError` are refusals to launch, never an
agent's own failure. Every task outcome goes through `Scheduler.finish`
exactly once. An unmeasurable host stops the worker rather than letting it
guess.

## Observability

No new event types. Attempt outcomes are already scheduler and ledger events.
The loop records only outcome metadata (`exit_code`,
`failure_classification`, `revision_after`) because raw agent output can carry
secrets.

## Acceptance tests

`tests/test_claudecode.py` (19 cases): the API key never reaches the
subprocess, every billing variable is stripped, a request asking for one is
refused before launch, subscription usage is not money, headless invocation in
the workspace, model passthrough, and each outcome mapping.

`tests/test_worker_loop.py` (12 cases): a leased task reaches the executor and
is finished, the request carries the lease identity, an idle queue is not an
error, a throwing adapter still finishes the lease, `run_until_idle` drains and
refuses to spin, a task without a work spec fails the task rather than the
worker, a machine under memory pressure takes no work and leaves it pending, a
calm machine admits, and the laptop refuses `text_coder` at construction.

## Deferred

Wiring `GitWorktreeBackend` into the loop, a node id carried as the lease
holder in the execution event identity, a ledger clock derived from the
database rather than the caller, memory as a scheduler dimension, additional
executors (Codex CLI, OpenCode), and everything that needs the Studio's larger
resource classes.
