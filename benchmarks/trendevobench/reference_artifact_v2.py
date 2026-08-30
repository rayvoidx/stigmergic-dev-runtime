# stigdev-artifact trendevobench/select_trends
# stigdev-mutation: reference-v2-probe
"""Calibration probe for fixtures v2 — NOT a run seed.

Demonstrates that the v2 ceiling is reachable only by combining signals the
simple v1-style heuristics miss: token-overlap duplicate detection (catches
paraphrases), source reliability weighting (catches subtle listicle spam),
keyword evidence, gentle recency, and dampened engagement. Used by tests and
docs to pin the benchmark's dynamic range; runs still start from
seed_artifact.py.
"""

TARGET = {
    "ai", "model", "launch", "climate", "emissions", "policy",
    "research", "chip", "grid", "carbon", "evaluation",
}
CLICKBAIT = {"shocking", "believe", "secret", "trick"}
SOURCE_WEIGHT = {"synth-feed-a": 1.5, "synth-feed-b": 1.0, "synth-feed-c": 0.35}


def _normalize(text):
    chars = [ch if ch.isalnum() or ch == " " else " " for ch in text.lower()]
    return " ".join("".join(chars).split())


def _tokens(text):
    return set(_normalize(text).split())


def select_trends(items, k):
    if not items:
        return []
    max_ts = max(item["ts"] for item in items)
    scored = []
    for item in items:
        words = _tokens(item["text"])
        score = 1.0 + 0.001 * float(item["engagement"])  # engagement nearly ignored
        score *= 1.0 + 0.8 * len(words & TARGET)
        if words & CLICKBAIT:
            score *= 0.05
        score *= SOURCE_WEIGHT.get(item["source"], 1.0)
        score *= 0.75 + 0.25 * (item["ts"] / max_ts if max_ts else 1.0)  # gentle recency
        scored.append((score, item, words))
    scored.sort(key=lambda triple: (-triple[0], triple[1]["id"]))
    out = []
    kept_tokens = []
    for _score, item, words in scored:
        duplicate = False
        for seen in kept_tokens:
            union = len(words | seen)
            if union and len(words & seen) / union >= 0.5:
                duplicate = True
                break
        if duplicate:
            continue
        kept_tokens.append(words)
        out.append(item["id"])
        if len(out) == k:
            break
    return out
