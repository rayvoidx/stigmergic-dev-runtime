# ADR 0012: Node profiles, resource classes, and Metal admission

Status: proposed (2026-09-28). Implemented offline in `stigdev/node.py` with
`scripts/commission_node.py` and `docs/commissioning.md`; no runtime path or
scheduler change depends on it yet.

## Context

A second machine arrives in mid-November 2026: a Mac Studio M5 Ultra, 96 GB,
intended as the 24/7 canonical worker with the existing MacBook Pro M4 Pro as
cockpit and canary. An audit of the current code found that the kernel has **no
concept of a machine at all** — no node, no host, no resource model. The nearest
things are opaque holder strings on leases and workspaces, and a `platform`
field written into the run manifest that no code reads. `Budget` measures calls,
tokens, dollars, wall seconds and workspaces; it does not measure memory or GPU.

Apple unified memory makes this harder than it looks. There is no hardware
partition equivalent to NVIDIA MIG, so a GPU-heavy job cannot be fenced off by
the driver. Two image jobs that each fit will together take the machine into
swap, and the failure mode is a slow, thermally throttled box rather than a
clean out-of-memory error.

## Decision

Model the machine as a declared ceiling plus a measured mood, and decide
admission from both.

- **`ResourceClass`** — what one kind of job costs: fractional Metal slots,
  memory, CPU slots, and the flags `exclusive`, `preemptible`, `max_parallel`.
  Six are shipped, from `text_small` to `video_heavy`.
- **`NodeProfile`** — one machine's ceilings: total and reserved memory, logical
  run limit, normal and hard Metal slots, CPU and IO workers, and an interactive
  reserve so the operator is never locked out by background work. `mobile-m4`
  and `studio-m5-ultra` ship as constants.
- **`HostFacts`** — what the caller measured right now: memory pressure, swap
  growth rate, free disk, thermal throttling.
- **`admit(profile, allocation, requested, facts)`** — returns a `GateDecision`
  listing every unmet condition rather than the first. Unknown class raises.

The normal Metal ceiling governs steady work; preemptible and exclusive classes
are measured against the hard ceiling instead, because the first can be evicted
and the second holds the node alone. Memory pressure above green, swap growth
above 64 MB/min, or thermal throttling stops *new* leases and never kills a
running one.

`commissioning_gate` is the same idea for the machine as a whole: FileVault, no
public remote access, backup target, cache and archive volumes, network time, a
non-admin service account, disk headroom, and the ability to host the writer
alias at all.

Policy is pure and testable offline. All host measurement lives in
`scripts/commission_node.py`, which is read-only and macOS-specific.

## Consequences

- The laptop's real capability is now stated rather than assumed: of six
  resource classes it admits exactly one. `text_coder` needs 28 GB and the
  laptop has 16 GB usable. This is the concrete reason the second machine is
  needed, and it is asserted by a test.
- The commissioning script refuses to run a profile whose declared memory
  disagrees with the machine's measured memory, so the Studio cannot silently
  be commissioned as the laptop.
- Checks that need `sudo` report unknown rather than passing. An unknown answer
  is not a pass.
- Writing the script surfaced a bug in its own first draft: the swap metric
  measured standing usage rather than growth, which refused every resource class
  on a healthy laptop with old swap. The field is a rate now, sampled twice.

## What this does not do

`admit` is not wired into `Scheduler`. The seam is
`Scheduler.acquire_next`, whose `state.leased >= budget.max_concurrency` check
is the current admission control, and `TaskLedger.acquire`, whose
`lease_acquired` payload is where a node id belongs. Wiring them is deliberately
a separate change, because the prerequisite is a worker daemon and none exists:
`Scheduler` and `TaskLedger` have no production caller today.

Ordered follow-ups, in the sequence that makes the Studio useful:

1. A `worker` command that loops recover → acquire → execute → finish. Without
   it the Studio can run tests, replays and benchmarks but cannot take work.
2. A node id — `socket.gethostname()` — carried as the lease holder and added to
   the execution event identity.
3. A clock the ledger derives from the database rather than the caller, so two
   machines cannot steal leases from each other through drift.
4. Memory as a scheduler dimension, then `admit` at the acquire seam.

## Alternatives considered

- **A memory dimension in `Budget` alone.** `Budget.cap()` resolves dimensions
  by attribute name, so adding one is mechanical — but a budget is per-run and
  a machine's ceiling is per-node. Two runs sharing a machine would each think
  they had the whole thing.
- **Measuring inside the kernel.** Calling `sysctl` and `memory_pressure` from
  `stigdev` would make the package macOS-only and untestable offline, and this
  repository's tests may not touch the host that way.
