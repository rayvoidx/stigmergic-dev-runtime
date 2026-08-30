"""Sandbox boundary for executing evolved artifacts.

The runtime never imports or executes artifact code in-process. All artifact
execution goes through a Sandbox implementation.

SubprocessSandbox is an honest MVP boundary, and only that:
  - separate CPython process in isolated mode (-I: no user site, no env hooks)
  - wall-clock timeout, killed on expiry
  - temporary working directory
It does NOT confine filesystem or network access and is NOT a security
boundary against deliberately malicious code. Fail-closed: any malformed or
missing output is reported as failure, never trusted.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

_RUNNER = Path(__file__).with_name("_sandbox_runner.py")


@dataclass(frozen=True)
class SandboxResult:
    ok: bool
    value: Any
    error: str
    wall_seconds: float


class Sandbox(Protocol):
    def call(
        self, artifact_path: Path, entrypoint: str, args: list[Any], timeout: float
    ) -> SandboxResult: ...


class SubprocessSandbox:
    def call(
        self, artifact_path: Path, entrypoint: str, args: list[Any], timeout: float
    ) -> SandboxResult:
        payload = json.dumps({"entrypoint": entrypoint, "args": args})
        start = time.monotonic()
        try:
            with tempfile.TemporaryDirectory() as workdir:
                proc = subprocess.run(
                    [sys.executable, "-I", str(_RUNNER), str(artifact_path)],
                    input=payload,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=workdir,
                )
        except subprocess.TimeoutExpired:
            return SandboxResult(False, None, f"timeout after {timeout}s", time.monotonic() - start)
        elapsed = time.monotonic() - start
        if proc.returncode != 0:
            return SandboxResult(
                False, None, f"sandbox exited {proc.returncode}: {proc.stderr[-500:]}", elapsed
            )
        try:
            envelope = json.loads(proc.stdout)
        except (json.JSONDecodeError, ValueError):
            return SandboxResult(
                False, None, f"non-JSON sandbox output: {proc.stdout[:200]!r}", elapsed
            )
        if not isinstance(envelope, dict) or "ok" not in envelope:
            return SandboxResult(False, None, "malformed sandbox envelope", elapsed)
        if not envelope["ok"]:
            return SandboxResult(False, None, str(envelope.get("error", "unknown error")), elapsed)
        return SandboxResult(True, envelope.get("result"), "", elapsed)
