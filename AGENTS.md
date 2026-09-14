# AGENTS.md

## Repository purpose

This repository is the public, reproducible research kernel of a
human-governed Agentic Engineering OS.

Its primary research thesis is:

> Persistent projects, ephemeral agents.

Finite-lived workers coordinate through immutable executable artifacts,
lineage, evaluator evidence, and failure records rather than persistent
conversational identity.

## Source of truth

Before modifying the repository, read:

1. `README.md`
2. `PROJECT_STATE.md`
3. `ROADMAP.md`
4. `docs/research_protocol.md`
5. `docs/integration_boundary.md`
6. Relevant ADRs
7. For OS work, `docs/agentic_engineering_os_architecture.md` and
   `docs/implementation_plan.md`

When these documents disagree, inspect the implementation, tests, committed
experiment data, and Git history. Do not silently choose one document.

## Research invariants

- Never claim results that are not supported by committed experiment data.
- Distinguish mechanism demonstrations, exploratory findings, and
  confirmatory results.
- Preserve matched budgets across experimental conditions.
- Tests must never call live models, paid APIs, or external networks.
- Offline deterministic results are not model-capability evidence.
- Record model IDs, prompts, seeds, budgets, fixture hashes, evaluator
  versions, policy versions, and environment metadata.
- Do not modify hypotheses after observing confirmatory results without
  documenting the change.
- Treat negative and non-significant results as valid findings.

## Runtime invariants

- Artifacts are immutable and content-addressed.
- The append-only event log is the source of truth.
- Canonical state must be recoverable from recorded events.
- Failed candidates must not contaminate canonical state.
- Unimplemented conditions must fail closed.
- Replay must re-derive evaluator evidence.
- New behavior requires tests.
- The current subprocess sandbox is not a security boundary.

## Public/private boundary

Never commit:

- Production credentials or API keys
- Private prompts
- Scraped production data
- Customer data
- Commercial ranking logic
- Private service connectors
- Company code or company infrastructure details

Private applications may depend on this runtime. This public runtime must
never depend on a private application.

## Agentic Engineering OS boundary

Keep the following abstractions separate:

- `Provider`: model-level inference
- `AgentExecutor`: Claude Code, Codex, OpenCode, or other coding-agent execution
- `WorkspaceBackend`: repository, Git worktree, container, or remote workspace
- `Scheduler`: task ordering, concurrency, retry, and budget allocation
- `Evaluator`: evidence and quality measurement
- `PolicyGate`: promotion, approval, security, and deployment decisions
- `RunStore`: artifacts, events, lineage, checkpoints, and recovery
- `GatewayAdapter`: Slack, Hermes, CLI, or web control-plane input

Do not force CLI coding agents into the existing `Provider` abstraction.

## Development workflow

Before implementation:

1. Write or update an ADR.
2. Define interfaces and state transitions.
3. Specify failure behavior.
4. Specify observability events.
5. Define acceptance tests.
6. Receive design approval before broad implementation.

After implementation:

1. Run the full test suite.
2. Run replay checks.
3. Update `PROJECT_STATE.md`.
4. Update `ROADMAP.md`.
5. Update affected research documentation.
6. Report limitations and unverified assumptions.

## Verification

Use a per-worktree virtual environment:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```

Do not run paid experiments or modify production systems without explicit user
approval.
