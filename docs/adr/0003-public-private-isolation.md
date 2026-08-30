# ADR 0003: Public/private isolation (one-way dependency)

Status: accepted (2026-08-30)

## Context

This public repository must be consumable by a private commercial system
(`social-trend-agent`) without ever exposing private code, data, prompts,
connectors, or credentials — and without the public runtime growing hidden
dependencies on the private side.

## Decision

- Dependency direction is **private -> public only**. The private system may
  `pip install` this package and implement its interfaces; nothing in this
  repository imports from, references, or assumes the private system.
- The integration surface is limited to public contracts: the `Provider`
  protocol (model adapters), the `Sandbox` protocol, the evaluator interface
  (`evaluate(store, artifact_hash, split, k) -> Evidence`), fixture JSONL
  schema, and the run-store layout. Documented in
  `docs/integration_boundary.md`.
- Only synthetic or redistributable fixtures are committed. Truth fields stay
  evaluator-side. No production connectors, scraped data, customer logs,
  ranking logic, non-public prompts, or secret-like values enter this repo.

## Consequences

- The private system can swap in its own data sources, evaluators, and paid
  providers as plugins while the public benchmark stays reproducible.
- Public CI can never require private assets; everything here runs offline.
- Any future contribution containing platform connectors or real platform data
  must be rejected regardless of usefulness (see SECURITY.md).
