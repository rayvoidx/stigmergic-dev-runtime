# stigdev-mutation: engagement_decay
def select_trends(items, k):
    """Selects the top 'k' trends based on a weighted score that considers engagement and recency."""
    if not items:
        return []

    scored = []
    for item in items:
        text = item["text"].lower()  # No normalization needed.
        score = float(item["engagement"])

        # Apply engagement decay based on age of the item.
        max_ts = max(item["ts"] for item in items)
        age = max_ts - item["ts"]
        if age > 0:
            score *= 0.95 ** (age / 300.0)  # Adjust exponent for smoother decay

        scored.append((score, item))

    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))

    out = []
    for _score, item in scored:
        out.append(item["id"])
        if len(out) == k:
            break
    return out
