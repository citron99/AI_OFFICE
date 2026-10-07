"""Source-level retrieval metrics for already truncated top-k results."""


def score_case(expected: list[str], returned: list[str]) -> dict[str, float]:
    # Deduplicate sources: multiple chunks are not multiple relevant documents.
    returned = list(dict.fromkeys(returned))
    relevant = set(expected)
    matches = relevant.intersection(returned)
    return {
        "recall_at_k": len(matches) / len(relevant) if relevant else 0.0,
        # This is precision among returned sources, NOT precision divided by k.
        "precision_returned": len(matches) / len(returned) if returned else 0.0,
        "reciprocal_rank": next(
            (1 / rank for rank, title in enumerate(returned, 1) if title in relevant), 0.0
        ),
    }
