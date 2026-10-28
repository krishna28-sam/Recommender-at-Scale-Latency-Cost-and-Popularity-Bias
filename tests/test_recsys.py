from recsys.reranker import rerank
from recsys.scorer import rank_candidates


def tables():
    return (
        {"A": {"normalized_popularity": 0.5, "smoothed_ctr": 0.2, "popularity": 2},
         "B": {"normalized_popularity": 0.5, "smoothed_ctr": 0.2, "popularity": 2},
         "C": {"normalized_popularity": 0.1, "smoothed_ctr": 0.1, "popularity": 1}},
        {"A": "news", "B": "sports", "C": "news"},
    )


def test_tie_break_and_short_candidates():
    stats, categories = tables()
    top, full = rank_candidates(["B", "A", "C"], [], stats, categories, 5,
                                {"popularity": 0.7, "category_affinity": 0.3})
    assert [row["news_id"] for row in top] == ["A", "B", "C"]
    assert len(full) == 3


def test_reranker_lambda_zero_and_nonzero():
    stats, categories = tables()
    _, full = rank_candidates(["A", "B", "C"], [], stats, categories, 3,
                               {"popularity": 0.7, "category_affinity": 0.3})
    assert [x["news_id"] for x in rerank(full, categories, {"news": 0.67, "sports": 0.33}, 3, 0)] == ["A", "B", "C"]
    result = rerank(full, categories, {"news": 0.67, "sports": 0.33}, 3, 1.0)
    assert len(result) == 3


def test_empty_candidates():
    top, full = rank_candidates([], [], {}, {}, 5,
                                {"popularity": 0.7, "category_affinity": 0.3})
    assert top == [] and full == []


def test_reranker_target_changes_penalty():
    rows = [
        {"news_id": "A", "score": 1.0, "smoothed_ctr": 1.0, "popularity": 1.0},
        {"news_id": "B", "score": 1.0, "smoothed_ctr": 1.0, "popularity": 1.0},
    ]
    result = rerank(rows, {"A": "publisher_a", "B": "publisher_b"},
                    {"publisher_a": 0.9, "publisher_b": 0.1}, 2, 1.0)
    assert [row["news_id"] for row in result] == ["A", "B"]


def test_reranker_running_share_penalty_converges_to_target():
    target = {"publisher_a": 0.8, "publisher_b": 0.2}
    groups = {"A": "publisher_a", "B": "publisher_b"}
    base_rows = [
        {"news_id": "A", "score": 1.0, "smoothed_ctr": 1.0, "popularity": 1.0},
        {"news_id": "B", "score": 1.0, "smoothed_ctr": 1.0, "popularity": 1.0},
    ]

    state = {"exposure": {"publisher_a": 0.9, "publisher_b": 0.1}, "total": 1.0}
    choice = rerank(base_rows, groups, target, 1, 1.0, state=state)[0]["news_id"]
    assert choice == "B"

    state = {"exposure": {}, "total": 0.0}
    for _ in range(1000):
        rerank(base_rows, groups, target, 1, 1.0, state=state)

    exposure = state["exposure"]
    total = state["total"]
    share_a = exposure.get("publisher_a", 0.0) / max(total, 1e-9)
    share_b = exposure.get("publisher_b", 0.0) / max(total, 1e-9)
    assert abs(share_a - 0.8) < 0.05
    assert abs(share_b - 0.2) < 0.05


def test_reranker_demotes_overexposed_publisher():
    rows = [
        {"news_id": "A", "score": 1.0, "smoothed_ctr": 1.0, "popularity": 1.0},
        {"news_id": "B", "score": 0.9, "smoothed_ctr": 0.9, "popularity": 0.9},
    ]
    groups = {"A": "publisher_a", "B": "publisher_b"}
    targets = {"publisher_a": 0.5, "publisher_b": 0.5}

    assert rerank(rows, groups, targets, 1, 0.0)[0]["news_id"] == "A"
    state = {"exposure": {"publisher_a": 10.0}, "total": 10.0}
    assert rerank(rows, groups, targets, 1, 1.0, state=state)[0]["news_id"] == "B"
