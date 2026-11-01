import json

from recsys.streaming import EventScorer, pass_through


def test_engine_wrappers_share_output_shape_and_variable_candidates(tmp_path):
    event = {
        "event_id": "e1",
        "impression_id": "i1",
        "producer_timestamp_ms": 1,
        "history": [],
        "candidates": ["N1", "unknown"],
    }
    spark = pass_through(event, "spark")
    flink = pass_through(event, "flink")
    assert spark["served_top_k"] == flink["served_top_k"]
    assert spark["event_id"] == flink["event_id"] == "e1"
    assert set(spark) == {
        "event_id", "impression_id", "producer_timestamp_ms", "served_top_k",
        "groups", "lambda", "mapping", "engine", "sink_timestamp_ms",
    }


def test_shared_scorer_handles_empty_history_and_unknown_item():
    scorer = EventScorer("data/processed/model_tables", "category_404", 0.0, "test")
    result = scorer.score({
        "event_id": "e2",
        "impression_id": "i2",
        "producer_timestamp_ms": 2,
        "history": [],
        "candidates": ["unknown"],
    })
    assert result["served_top_k"] == ["unknown"]
    assert result["mapping"] == "category_404"


def test_stateful_reranker_preserves_state_across_events():
    scorer = EventScorer("data/processed/model_tables", "category_404", 0.6, "spark")
    assert scorer.state["total"] == 0.0
    event1 = {
        "event_id": "e1",
        "impression_id": "i1",
        "producer_timestamp_ms": 1,
        "history": [],
        "candidates": ["N50775", "N31958", "N49285"],
    }
    scorer.score(event1)
    assert scorer.state["total"] > 0.0
    first_state_total = scorer.state["total"]

    event2 = {
        "event_id": "e2",
        "impression_id": "i2",
        "producer_timestamp_ms": 2,
        "history": [],
        "candidates": ["N58251", "N47383", "N50775"],
    }
    scorer.score(event2)
    assert scorer.state["total"] > first_state_total


def test_spark_and_flink_scorer_produce_identical_stateful_recommendations():
    events = [
        {"event_id": "e{}".format(i), "impression_id": "i{}".format(i),
         "producer_timestamp_ms": i, "history": [],
         "candidates": ["N50775", "N31958", "N49285", "N58251", "N47383"]}
        for i in range(1, 6)
    ]
    spark_scorer = EventScorer("data/processed/model_tables", "category_404", 0.6, "spark")
    flink_scorer = EventScorer("data/processed/model_tables", "category_404", 0.6, "flink")

    spark_results = [spark_scorer.score(ev) for ev in events]
    flink_results = [flink_scorer.score(ev) for ev in events]

    assert [r["served_top_k"] for r in spark_results] == [r["served_top_k"] for r in flink_results]
    assert spark_scorer.state == flink_scorer.state


def test_partitioned_state_diverges_from_unified_state():
    events = [
        {"event_id": "e{}".format(i), "impression_id": "i{}".format(i),
         "producer_timestamp_ms": i, "history": [],
         "candidates": ["N50775", "N31958", "N49285", "N58251", "N47383"]}
        for i in range(1, 10)
    ]
    global_scorer = EventScorer("data/processed/model_tables", "category_404", 0.6, "global")
    for ev in events:
        global_scorer.score(ev)

    p1_scorer = EventScorer("data/processed/model_tables", "category_404", 0.6, "p1")
    p2_scorer = EventScorer("data/processed/model_tables", "category_404", 0.6, "p2")
    for i, ev in enumerate(events):
        if i % 2 == 0:
            p1_scorer.score(ev)
        else:
            p2_scorer.score(ev)

    assert p1_scorer.state["total"] < global_scorer.state["total"]
    assert p2_scorer.state["total"] < global_scorer.state["total"]
    assert abs((p1_scorer.state["total"] + p2_scorer.state["total"]) - global_scorer.state["total"]) < 1e-9


def test_validate_smoke_offsets():
    from recsys.streaming import validate_smoke_offsets

    # Exact count equality
    ok, msg = validate_smoke_offsets(100, 100)
    assert ok is True
    assert "Parity check passed" in msg

    # Permissible slight duplicates (within 1.2x at-least-once threshold)
    ok, msg = validate_smoke_offsets(100, 115)
    assert ok is True
    assert "Parity check passed" in msg

    # Under-delivery / missing outputs must fail
    ok, msg = validate_smoke_offsets(100, 95)
    assert ok is False
    assert "Missing outputs" in msg
    assert "loss=5" in msg

    # Complete loss (0 outputs) must fail
    ok, msg = validate_smoke_offsets(100, 0)
    assert ok is False
    assert "Missing outputs" in msg
    assert "loss=100" in msg

    # Runaway / excessive duplication (>1.2x) must fail
    ok, msg = validate_smoke_offsets(100, 125)
    assert ok is False
    assert "Excessive duplicates" in msg

    # Non-positive input count must fail
    ok, msg = validate_smoke_offsets(0, 0)
    assert ok is False
    assert "Zero input impressions" in msg


