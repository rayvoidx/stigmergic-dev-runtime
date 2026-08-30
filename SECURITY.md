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
- Run directories contain only config, synthetic evidence, and artifact code.
  Manifests record Python/platform versions; no usernames, paths outside the
  run, or credentials.

## Secrets

The runtime reads no API keys and makes no network calls. Nothing secret-like
may be committed; contributions containing credentials, tokens, or production
connector configuration are rejected (see ADR 0003, CONTRIBUTING.md).

## Reporting

Open a GitHub issue for non-sensitive problems. For anything sensitive,
contact the maintainers privately before disclosure.
