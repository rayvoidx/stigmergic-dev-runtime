# stigdev-mutation: keyword_boost_more_specific

GENES = frozenset([])

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
            # More specific keyword boost
            if words & {"ai", "model", "launch", "climate", "emissions", "policy", "research", "chip"}:
                score *= 2.5  # Reduced boost to avoid over-weighting
            if words & {"shocking", "believe", "secret", "trick"}:
                score *= 0.2
        if "short_filter" in GENES and len(item["text"]) < 60:
            continue
        if "noise" in GENES:
            score *= 0.5 + (sum(ord(ch) for ch in item["id"]) % 100) / 100.0
        if "crash" in GENES:
            score += float('inf')  # intentional defect gene - use infinity to ensure it's always selected last
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
