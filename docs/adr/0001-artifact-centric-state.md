# ADR 0001: Artifact-centric canonical state

Status: accepted (2026-08-30)

## Context

The thesis requires capability to accumulate across finite-lived workers with
no persistent conversational identity. State must therefore live in the
project, not in any agent.

## Decision

The unit of progress is an **executable artifact**: a complete Python module,
content-addressed by sha256 and stored immutably (`artifacts/<hash>.py`).
Canonical state is a single pointer (`canonical.json`: hash, generation,
score). All history — proposals, evidence, decisions, failures — is an
append-only JSONL event log. Workers receive a bounded *observation* projected
from the store (canonical source + score, recent failure records, budget),
never the full history and never each other's messages.

## Consequences

- Any worker (or human) can resume from disk alone; identity is disposable.
- Whole-module replacement keeps diffing/patching machinery out of the MVP;
  finer-grained edits can arrive later without changing the store contract.
- Rejected artifacts remain addressable forever as failure evidence without
  ever being reachable from the canonical pointer.
- One canonical artifact per run for now; multi-artifact projects need a
  directory-tree hash (future work, tracked in ROADMAP).
