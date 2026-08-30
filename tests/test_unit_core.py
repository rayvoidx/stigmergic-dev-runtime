"""Unit tests: model, store, policy, sandbox, evaluator, provider, worker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stigdev.evaluator import TrendSelectEvaluator, load_items, public_view
from stigdev.model import Budget, Evidence, RunConfig, content_hash
from stigdev.policy import StrictImprovementPolicy
from stigdev.provider import (
    OfflineTrendProvider,
    ProviderRequest,
    parse_genes,
    render_artifact,
)
from stigdev.runtime import default_fixtures_dir
from stigdev.sandbox import SubprocessSandbox
from stigdev.store import RunStore, StoreIntegrityError
from stigdev.worker import extract_code_fence, parse_mutation

FIXTURES = default_fixtures_dir("v1")


def _evidence(passed: bool, score: float) -> Evidence:
    return Evidence("e", "1", "h" * 64, "train", passed, score, {}, "" if passed else "boom")


# -- model ----------------------------------------------------------------


def test_content_hash_is_stable_sha256():
    assert content_hash("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_runconfig_round_trip():
    config = RunConfig(run_id="r1", seed=7, budget=Budget(max_episodes=3))
    restored = RunConfig.from_dict(json.loads(json.dumps(config.to_dict())))
    assert restored == config


# -- store ----------------------------------------------------------------


def test_store_artifact_content_addressing_and_tamper_detection(tmp_path: Path):
    store = RunStore.create(tmp_path / "run")
    digest = store.put_artifact("x = 1\n")
    assert store.get_artifact(digest) == "x = 1\n"
    store.artifact_path(digest).write_text("x = 2\n", encoding="utf-8")
    with pytest.raises(StoreIntegrityError):
        store.get_artifact(digest)


def test_store_event_seq_survives_reopen(tmp_path: Path):
    store = RunStore.create(tmp_path / "run")
    store.append_event("a")
    store.append_event("b")
    reopened = RunStore.open(tmp_path / "run")
    record = reopened.append_event("c")
    assert record["seq"] == 3
    assert [e["type"] for e in reopened.events()] == ["a", "b", "c"]


def test_store_refuses_to_overwrite_existing_run(tmp_path: Path):
    RunStore.create(tmp_path / "run")
    with pytest.raises(FileExistsError):
        RunStore.create(tmp_path / "run")


# -- policy ---------------------------------------------------------------


def test_policy_rejects_hard_check_failure():
    decision = StrictImprovementPolicy().decide(_evidence(False, 0.9), 0.1)
    assert not decision.promote
    assert "hard checks failed" in decision.reason


def test_policy_promotes_strict_improvement_only():
    policy = StrictImprovementPolicy()
    assert policy.decide(_evidence(True, 0.6), 0.5).promote
    assert not policy.decide(_evidence(True, 0.5), 0.5).promote
    assert not policy.decide(_evidence(True, 0.4), 0.5).promote
    assert policy.decide(_evidence(True, 0.4), None).promote  # seeding


# -- sandbox --------------------------------------------------------------


def _write_artifact(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "artifact.py"
    path.write_text(body, encoding="utf-8")
    return path


def test_sandbox_runs_artifact(tmp_path: Path):
    path = _write_artifact(tmp_path, "def f(x):\n    return [x, x]\n")
    result = SubprocessSandbox().call(path, "f", ["a"], timeout=10)
    assert result.ok and result.value == ["a", "a"]


def test_sandbox_reports_artifact_exception_fail_closed(tmp_path: Path):
    path = _write_artifact(tmp_path, "def f():\n    raise ValueError('nope')\n")
    result = SubprocessSandbox().call(path, "f", [], timeout=10)
    assert not result.ok and "ValueError" in result.error


def test_sandbox_kills_on_timeout(tmp_path: Path):
    path = _write_artifact(tmp_path, "def f():\n    while True:\n        pass\n")
    result = SubprocessSandbox().call(path, "f", [], timeout=1)
    assert not result.ok and "timeout" in result.error


def test_sandbox_rejects_stdout_pollution(tmp_path: Path):
    path = _write_artifact(tmp_path, "def f():\n    print('junk')\n    return []\n")
    result = SubprocessSandbox().call(path, "f", [], timeout=10)
    assert not result.ok and "non-JSON" in result.error


# -- evaluator ------------------------------------------------------------


def _eval_source(tmp_path: Path, source: str) -> Evidence:
    store = RunStore.create(tmp_path / "evalrun")
    digest = store.put_artifact(source)
    evaluator = TrendSelectEvaluator(FIXTURES, SubprocessSandbox())
    return evaluator.evaluate(store, digest, "train", 10)


def test_evaluator_strips_truth_fields():
    items = public_view(load_items(FIXTURES, "train"))
    assert items and all("relevant" not in i and "dup_group" not in i for i in items)


def test_evaluator_scores_seed_artifact(tmp_path: Path):
    seed = (Path(__file__).parents[1] / "benchmarks/trendevobench/seed_artifact.py").read_text()
    evidence = _eval_source(tmp_path, seed)
    assert evidence.passed
    assert evidence.score == pytest.approx(0.55)
    assert evidence.metrics["precision_at_k"] == pytest.approx(0.4)


def test_evaluator_hard_fails_wrong_output_type(tmp_path: Path):
    evidence = _eval_source(tmp_path, "def select_trends(items, k):\n    return 42\n")
    assert not evidence.passed and "not a list" in evidence.reason


def test_evaluator_hard_fails_unknown_ids(tmp_path: Path):
    evidence = _eval_source(tmp_path, "def select_trends(items, k):\n    return ['zz']\n")
    assert not evidence.passed and "unknown ids" in evidence.reason


def test_evaluator_hard_fails_too_many_ids(tmp_path: Path):
    source = "def select_trends(items, k):\n    return [i['id'] for i in items]\n"
    evidence = _eval_source(tmp_path, source)
    assert not evidence.passed and "k=10" in evidence.reason


# -- provider / worker ----------------------------------------------------


def _prompt(canonical_genes: set[str], failed: list[str], episode: int = 0) -> str:
    observation = {
        "episode": episode,
        "canonical_source": render_artifact(canonical_genes, "seed"),
        "failed_mutations": failed,
    }
    return f"x BEGIN_OBSERVATION_JSON {json.dumps(observation)} END_OBSERVATION_JSON"


def _spec(use_failure_memory: bool = True):
    from stigdev.model import ProviderSpec

    return ProviderSpec(use_failure_memory=use_failure_memory)


def test_provider_is_deterministic():
    request = ProviderRequest(_prompt(set(), []), 42, 0.0, 0)
    first = OfflineTrendProvider(_spec(), 42).generate(request)
    second = OfflineTrendProvider(_spec(), 42).generate(request)
    assert first.text == second.text
    assert first.usd == 0.0 and first.input_tokens == 0


def test_provider_skips_failed_mutations_with_memory():
    request = ProviderRequest(_prompt(set(), ["short_filter"]), 42, 0.0, 0)
    response = OfflineTrendProvider(_spec(), 42).generate(request)
    mutation = parse_mutation(extract_code_fence(response.text))
    assert mutation != "short_filter"


def test_provider_repeats_failures_without_memory():
    # seed-42 order proposes short_filter first; without memory it re-proposes it
    request = ProviderRequest(_prompt(set(), ["short_filter"]), 42, 0.0, 0)
    response = OfflineTrendProvider(_spec(use_failure_memory=False), 42).generate(request)
    assert parse_mutation(extract_code_fence(response.text)) == "short_filter"


def test_ollama_provider_maps_request_and_response(monkeypatch):
    import io
    import urllib.request

    from stigdev.provider import OllamaProvider

    captured = {}

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        body = {"response": "```python\nx = 1\n```", "prompt_eval_count": 12, "eval_count": 34}
        return FakeResponse(json.dumps(body).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    from stigdev.model import ProviderSpec

    provider = OllamaProvider(ProviderSpec(provider="ollama", model_id="test-model"))
    response = provider.generate(ProviderRequest("hi", seed=7, temperature=0.0, max_output_tokens=64))
    assert captured["url"].endswith("/api/generate")
    assert captured["payload"]["model"] == "test-model"
    assert captured["payload"]["options"] == {"temperature": 0.0, "seed": 7, "num_predict": 64}
    assert captured["payload"]["stream"] is False
    assert response.text == "```python\nx = 1\n```"
    assert (response.input_tokens, response.output_tokens, response.usd) == (12, 34, 0.0)


def test_render_and_parse_genes_round_trip():
    genes = {"dedup", "recency"}
    assert parse_genes(render_artifact(genes, "recency")) == genes


def test_extract_code_fence():
    assert extract_code_fence("no code here") is None
    assert extract_code_fence("a\n```python\nx = 1\n```\nb") == "x = 1\n"
