"""Provider adapter boundary.

Provider is the seam where a live model API (Anthropic, OpenAI, ...) would
plug in. The MVP ships only OfflineTrendProvider: a deterministic, zero-cost
reference worker so the whole runtime, benchmark, and test suite run with no
network and no paid calls.

OfflineTrendProvider strategy (benchmark-specific, documented, not hidden):
the artifact source carries a '# stigdev-genes:' header naming enabled code
paths ("genes"). The provider reads the observation JSON embedded in the
prompt, picks the next gene not already canonical and not recorded as a
failure (when use_failure_memory is on), and emits a complete new artifact
source in a ```python fence — the same output contract a live LLM adapter
must satisfy. The runtime itself treats artifacts as opaque code; genes are
purely this provider's proposal strategy.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from typing import Protocol

from .model import ProviderSpec

OBS_BEGIN = "BEGIN_OBSERVATION_JSON"
OBS_END = "END_OBSERVATION_JSON"

# Proposal genes. Good genes genuinely improve the fixtures' composite score;
# bad genes regress it or crash — the promotion gate must catch them.
GENES = ("dedup", "recency", "keyword", "short_filter", "noise", "crash")

ARTIFACT_TEMPLATE = '''# stigdev-artifact trendevobench/select_trends
# stigdev-genes: {genes_json}
# stigdev-mutation: {mutation}
"""Trend selection artifact. Written by stigdev workers; executed only in the sandbox."""

GENES = frozenset({genes_json})


def _normalize(text):
    chars = [ch if ch.isalnum() or ch == " " else " " for ch in text.lower()]
    return " ".join("".join(chars).split())


def select_trends(items, k):
    if not items:
        return []
    max_ts = max(item["ts"] for item in items)
    scored = []
    for item in items:
        text = _normalize(item["text"])
        score = float(item["engagement"])
        if "recency" in GENES:
            score *= 0.5 ** ((max_ts - item["ts"]) / 300.0)
        if "keyword" in GENES:
            words = set(text.split())
            if words & {{"ai", "model", "launch", "climate", "emissions", "policy", "research", "chip"}}:
                score *= 3.0
            if words & {{"shocking", "believe", "secret", "trick"}}:
                score *= 0.2
        if "short_filter" in GENES and len(item["text"]) < 60:
            continue
        if "noise" in GENES:
            score *= 0.5 + (sum(ord(ch) for ch in item["id"]) % 100) / 100.0
        if "crash" in GENES:
            score += UNDEFINED_SYMBOL  # intentional defect gene
        scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    seen = set()
    out = []
    for _score, item in scored:
        if "dedup" in GENES:
            key = _normalize(item["text"])[:40]
            if key in seen:
                continue
            seen.add(key)
        out.append(item["id"])
        if len(out) == k:
            break
    return out
'''

_GENES_RE = re.compile(r"^# stigdev-genes: (\[.*\])$", re.MULTILINE)


def render_artifact(genes: set[str], mutation: str) -> str:
    return ARTIFACT_TEMPLATE.format(genes_json=json.dumps(sorted(genes)), mutation=mutation)


def parse_genes(source: str) -> set[str]:
    match = _GENES_RE.search(source)
    return set(json.loads(match.group(1))) if match else set()


@dataclass(frozen=True)
class ProviderRequest:
    prompt: str
    seed: int
    temperature: float
    max_output_tokens: int


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0


class Provider(Protocol):
    spec: ProviderSpec

    def generate(self, request: ProviderRequest) -> ProviderResponse: ...


class OllamaProvider:
    """Local Ollama adapter (default http://localhost:11434). Free and local-only,
    but still a live model: outputs are not bit-reproducible across hardware or
    Ollama versions. Never used in tests; replay verifies evidence, not
    generation. GPU use (Metal/CUDA) is Ollama's own scheduling.
    """

    def __init__(
        self,
        spec: ProviderSpec,
        host: str = "http://localhost:11434",
        timeout: float = 600.0,
    ):
        self.spec = spec
        self._host = host
        self._timeout = timeout

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        import urllib.request

        options: dict = {"temperature": request.temperature, "seed": request.seed}
        if request.max_output_tokens:
            options["num_predict"] = request.max_output_tokens
        payload = {
            "model": self.spec.model_id,
            "prompt": request.prompt,
            "stream": False,
            "options": options,
        }
        http_request = urllib.request.Request(
            f"{self._host}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(http_request, timeout=self._timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        return ProviderResponse(
            text=str(body.get("response", "")),
            input_tokens=int(body.get("prompt_eval_count", 0)),
            output_tokens=int(body.get("eval_count", 0)),
            usd=0.0,
        )


class OfflineTrendProvider:
    def __init__(self, spec: ProviderSpec, seed: int):
        self.spec = spec
        order = list(GENES)
        random.Random(seed).shuffle(order)
        self._order = order

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        observation = self._parse_observation(request.prompt)
        canonical_genes = parse_genes(observation["canonical_source"])
        failed = (
            set(observation.get("failed_mutations", [])) if self.spec.use_failure_memory else set()
        )
        untried = [g for g in self._order if g not in canonical_genes and g not in failed]
        if untried:
            mutation = untried[0]
        else:
            # Exhausted: deterministically re-probe an already-failed mutation so
            # repeated-failure accounting is exercised; stop if nothing failed.
            failed_all = sorted(set(observation.get("failed_mutations", [])) - canonical_genes)
            if not failed_all:
                return ProviderResponse("NO_PROPOSAL: all mutations already canonical")
            mutation = failed_all[observation.get("episode", 0) % len(failed_all)]
        source = render_artifact(canonical_genes | {mutation}, mutation)
        text = f"Proposing mutation '{mutation}'.\n```python\n{source}```\n"
        return ProviderResponse(text)

    @staticmethod
    def _parse_observation(prompt: str) -> dict:
        start = prompt.index(OBS_BEGIN) + len(OBS_BEGIN)
        end = prompt.index(OBS_END)
        return json.loads(prompt[start:end])
