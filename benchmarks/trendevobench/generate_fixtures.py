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


def _make_items_v1(rng: random.Random, prefix: str, scale: int) -> list[dict]:
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


# --------------------------------------------------------------------------
# v2: harder tier. Design goals (calibrated; see tests/test_fixtures_v2.py):
#   low floor      engagement-only seed ranks traps first
#   middle rungs   v1-style single heuristics give partial gains
#   high ceiling   only combined source/duplicate/keyword/recency reasoning
#                  approaches the top (reference_artifact_v2.py is the probe)
# Adversarial properties vs v1:
#   - paraphrased duplicates: same story, different lead words -> 40-char
#     normalized-prefix dedup misses them; token-overlap reasoning required
#   - subtle listicle spam without classic clickbait words -> demote-word
#     filters miss it; the source field is the usable signal
#   - old-but-relevant analysis items -> aggressive recency decay backfires
#   - relevant items skew low/mid engagement -> engagement is anti-signal
# --------------------------------------------------------------------------

V2_TOPICS = [
    ("ai", "ai model launch expands context window for enterprise research"),
    ("ai", "open weights ai model release improves benchmark transparency"),
    ("ai", "research chip design cuts ai inference power draw in datacenter tests"),
    ("ai", "university consortium publishes ai evaluation methodology for agents"),
    ("ai", "ai policy draft sets disclosure rules for model training data"),
    ("ai", "startup demonstrates on device ai model for offline research use"),
    ("climate", "climate policy summit agrees emissions reporting standards"),
    ("climate", "grid operator adds storage capacity under climate policy framework"),
    ("climate", "emissions disclosure policy drafted for shipping and aviation"),
    ("climate", "coastal cities adopt climate adaptation policy with research funding"),
    ("climate", "carbon removal research pilot reports verified emissions cuts"),
    ("climate", "climate model research improves regional flood forecasts"),
]
V2_PARAPHRASE = [
    "{h}",
    "analysts react as {h}",
    "what it means now that {h}",
]
V2_OLD_RELEVANT = [
    "policy analysis archive climate emissions accounting methods explained",
    "foundational research review ai evaluation practices and pitfalls",
    "long form analysis grid storage economics under climate policy",
    "survey of ai model verification research methods for regulators",
]
V2_CLICKBAIT = [
    "shocking secret trick doctors dont want you to know about sleep",
    "you wont believe what this celebrity did shocking photos inside",
    "one weird trick to save money instantly secret banks hate it",
    "shocking footage viewers cant stop watching this secret clip",
]
V2_LISTICLE = [  # no demote words, no target words: source is the tell
    "top ten gadgets you need this summer ranked by our editors",
    "seven cozy recipes everyone is making this weekend right now",
    "the best travel spots locals never tell tourists about ranked",
    "ten desk setups that will transform your work from home life",
    "eight simple habits of highly organized people you can copy",
]
V2_OFFTOPIC = [
    "local team wins derby match in stoppage time after penalty call",
    "veteran striker announces retirement after record cup season",
    "city marathon draws record crowds in perfect autumn weather",
    "rookie goalkeeper saves three penalties in dramatic shootout",
    "regional league expands playoff format after fan survey",
    "transfer window rumors swirl around championship winning squad",
]
V2_HYPE = [
    "celebrity says ai will change everything in candid interview",
    "viral thread claims model predicted match results experts doubt",
    "influencer launches lifestyle brand with ai powered routines",
    "pundit blames climate for team slump in heated radio segment",
    "meme stock traders adopt ai chatbot for launch day predictions",
]


def _make_items_v2(rng: random.Random, prefix: str, scale: int) -> list[dict]:
    items: list[dict] = []
    counter = 0

    def add(text: str, relevant: bool, dup_group: str | None, ts: int, engagement: int, source: str) -> None:
        nonlocal counter
        item_id = f"{prefix}{counter:03d}"
        counter += 1
        items.append(
            {
                "id": item_id,
                "text": text,
                "source": source,
                "ts": ts,
                "engagement": engagement,
                "relevant": relevant,
                "dup_group": dup_group or f"solo-{item_id}",
            }
        )

    def rel_source() -> str:
        return rng.choices(SOURCES, weights=(70, 25, 5))[0]

    # relevant stories, paraphrase-duplicated (prefix dedup cannot catch these)
    stories = rng.sample(V2_TOPICS, 6 * scale)
    for story_idx, (_topic, headline) in enumerate(stories):
        n_variants = rng.choice((1, 2, 3))
        group = f"{prefix}story{story_idx}" if n_variants > 1 else None
        for template in rng.sample(V2_PARAPHRASE, n_variants):
            add(
                template.format(h=headline),
                True,
                group,
                rng.randint(550, 960),
                rng.randint(120, 500),
                rel_source(),
            )
    # old-but-relevant analysis (aggressive recency decay loses these)
    for text in rng.sample(V2_OLD_RELEVANT, 2 * scale):
        add(text, True, None, rng.randint(60, 320), rng.randint(150, 420), rel_source())
    # classic clickbait: demote words, huge engagement, recent
    for text in rng.sample(V2_CLICKBAIT, 2 * scale):
        add(text, False, None, rng.randint(500, 950), rng.randint(750, 1000), "synth-feed-c")
    # subtle listicle spam: no demote words; feed-c is the signal
    for text in rng.sample(V2_LISTICLE, 2 * scale):
        add(text, False, None, rng.randint(550, 950), rng.randint(650, 950), "synth-feed-c")
    # offtopic sports: mixed age, mid-high engagement
    for text in rng.sample(V2_OFFTOPIC, 3 * scale):
        add(text, False, None, rng.randint(80, 900), rng.randint(400, 800), rng.choice(SOURCES))
    # hype: target keywords, recent, high engagement, irrelevant
    for text in rng.sample(V2_HYPE, 2 * scale):
        add(text, False, None, rng.randint(600, 960), rng.randint(550, 800), rng.choice(("synth-feed-b", "synth-feed-c")))
    rng.shuffle(items)
    return items


GENERATORS = {
    "v1": (_make_items_v1, (("train", 7, "tr", 2), ("holdout", 11, "ho", 1))),
    "v2": (_make_items_v2, (("train", 19, "tr", 2), ("holdout", 23, "ho", 1))),
}


def main() -> None:
    version = sys.argv[1] if len(sys.argv) > 1 else "v1"
    make_items, splits = GENERATORS[version]
    out_dir = Path(__file__).parent / "fixtures" / version
    out_dir.mkdir(parents=True, exist_ok=True)
    for split, seed, prefix, scale in splits:
        items = make_items(random.Random(seed), prefix, scale)
        path = out_dir / f"{split}.jsonl"
        path.write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in items),
            encoding="utf-8",
        )
        relevant = sum(1 for i in items if i["relevant"])
        print(f"{path}: {len(items)} items ({relevant} relevant)")


if __name__ == "__main__":
    main()
