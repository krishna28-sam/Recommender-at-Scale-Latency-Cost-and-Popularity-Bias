"""Pure-Python Tier 1 scorer shared by Spark and Flink."""
import math


def category_affinity(history_ids, candidate_category, categories):
    known = [categories[item] for item in history_ids if item in categories]
    return (sum(category == candidate_category for category in known) / float(len(known))
            if known else 0.0)


def rank_candidates(candidates, history_ids, item_stats, categories, top_k, weights):
    scored = []
    for item_id in candidates:
        stats = item_stats.get(item_id, {})
        score = (weights["popularity"] * stats.get("normalized_popularity", 0.0)
                 + weights["category_affinity"] * category_affinity(
                     history_ids, categories.get(item_id), categories))
        scored.append({
            "news_id": item_id,
            "score": score,
            "smoothed_ctr": stats.get("smoothed_ctr", 0.0),
            "popularity": stats.get("popularity", 0.0),
            "category": categories.get(item_id),
        })
    scored.sort(key=lambda row: (
        -row["score"], -row["smoothed_ctr"], -row["popularity"], row["news_id"]))
    return scored[:top_k], scored
