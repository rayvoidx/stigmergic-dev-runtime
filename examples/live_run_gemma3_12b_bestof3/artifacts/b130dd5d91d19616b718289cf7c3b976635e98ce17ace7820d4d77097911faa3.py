# stigdev-mutation: recency_weighting
def _normalize(text):
    chars = [ch if ch.isalnum() or ch == " " else " " for ch in text.lower()]
    return " ".join("".join(chars).split())


def select_trends(items, k):
    if not items:
        return []

    scored = []
    for item in items:
        text = _normalize(item["text"])
        score = float(item["engagement"])

        # Apply recency weighting.  Reduce score based on age of the item.
        max_ts = max(item["ts"] for item in items)
        age = max_ts - item["ts"]
        if age > 0:
            score *= 0.9 ** (age / 300.0)  # Adjust weighting factor as needed

        scored.append((score, item))

    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))

    out = []
    for _score, item in scored:
        out.append(item["id"])
        if len(out) == k:
            break

    return out
