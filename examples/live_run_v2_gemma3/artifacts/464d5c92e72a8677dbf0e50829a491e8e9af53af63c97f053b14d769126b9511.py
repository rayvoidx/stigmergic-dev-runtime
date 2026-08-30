# stigdev-mutation: keyword_boost

GENES = frozenset([])

def _normalize(text):
    chars = [ch if ch.isalnum() or ch == " " else " " for ch in text.lower()]
    return " ".join("".join(chars).split())

def select_trends(items, k):
    if not items:
        return []
    max_ts = max(item["ts"] for item in items) if items else 0  # Handle empty list case
    scored = []
    for item in items:
        text = _normalize(item["text"])
        score = float(item["engagement"])
        if "keyword" in GENES:
            words = set(text.split())
            boost_keywords = {"ai", "model", "launch", "climate", "emissions", "policy", "research", "chip"}
            negative_keywords = {"shocking", "believe", "secret", "trick"}
            if words & boost_keywords:
                score *= 1.5  # Increased keyword boost
            if words & negative_keywords:
                score *= 0.5 # increased penalty for negative keywords
        scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    return [item["id"] for _, item in scored[:k]]
