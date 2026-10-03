"""Claude Code as an `AgentExecutor` (ADR 0014).

Claude Code is a coding-agent CLI, not a model endpoint. ADR 0005 keeps those
apart on purpose: `Provider` is model inference (Ollama, or a paid API behind
explicit approval), `AgentExecutor` is an agent process working in a
workspace. Putting Claude Code behind `Provider` would be the category error
`AGENTS.md` warns about.

The operator runs it on a subscription, so this module's main job is to keep
it that way. Two rules, both tested:

1. No known billing-route variable reaches the subprocess. If a caller puts
   one in `ExecutionRequest.environment` the execution is refused before
   anything launches; if one merely sits in the ambient environment it is
   stripped.
2. Subscription usage is never reported as money. The CLI prints an
   API-equivalent cost estimate; recording it as `usd` would make every budget
   that reads `ExecutionUsage.usd` believe cash moved when none did.

Tests never invoke the real binary — `runner` is injected, the same rule the
Ollama adapter follows.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any, Callable, Mapping

from .executor import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionUsage,
    FailureClassification,
)

EXECUTOR_ID = "claude-code/v1"
# Every environment variable that routes Claude Code away from the operator's
# subscription and onto metered billing, as of Claude Code 2.1.261. Widen this
# set rather than narrowing it: a false positive costs one refused run, a false
# negative costs real money and breaks the local-first rule.
BILLING_ROUTE_VARS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_BEDROCK_BASE_URL",
        "ANTHROPIC_VERTEX_BASE_URL",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
    }
)
# A subscription run moves no cash, whatever the CLI estimates it would have
# cost on the API. The estimate stays in stdout for a human; it never becomes
# an accounting figure.
SUBSCRIPTION_USD = 0.0


class ClaudeCodeError(RuntimeError):
    """Refusal to launch. Never raised for an agent's own failure."""


Runner = Callable[..., Any]


class ClaudeCodeExecutor:
    """Run one assigned attempt in a workspace with the `claude` CLI, headless."""

    executor_id = EXECUTOR_ID

    def __init__(
        self,
        *,
        runner: Runner | None = None,
        binary: str = "claude",
        model: str | None = None,
        base_environment: Mapping[str, str] | None = None,
        extra_args: tuple[str, ...] = (),
    ):
        self._run = runner if runner is not None else subprocess.run
        self._binary = binary
        self._model = model
        self._base_env = dict(os.environ if base_environment is None else base_environment)
        self._extra_args = tuple(extra_args)

    # -- environment ---------------------------------------------------------

    def _environment(self, request: ExecutionRequest) -> dict[str, str]:
        asked = {name for name, _ in request.environment} & BILLING_ROUTE_VARS
        if asked:
            raise ClaudeCodeError(
                "refusing to run: the request sets a billing route "
                f"({', '.join(sorted(asked))}); Claude Code runs on the operator's subscription"
            )
        env = {k: v for k, v in self._base_env.items() if k not in BILLING_ROUTE_VARS}
        env.update(dict(request.environment))
        return env

    def _argv(self, request: ExecutionRequest) -> list[str]:
        argv = [self._binary, "-p", request.instruction, "--output-format", "json"]
        if self._model is not None:
            argv += ["--model", self._model]
        return argv + list(self._extra_args)

    # -- execution -----------------------------------------------------------

    def execute(self, request: ExecutionRequest) -> ExecutionResult:
        env = self._environment(request)
        if request.workspace.locator is None:
            raise ClaudeCodeError(
                f"workspace {request.workspace.workspace_id} has no locator to run in"
            )
        started = time.time()
        try:
            completed = self._run(
                self._argv(request),
                cwd=request.workspace.locator,
                env=env,
                timeout=request.timeout_seconds,
                capture_output=True,
                text=True,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return self._result(request, started, "timed_out", None, "", "", "timeout", True)
        except (FileNotFoundError, PermissionError) as exc:
            return self._result(
                request, started, "failed", None, "", str(exc), "executor_error", False
            )
        return self._interpret(request, started, completed)

    def _interpret(
        self, request: ExecutionRequest, started: float, completed: Any
    ) -> ExecutionResult:
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        exit_code = completed.returncode
        try:
            report = json.loads(stdout)
            if not isinstance(report, dict):
                raise ValueError("result envelope is not an object")
        except (ValueError, TypeError):
            # Fail closed: an unreadable envelope is not a success, whatever the exit code.
            return self._result(
                request, started, "failed", exit_code, stdout, stderr, "malformed_result", False
            )
        if exit_code != 0 or report.get("is_error"):
            # An `is_error` envelope with exit 0 is the CLI reporting its own
            # failure cleanly; that is the executor's error, not a bad exit code.
            classification = "nonzero_exit" if exit_code != 0 else "executor_error"
            return self._result(
                request, started, "failed", exit_code, stdout, stderr, classification, False,
                usage=self._usage(report),
            )
        return self._result(
            request, started, "success", exit_code, stdout, stderr, "none", False,
            usage=self._usage(report),
        )

    @staticmethod
    def _usage(report: dict[str, Any]) -> ExecutionUsage:
        raw = report.get("usage") or {}

        def count(key: str) -> int:
            value = raw.get(key, 0) if isinstance(raw, dict) else 0
            ok = isinstance(value, int) and not isinstance(value, bool) and value >= 0
            return value if ok else 0

        return ExecutionUsage(
            input_tokens=count("input_tokens"),
            output_tokens=count("output_tokens"),
            usd=SUBSCRIPTION_USD,
        )

    def _result(
        self,
        request: ExecutionRequest,
        started: float,
        status: str,
        exit_code: int | None,
        stdout: str,
        stderr: str,
        classification: FailureClassification,
        retryable: bool,
        usage: ExecutionUsage | None = None,
    ) -> ExecutionResult:
        return ExecutionResult(
            attempt_id=request.attempt_id,
            workspace=request.workspace,
            status=status,  # type: ignore[arg-type]
            started_at=started,
            finished_at=time.time(),
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            failure_classification=classification,
            retryable=retryable,
            usage=usage,
        )
