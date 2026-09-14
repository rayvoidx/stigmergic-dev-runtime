# Security and privacy notes

## What executes where

Evolved artifacts are untrusted code. The runtime never imports them
in-process; execution goes through the `Sandbox` boundary
(`stigdev/sandbox.py`). The shipped `SubprocessSandbox` provides **process
isolation only**: a separate CPython in `-I` mode, a wall-clock timeout, and a
temporary working directory. It does **not** restrict filesystem or network
access. Do not run artifacts from untrusted sources with it; a stronger
sandbox (container/seccomp) is roadmap work, not a present capability.

Fail-closed behavior: any sandbox crash, timeout, or malformed output becomes
a failed hard check and a rejection — never a promotion and never trusted
output.

## Data

- All committed fixtures are synthetic (`benchmarks/trendevobench/`), produced
  by a seeded generator in this repository. No scraped platform content, no
  personal data, no customer data.
- Run directories contain config, event provenance, evaluator evidence,
  artifact code, usage summaries, and (for `no_proposal`) a bounded model
  response excerpt. Manifests record Python/platform versions and may preserve
  a configured fixture path. Treat live run directories as reviewable research
  records, not as a safe destination for secrets or private prompts.

## Secrets

The offline provider, demo, and tests read no API keys and make no network
calls. The optional `OllamaProvider` makes HTTP requests to a configurable
Ollama endpoint (localhost by default); it is never used live in tests. The
runtime has no paid-provider credential integration today. Nothing secret-like
may be committed; contributions containing credentials, tokens, or production
connector configuration are rejected (see ADR 0003, CONTRIBUTING.md).

The offline execution contracts add no present security boundary. Their
synchronous runner cannot stop arbitrary blocking Python code, enforce paid
budgets, or confine filesystem/network access. Only in-process deterministic
fakes are shipped. Recovery requires the previous writer to be stopped; there
are no locks, leases, fsync guarantees, torn-JSON repair, or exactly-once claims.
Failed workspaces remain the caller's responsibility.

Execution records omit instructions, environments, workspace locators, raw
stdout/stderr, and exception text. Known transient values are checked against
public metadata and referenced artifacts; embedded short, encoded, or unknown
secrets can evade the checks. This is not a comprehensive secret detector.
Callers must review opaque IDs, revisions, and artifact contents.
Rejecting a result does not erase artifacts already stored by a caller. See
`docs/execution_contracts.md` for the precise evidence and recovery boundary.

Git worktrees isolate files for concurrent work but do not confine processes. Any
future executor or gateway must use capability-scoped permissions, secret
references rather than raw values, and explicit human approval for production
credentials, deployment, destructive actions, or paid execution.

## Reporting

Open a GitHub issue for non-sensitive problems. For anything sensitive,
contact the maintainers privately before disclosure.
