# Commissioning a second node

How to take a new machine from boxed to allowed-to-do-production-work, and what
is deliberately still manual. Written for the Mac Studio arriving mid-November
2026, but nothing here is specific to that machine beyond the profile numbers.

The rule this document exists to enforce: **a node does not get work because it
is fast. It gets work because it passed a check.**

## The two profiles

`stigdev.node` ships two, and `scripts/commission_node.py` refuses to run if the
machine's measured memory disagrees with the profile you named.

| | `mobile-m4` | `studio-m5-ultra` |
|---|---|---|
| Memory | 24 GB, 8 GB reserved | 96 GB, 20 GB reserved |
| Usable | 16 GB | 76 GB |
| Logical runs | 4 | 24 |
| Metal slots, normal / hard | 1 / 1 | 2 / 4 |
| CPU / IO workers | 3 / 6 | 6 / 12 |

A consequence worth stating plainly, because it is the reason the second machine
matters: **the laptop cannot host the writer alias at all.** `text_coder` wants
28 GB and the laptop has 16 GB usable. Of the six resource classes, the laptop
admits exactly one, `text_small`. Everything else waits for the Studio.

## Day one, in order

Each step has a check that either passes or tells you what is missing. Do not
skip ahead: step 5 is the first one that can produce work anyone relies on.

### 1. Accounts before anything else

Two macOS users. `owner-admin` for setup and recovery only. `agent-runtime` for
the 24/7 services, with no administrator rights and no Apple Account signed in.
Creating the service account later means re-doing file ownership, so do it now.

### 2. Disk, encryption, time

Turn on FileVault and let it finish before loading data. Confirm network time.
Both are commissioning checks and both fail closed.

### 3. Storage tiers

Three volumes, three jobs. Point the environment at them:

```sh
export STIGDEV_CACHE_VOLUME=/Volumes/nvme-cache      # Thunderbolt NVMe: model and render cache
export STIGDEV_ARCHIVE_VOLUME=/Volumes/archive       # NAS or external HDD: masters, long-term
export STIGDEV_BACKUP_TARGET=/Volumes/backup         # encrypted, separate from the archive
```

The internal 1 TB SSD holds the control database, the active models, and recent
proxies. It does not hold masters. Cache is regenerable and expires; source
bundles, claims, manifests, masters and receipts do not.

### 4. Network posture

No public SSH, no public Screen Sharing. Reach the machine over a private
overlay network with key-based SSH. The commissioning check looks for listeners
on `*:22` and `*:5900` and fails if it finds them.

### 5. Run the check

```sh
python3 scripts/commission_node.py --profile studio-m5-ultra
python3 scripts/commission_node.py --profile studio-m5-ultra --json   # for a record
```

It prints every check, which resource classes the node would admit while idle,
and a blocker list. Exit status is 0 only when the node is ready. Two checks
need `sudo` to answer; without it they report `??` rather than passing, because
an unknown answer is not a pass.

Keep the JSON. It is the before picture when something later behaves oddly.

### 6. Prove sameness before trusting speed

Run the committed examples on the new machine and compare against the old one:

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest                     # must match the laptop exactly
.venv/bin/stigdev replay examples/sample_run   # ok: true
.venv/bin/stigdev demo --runs-root /tmp/m5demo # seed 42: 3 promoted, 5 rejected, 0.55 -> 0.86
```

Same inputs, same artifact hashes, same evidence. A faster machine that produces
different bytes is not a faster machine, it is a different machine.

### 7. Soak before cutover

Leave it under load for 72 hours. Watch memory pressure, swap growth, and
thermals — the three host facts admission already reads. Re-run the check at the
end. If pressure spends time in yellow, lower `normal_metal_slots` or raise
`reserve_memory_gb` in the profile rather than hoping.

### 8. Then, and only then, move the queue

The laptop becomes cockpit and canary; the Studio becomes the canonical worker.

## What is deliberately not automated yet

Honesty about the gap matters more than a plist that pretends.

- **There is no worker daemon.** `stigdev.scheduler` and `stigdev.ledger` have no
  production caller — they are exercised by tests only. Until a `worker` command
  exists, the Studio can run the suite, replays, demos and benchmarks, but it
  cannot lease real tasks. This is the single largest gap before the machine
  earns its keep, and it is the next thing to build.
- **One store, one machine.** The SQLite store is single-writer by design, WAL is
  unsafe over network mounts, and the v1 JSONL log now refuses to append if a
  second writer touched it. Keep the store on the Studio's internal SSD and give
  the laptop read-only copies. Do not put the store on the NAS.
- **Backups are a drill, not a feeling.** Restore from the backup target onto a
  scratch path monthly and replay an example out of the restored copy.

## Calibration notes

The numbers in `stigdev.node.RESOURCE_CLASSES` are first-benchmark safe ceilings,
not measurements. Two are already suspect and should be re-measured on the real
machine rather than trusted:

- `render_cpu` asks for 4 CPU slots while `mobile-m4` allows 3, so the laptop can
  never render. That may be correct, or the profile may be one worker too tight.
- `image_final` at 40 GB and `video_heavy` at 72 GB were chosen before any model
  was pinned. Measure peak resident size with the real pipeline and lower them.

Lower a ceiling when evidence says so. Raising one needs the same evidence.
