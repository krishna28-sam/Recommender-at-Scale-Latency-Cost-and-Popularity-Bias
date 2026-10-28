"""Deterministic running-share exposure-aware reranking."""
import math


def discount(position):
    return 1.0 / math.log2(position + 1)


def rerank(scored_candidates, group_by_item, target_shares, top_k, lambda_value,
           state=None, eps=1e-9, config_path=None):
    if state is None:
        state = {"exposure": {}, "total": 0.0}
    exposure = state.setdefault("exposure", {})
    total = state.setdefault("total", 0.0)
    remaining = list(scored_candidates)
    selected = []

    for position in range(1, min(top_k, len(remaining)) + 1):
        d = discount(position)

        def key(row):
            group = group_by_item.get(row["news_id"])
            share = exposure.get(group, 0.0) / max(total, eps)
            penalty = lambda_value * max(0.0, share - target_shares.get(group, 0.0))
            adjusted = row["score"] - penalty
            return (adjusted, row["score"], row["smoothed_ctr"], row["popularity"], row["news_id"])

        chosen = sorted(
            remaining,
            key=lambda row: (-key(row)[0], -key(row)[1], -key(row)[2], -key(row)[3], key(row)[4]),
        )[0]
        remaining.remove(chosen)
        selected.append(chosen)

        group = group_by_item.get(chosen["news_id"])
        exposure[group] = exposure.get(group, 0.0) + d
        total += d
        state["exposure"] = exposure
        state["total"] = total

    return selected
