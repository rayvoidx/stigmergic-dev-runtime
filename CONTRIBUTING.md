# Contributing

Small, verifiable changes. The repository must stay runnable offline from a
fresh checkout with zero paid calls.

## Setup and checks

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest          # must pass (all tests, offline)
.venv/bin/stigdev demo --runs-root /tmp/stigdev-check --run-id smoke
```

## Rules

- Stdlib-only runtime; new runtime dependencies need an ADR.
- No network access in tests or the demo. No model API calls anywhere in CI.
- Determinism is a contract: evaluator metrics may not contain timings,
  artifact code may not use randomized `hash()`, sort orders must be total.
- Version everything that affects scores: evaluators, policies, fixtures.
  Changing scoring means a new version id, never an in-place edit.
- Never commit: platform connectors, scraped or customer data, credentials,
  secret-like strings, non-public prompts (see SECURITY.md and ADR 0003).
- Regenerating fixtures (`benchmarks/trendevobench/generate_fixtures.py`)
  changes recorded hashes — bump the fixture version directory instead of
  overwriting v1.
- Update PROJECT_STATE.md (state + decision log) with any milestone-level
  change; update the sample run in `examples/` if demo output changes.

## Tests

Every behavior change needs a test that fails without it. E2E invariants for
the seed-42 demo live in `tests/test_e2e.py`; if you intentionally change the
landscape, update those numbers in the same commit and say why.
