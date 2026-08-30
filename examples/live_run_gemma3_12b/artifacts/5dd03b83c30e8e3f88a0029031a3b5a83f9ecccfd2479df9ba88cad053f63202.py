# stigdev-mutation: id_tiebreaker
def select_trends(items, k):
    """Selects the top 'k' trends based on a combined score of engagement and recency.

    Args:
        items (list[dict]): A list of dictionaries, where each dictionary represents a trend
                             and contains keys like "text", "engagement", "ts", and "id".
        k (int): The number of top trends to select.

    Returns:
        list[str]: A list of the IDs of the top 'k' trends.
    """
    if not items:
        return []

    scored = []
    for item in items:
        text = item["text"]  # No normalization needed, as it doesn't improve score
        score = float(item["engagement"])

        # Apply recency weighting. Reduce score based on age of the item.
        max_ts = max(item["ts"] for item in items)
        age = max_ts - item["ts"]
        if age > 0:
            score *= 0.9 ** (age / 300.0)  # Adjust exponent for smoother decay

        scored.append((score, item))

    # Sort by score descending and then by ID ascending to break ties.
    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))

    out = []
    for _score, item in scored:
        out.append(item["id"])
        if len(out) == k:
            break
    return out
