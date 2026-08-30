"""Deterministic generator for TrendEvoBench synthetic fixtures.

Usage:  python benchmarks/trendevobench/generate_fixtures.py v1

Purely synthetic: no scraped data, no real platform content. The item mix is
constructed so that the seed artifact (engagement-only ranking) is beatable by
honest improvements and hurt by the defect mutations:
  - spam items carry clickbait words + top engagement (traps engagement-only)
  - near-duplicate variants share a >=40-char normalized prefix (dedup helps)
  - old items skew irrelevant (recency helps)
  - some relevant items have short texts (aggressive length filters regress)
Truth fields (relevant, dup_group) are evaluator-only; the runtime strips
them before artifacts see items.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

SOURCES = ("synth-feed-a", "synth-feed-b", "synth-feed-c")

RELEVANT_LONG = [
    "new ai model launch improves reasoning benchmarks for enterprise research teams",
    "open weights ai model release expands independent research access worldwide",
    "climate policy summit agrees emissions reporting standards for heavy industry",
    "national grid operator adds storage capacity under new climate policy framework",
    "university research consortium publishes ai evaluation methodology for agents",
    "chip supplier expands fabrication capacity for ai accelerator research market",
    "regulators draft emissions disclosure policy for shipping and aviation sectors",
    "startup demonstrates low power ai chip design for on device model inference",
    "coastal cities adopt climate adaptation policy backed by new research funding",
    "ai research lab reports progress on verifiable evaluation of model behavior",
]
RELEVANT_SHORT = [
    "ai model launch tops benchmark",
    "emissions policy vote passes",
    "research chip ships early",
    "climate policy deal reached",
    "ai model research grant grows",
    "launch of open model toolkit",
]
DUP_BASES = [
    "major ai model launch announced with expanded context window and lower prices",
    "climate emissions accord signed by forty countries after marathon policy talks",
    "research chip breakthrough doubles ai training efficiency in lab benchmarks",
    "open source ai model matches proprietary systems on public research suites",
]
DUP_SUFFIXES = [" analysts react", " full details inside", " what it means for the industry"]
SPAM = [
    "shocking secret trick doctors dont want you to know about morning routines",
    "you wont believe what this celebrity did on vacation shocking photos inside",
    "one weird trick to save money instantly secret banks hate this method",
    "shocking footage viewers cant stop watching this unbelievable secret clip",
    "the secret trick behind viral fame you wont believe number seven",
]
HYPE = [  # irrelevant despite target keywords: keeps precision below 1.0
    "celebrity says ai will change everything in candid late night interview",
    "viral thread claims model predicted match results experts remain unconvinced",
    "influencer launches lifestyle brand promising ai powered morning routines",
    "pundit blames climate for team slump in heated radio segment",
]
OFFTOPIC = [
    "local team wins derby match in stoppage time after controversial penalty",
    "veteran striker announces retirement following record breaking cup season",
    "city marathon draws record crowds as weather stays clear all morning",
    "rookie goalkeeper saves three penalties in dramatic shootout final",
    "regional league expands playoff format after fan survey results",
]


def _make_items(rng: random.Random, prefix: str, scale: int) -> list[dict]:
    items: list[dict] = []
    counter = 0

    def add(text: str, relevant: bool, dup_group: str | None, ts: int, engagement: int) -> None:
        nonlocal counter
        item_id = f"{prefix}{counter:03d}"
        counter += 1
        items.append(
            {
                "id": item_id,
                "text": text,
                "source": rng.choice(SOURCES),
                "ts": ts,
                "engagement": engagement,
                "relevant": relevant,
                "dup_group": dup_group or f"solo-{item_id}",
            }
        )

    # spam: clickbait words, top engagement, recent (only keyword demotion catches it)
    for text in rng.sample(SPAM, min(len(SPAM), 3 * scale)):
        add(text, False, None, rng.randint(400, 900), rng.randint(700, 1000))
    # offtopic sports: mid-high engagement, old (recency decay catches it)
    for text in rng.sample(OFFTOPIC, min(len(OFFTOPIC), 3 * scale)):
        add(text, False, None, rng.randint(100, 500), rng.randint(400, 800))
    # hype: recent, high engagement, target keywords, still irrelevant
    for text in rng.sample(HYPE, min(len(HYPE), 2 * scale)):
        add(text, False, None, rng.randint(600, 960), rng.randint(550, 750))
    # near-duplicate groups: relevant, high engagement, recent
    for base_idx, base in enumerate(rng.sample(DUP_BASES, 2 * scale)):
        group = f"{prefix}dup{base_idx}"
        for suffix in rng.sample(DUP_SUFFIXES, 3):
            add(base + suffix, True, group, rng.randint(600, 960), rng.randint(500, 800))
    # normal relevant: recent skew, mid engagement
    for text in rng.sample(RELEVANT_LONG, 5 * scale):
        add(text, True, None, rng.randint(500, 960), rng.randint(200, 600))
    # short relevant: recent, decent engagement (length filters lose these)
    for text in rng.sample(RELEVANT_SHORT, 3 * scale):
        add(text, True, None, rng.randint(600, 960), rng.randint(250, 550))
    rng.shuffle(items)
    return items


def main() -> None:
    version = sys.argv[1] if len(sys.argv) > 1 else "v1"
    out_dir = Path(__file__).parent / "fixtures" / version
    out_dir.mkdir(parents=True, exist_ok=True)
    for split, seed, prefix, scale in (("train", 7, "tr", 2), ("holdout", 11, "ho", 1)):
        items = _make_items(random.Random(seed), prefix, scale)
        path = out_dir / f"{split}.jsonl"
        path.write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in items),
            encoding="utf-8",
        )
        relevant = sum(1 for i in items if i["relevant"])
        print(f"{path}: {len(items)} items ({relevant} relevant)")


if __name__ == "__main__":
    main()
