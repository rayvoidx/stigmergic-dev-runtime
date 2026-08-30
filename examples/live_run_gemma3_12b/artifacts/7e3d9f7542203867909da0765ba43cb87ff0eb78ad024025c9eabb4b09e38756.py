# stigdev-mutation: ts_normalization
def select_trends(items, k):
    """Selects the top 'k' trends from a list of items, considering engagement and recency."""

    if not items:
        return []

    scored = []
    for item in items:
        text = item["text"]  # No normalization needed.
        score = float(item["engagement"])

        # Apply recency weighting. Normalize timestamp to [0, 1].
        max_ts = max(item["ts"] for item in items)
        min_ts = min(item["ts"] for item in items)
        normalized_ts = (item["ts"] - min_ts) / (max_ts - min_ts) if (max_ts - min_ts) > 0 else 0.5  # Handle cases where all timestamps are the same

        # Reduce score based on age of the item, using normalized timestamp
        age = 1 - normalized_ts
        if age > 0:
            score *= 0.9 ** (age / 300.0)  # Adjust exponent for smoother decay

        scored.append((score, item))

    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))

    out = []
    for _score, item in scored:
        out.append(item["id"])
        if len(out) == k:
            break
    return out
