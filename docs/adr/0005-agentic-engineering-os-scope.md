# ADR 0005: Agentic Engineering OS scope and repository boundary

Status: accepted for the design baseline and offline execution-contract phase
(2026-09-14). Operational implementation decisions remain deferred below.

## Context

`stigmergic-dev-runtime` is already a public research runtime with an auditable
artifact/evaluator/promotion loop, TrendEvoBench v1/v2, three implemented
comparison conditions, provider replacement, ablations, and committed H5 2×2
data. It is not an empty product shell.

The next design question is whether to rename or replace it with a new
`stigmergic-agentic-os` repository, and whether coding agents such as Codex,
Claude Code, or OpenCode should be represented by the existing `Provider`
protocol. Doing either now would conflate the research lineage with an
unimplemented control plane.

## Decision

### Keep this repository and package

Keep the repository name `stigmergic-dev-runtime` and package name `stigdev`.
Describe this repository externally as:

> The research kernel of a human-governed Agentic Engineering OS.

The original research thesis remains primary and intact: persistent projects,
ephemeral agents. The OS framing extends the application boundary; it does not
retroactively turn exploratory research results into platform claims.

### Keep research and operational scopes explicit

This repository may contain:

- the public research runtime and synthetic benchmarks;
- generic, offline-testable contracts needed to study the OS architecture;
- reproducible comparison conditions, event schemas, and reference backends;
- documentation and ADRs for future control-plane extraction.

It does not currently contain a deployable multi-repository control plane.
Hermes, Slack, Orca, Codex, Claude Code, and OpenCode are integration targets,
not present runtime capabilities.

### Separate the contracts

The OS design uses distinct abstractions:

- `Provider` performs model-level inference and returns a model response.
- `AgentExecutor` launches and supervises a coding-agent process that may use
  tools and modify an assigned workspace.
- `WorkspaceBackend` allocates, checkpoints, and releases a repository,
  worktree, container, or remote workspace.
- `Scheduler` advances a durable task graph under dependency, concurrency,
  retry, and budget constraints.
- `Evaluator` produces evidence without deciding promotion.
- `PolicyGate` makes versioned promotion and human-approval decisions.
- `RunStore` owns events, artifacts, lineage, checkpoints, and recovery.
- `GatewayAdapter` translates authenticated external input into commands and
  projects status back out; it does not mutate canonical state directly.

CLI coding agents must not be forced into `Provider`. They own process and tool
lifecycle, have workspace side effects, and need permission and checkpoint
contracts that a text-in/text-out provider does not.

### Keep the public/private dependency one-way

The private `social-trend-agent` repository may depend on published `stigdev`
contracts. This public repository must not import private application code,
data, prompts, connectors, credentials, or ranking logic.

Hermes/Slack adapters containing organization-specific routing, secrets, or
operational policy live in a private consumer or a future control-plane
repository. Only generic adapter protocols and synthetic fakes belong here.

### Delay control-plane repository extraction

Do not create a new control-plane repository during design. Extract one only
when at least two of the following are true:

1. it has an independent deployment or release cadence;
2. it coordinates more than one application repository;
3. it requires operational dependencies or credentials inappropriate for the
   public research kernel;
4. it owns durable scheduling/gateway APIs used without the benchmark runtime;
5. its security boundary or license differs from this repository.

The expected split at that point is:

```text
stigmergic-dev-runtime                public research kernel
agentic-engineering-control-plane    gateways, scheduler, repository manager
social-trend-agent                   private application/testbed
```

### Design before implementation

The 2026-09-14 user direction authorizes completion of this design baseline
followed by the previously specified execution-contract task. That scope covers
typed `AgentExecutor` and `WorkspaceBackend` contracts, deterministic test
doubles, and a narrow execution-evidence entry point backed by `RunStore`.
It does not authorize third-stage integrations. Each implementation milestone
receives its own worktree and acceptance tests.

The first contract phase uses the existing single-writer file-backed store.
New execution records use namespaced event types and an additive contract
version inside the current flat envelope; existing events and published runs
are not migrated. The new entry point records attempts without promoting
canonical state or changing Provider experiments. Recovery inspects recorded
outcomes and marks interrupted attempts; it never silently reruns an executor.
Typed budgets are metadata in this phase, not a paid-execution reservation
system. Real process supervision, leases, heartbeats, and strong isolation
remain later milestones.

## Consequences

### Positive

- Research history, experiment provenance, and package consumers remain on one
  lineage.
- Research conditions and operational orchestration cannot silently collapse
  into the same abstraction.
- A later repository split follows deployment and security evidence rather
  than a speculative product name.
- External tools remain replaceable adapters around a durable, auditable core.

### Costs and risks

- Documentation must label current, proposed, and private components carefully.
- The repository may temporarily contain both research and generic OS contracts;
  maintainers must reject product-specific dependencies.
- File-based `RunStore` evolution needs backward compatibility for committed
  runs before a control plane can rely on it.
- Human approval, strong workspace isolation, and concurrency control remain
  future work, so the design must not be marketed as a production OS.

## Alternatives considered

### Create `stigmergic-agentic-os` now

Rejected for now. It would split code and research history before an
independently deployable control plane exists.

### Put CLI coding agents behind `Provider`

Rejected. A provider returns inference output; a coding agent executes a tool
loop with workspace, process, credential, and permission side effects.

### Put all integrations in this public repository

Rejected. Production gateway and application integrations would violate ADR
0003 and make offline public CI depend on private infrastructure.

### Let gateways write directly to workspaces or canonical state

Rejected. It bypasses event provenance, policy gates, idempotency, and human
governance.

## Decisions deferred beyond the contract phase

Before the affected operational milestone, reviewers must decide:

1. whether the first scheduler is single-process/file-backed or begins with a
   transactional database;
2. the event-schema v1 compatibility and migration policy;
3. the minimum strong-isolation backend required before untrusted agents run;
4. which actions require human approval by default;
5. the concrete trigger that moves operational adapters into a separate
   control-plane repository.

Decisions 1 and 2 are addressed by ADR 0006 (proposed 2026-09-20).
