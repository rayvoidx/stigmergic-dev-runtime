#!/usr/bin/env python3
"""Fetch open-model candidates from Hugging Face and shortlist what this node can hold.

This is the networked half of ADR 0015. It lives in `scripts/` for the same
reason `commission_node.py` does: the kernel and its tests never reach the
network, so anything that does stays out of `stigdev/`.

What it produces is a *shortlist to benchmark*, not a choice. Ranking a model
highly on a public board is someone else's measurement; ADR 0010's promotion
gate still decides what runs, and it reads only what this machine measured.

Two judgement calls are visible in the output and should stay visible:

* `params_b` is read from the model's own metadata where possible and guessed
  from the name otherwise. The memory estimate then rests on that number.
* `license_state` is derived from the licence tag. Anything that is not
  clearly a permissive open licence reports `unknown` or `restricted`, never
  `commercial_ok`, because a licence is a rights question and the default has
  to fail closed.

Usage:
    python3 scripts/fetch_model_rankings.py --node mobile-m4 --class text_small
    python3 scripts/fetch_model_rankings.py --out state/models/candidates.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stigdev.modelfit import ModelCandidate, ModelFitError, estimated_memory_gb, shortlist  # noqa: E402
from stigdev.node import PROFILES, RESOURCE_CLASSES  # noqa: E402

HF_API = "https://huggingface.co/api/models"
USER_AGENT = "stigdev-model-radar/0.1 (+https://github.com/rayvoidx/stigmergic-dev-runtime)"
TIMEOUT_SECONDS = 20.0

# Licences under which the operator may publish commercially produced work.
# Anything absent reports `unknown`/`restricted` and is shortlisted only with
# --allow-noncommercial, which exists so a researcher can look, not publish.
COMMERCIAL_LICENCES = frozenset(
    {
        "apache-2.0",
        "mit",
        "bsd-3-clause",
        "bsd-2-clause",
        "cc-by-4.0",
        "cc0-1.0",
    }
)
# Sizes that appear in model names: "...-8b", "...-3.8B-instruct", "...-70b-...".
_SIZE = re.compile(r"(?<![0-9.])([0-9]{1,3}(?:\.[0-9])?)\s*[bB](?![a-zA-Z0-9])")


def _get(url: str) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def params_from_name(model_id: str) -> float | None:
    """Best-effort size from the model name. None rather than a wild guess."""
    matches = _SIZE.findall(model_id)
    if not matches:
        return None
    try:
        value = float(matches[0])
    except ValueError:
        return None
    return value if 0 < value <= 1000 else None


def params_from_metadata(entry: dict) -> float | None:
    """Parameter count from `safetensors.total`, which HF reports for most repos."""
    total = (entry.get("safetensors") or {}).get("total")
    if isinstance(total, (int, float)) and not isinstance(total, bool) and total > 0:
        return round(total / 1e9, 2)
    return None


def license_state(entry: dict) -> str:
    """Fail closed: only a known permissive licence earns `commercial_ok`."""
    tags = [t for t in (entry.get("tags") or []) if isinstance(t, str)]
    licences = {t.split("license:", 1)[1].lower() for t in tags if t.startswith("license:")}
    card = entry.get("cardData") or {}
    if isinstance(card, dict) and isinstance(card.get("license"), str):
        licences.add(card["license"].lower())
    if licences & COMMERCIAL_LICENCES:
        return "commercial_ok"
    return "restricted" if licences else "unknown"


def fetch(limit: int, task: str, search: str | None) -> list[dict]:
    query = {
        "sort": "downloads",  # the public proxy for "what people actually run"
        "direction": "-1",
        "limit": str(limit),
        "filter": task,
        "full": "true",
    }
    if search:
        query["search"] = search
    url = f"{HF_API}?{urllib.parse.urlencode(query)}"
    payload = _get(url)
    if not isinstance(payload, list):
        raise SystemExit(f"unexpected response shape from {url}")
    return [entry for entry in payload if isinstance(entry, dict)]


def to_candidates(
    entries: list[dict], quantization: str, source: str
) -> tuple[list[ModelCandidate], list[dict]]:
    now = datetime.now(timezone.utc).isoformat()
    candidates: list[ModelCandidate] = []
    skipped: list[dict] = []
    rank = 0
    for entry in entries:
        model_id = entry.get("id") or entry.get("modelId")
        if not isinstance(model_id, str):
            continue
        measured = params_from_metadata(entry)
        params = measured if measured is not None else params_from_name(model_id)
        if params is None:
            skipped.append({"model_id": model_id, "reason": "no parameter count"})
            continue
        rank += 1
        try:
            candidates.append(
                ModelCandidate(
                    model_id=model_id,
                    params_b=params,
                    quantization=quantization,
                    rank=rank,
                    source=source,
                    captured_at=now,
                    license_state=license_state(entry),
                    evidence_grade="B",
                    score=float(entry["downloads"])
                    if isinstance(entry.get("downloads"), (int, float))
                    else None,
                )
            )
        except ModelFitError as exc:
            rank -= 1
            skipped.append({"model_id": model_id, "reason": str(exc)})
    return candidates, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", default="mobile-m4", choices=sorted(PROFILES))
    parser.add_argument(
        "--class", dest="resource_class", default="text_small", choices=sorted(RESOURCE_CLASSES)
    )
    parser.add_argument("--quantization", default="q4")
    parser.add_argument("--task", default="text-generation")
    parser.add_argument("--search", default=None, help="narrow the query, e.g. a language or family")
    parser.add_argument("--limit", type=int, default=50, help="how many ranked rows to pull")
    parser.add_argument("--top", type=int, default=5, help="how many shortlisted candidates to keep")
    parser.add_argument(
        "--allow-noncommercial",
        action="store_true",
        help="include models whose licence does not establish commercial use",
    )
    parser.add_argument("--out", default=None, help="write the shortlist as JSON")
    args = parser.parse_args()

    profile = PROFILES[args.node]
    resource_class = RESOURCE_CLASSES[args.resource_class]
    source = f"huggingface/{args.task}/downloads"

    try:
        entries = fetch(args.limit, args.task, args.search)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise SystemExit(f"could not reach Hugging Face: {exc}") from exc

    candidates, skipped = to_candidates(entries, args.quantization, source)
    picked = shortlist(
        candidates,
        profile,
        resource_class,
        limit=args.top,
        require_commercial=not args.allow_noncommercial,
    )

    report = {
        "node": profile.node_id,
        "resource_class": resource_class.name,
        "class_memory_gb": resource_class.memory_gb,
        "node_usable_memory_gb": profile.usable_memory_gb,
        "quantization": args.quantization,
        "source": source,
        "considered": len(candidates),
        "skipped": skipped[:10],
        "shortlist": [
            dict(c.to_dict(), estimated_memory_gb=round(estimated_memory_gb(c), 2)) for c in picked
        ],
        "note": (
            "A shortlist is what to benchmark, not what to run. Promotion is "
            "stigdev.modelradar.model_promotion_gate on measured results."
        ),
    }
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {out} ({len(picked)} candidates)")
    else:
        print(text)
    return 0 if picked else 1


if __name__ == "__main__":
    raise SystemExit(main())
