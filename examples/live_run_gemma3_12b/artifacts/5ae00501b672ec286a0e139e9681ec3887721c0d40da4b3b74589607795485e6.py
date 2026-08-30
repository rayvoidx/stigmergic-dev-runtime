# stigdev-mutation: remove_normalization
def select_trends(items: list[dict], k: int) -> list[str]:
    """Selects the top k trends from a list of items, sorted by engagement and recency.

    Args:
        items: A list of dictionaries, where each dictionary represents an item
            and has keys "engagement", "ts", and "id".  "engagement" is a numerical score,
            "ts" is a timestamp (numerical), and "id" is a unique identifier for the item.
        k: The number of top trends to select.

    Returns:
        A list of strings, where each string is the "id" of a selected trend.
    """
    if not items:
        return []

    scored = []
    for item in items:
        score = float(item["engagement"])

        # Apply recency weighting.  Reduce score based on age of the item.
        max_ts = max(item["ts"] for item in items)
        age = max_ts - item["ts"]
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
