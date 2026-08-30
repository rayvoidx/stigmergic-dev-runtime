"""Ephemeral worker episode: observe -> propose -> evaluate -> gate -> record.

A worker has no memory beyond the observation projected from the run store.
Everything it learns from prior episodes arrives through canonical state,
lineage, evidence, and failure records — the stigmergic medium.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from .evaluator import TrendSelectEvaluator
from .model import RunConfig, content_hash
from .policy import StrictImprovementPolicy
from .provider import OBS_BEGIN, OBS_END, Provider, ProviderRequest
from .store import RunStore

MAX_OBSERVED_FAILURES = 20  # bounded view: workers never see the full history

PROMPT_TEMPLATE = """You are one ephemeral worker episode in an artifact-evolution runtime.
Improve the canonical artifact below. Respond with a complete Python module in
one ```python fence. The module must define
select_trends(items: list[dict], k: int) -> list[str] returning item ids.
Use only the Python standard library. Include one comment line
`# stigdev-mutation: <short-name>` naming your change.
Prior failures are listed so you do not repeat them.
{obs_begin}
{observation_json}
{obs_end}
"""

_FENCE_RE = re.compile(r"```python\n(.*?)```", re.DOTALL)


def build_observation(store: RunStore, config: RunConfig, episode: int) -> dict[str, Any]:
    canonical = store.canonical()
    assert canonical is not None, "runtime must seed canonical state before episodes"
    failures = store.failures()[-MAX_OBSERVED_FAILURES:]
    return {
        "episode": episode,
        "canonical_hash": canonical["artifact_hash"],
        "canonical_score": canonical["score"],
        "canonical_generation": canonical["generation"],
        "canonical_source": store.get_artifact(canonical["artifact_hash"]),
        "failed_mutations": sorted({f["mutation"] for f in failures if f.get("mutation")}),
        "failures": [
            {
                "mutation": f.get("mutation"),
                "artifact_hash": f["artifact_hash"],
                "score": f["score"],
                "reason": f["reason"],
            }
            for f in failures
        ],
        "budget": {"episodes_remaining": config.budget.max_episodes - episode},
    }


def extract_code_fence(text: str) -> str | None:
    matches = _FENCE_RE.findall(text)
    return matches[-1] if matches else None


def parse_mutation(source: str) -> str | None:
    match = re.search(r"^# stigdev-mutation: (\S+)$", source, re.MULTILINE)
    return match.group(1) if match else None


def run_episode(
    store: RunStore,
    config: RunConfig,
    provider: Provider,
    evaluator: TrendSelectEvaluator,
    policy: StrictImprovementPolicy,
    episode: int,
) -> dict[str, Any]:
    observation = build_observation(store, config, episode)
    prompt = PROMPT_TEMPLATE.format(
        obs_begin=OBS_BEGIN,
        observation_json=json.dumps(observation, sort_keys=True),
        obs_end=OBS_END,
    )
    prompt_hash = content_hash(prompt)
    store.append_event(
        "episode_started",
        episode=episode,
        prompt_hash=prompt_hash,
        provider=asdict(provider.spec),
    )
    response = provider.generate(
        ProviderRequest(
            prompt=prompt,
            seed=config.seed,
            temperature=config.provider.temperature,
            max_output_tokens=config.provider.max_output_tokens,
        )
    )
    cost = {
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "usd": response.usd,
    }
    source = extract_code_fence(response.text)
    if source is None:
        store.append_event("no_proposal", episode=episode, response_text=response.text[:500], **cost)
        return {"status": "no_proposal", "cost": cost}

    candidate_hash = store.put_artifact(source)
    mutation = parse_mutation(source)
    prior_failures = store.failures()
    repeated_failure = candidate_hash in {f["artifact_hash"] for f in prior_failures} or (
        mutation is not None and mutation in {f.get("mutation") for f in prior_failures}
    )
    store.append_event(
        "proposed",
        episode=episode,
        artifact_hash=candidate_hash,
        parent_hash=observation["canonical_hash"],
        mutation=mutation,
        repeated_failure=repeated_failure,
        prompt_hash=prompt_hash,
        **cost,
    )
    evidence = evaluator.evaluate(store, candidate_hash, "train", config.k)
    store.append_event("evaluated", episode=episode, evidence=evidence.to_dict())
    decision = policy.decide(evidence, observation["canonical_score"])
    if decision.promote:
        generation = observation["canonical_generation"] + 1
        store.set_canonical(candidate_hash, generation, evidence.score)
        store.append_event(
            "promoted",
            episode=episode,
            artifact_hash=candidate_hash,
            parent_hash=observation["canonical_hash"],
            generation=generation,
            mutation=mutation,
            score=evidence.score,
            reason=decision.reason,
            policy_id=decision.policy_id,
        )
        status = "promoted"
    else:
        store.append_event(
            "rejected",
            episode=episode,
            artifact_hash=candidate_hash,
            parent_hash=observation["canonical_hash"],
            mutation=mutation,
            score=evidence.score,
            reason=decision.reason,
            policy_id=decision.policy_id,
            repeated_failure=repeated_failure,
        )
        status = "rejected"
    return {
        "status": status,
        "artifact_hash": candidate_hash,
        "mutation": mutation,
        "score": evidence.score,
        "repeated_failure": repeated_failure,
        "cost": cost,
    }
