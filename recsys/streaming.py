"""Shared event scoring for the Spark and Flink streaming jobs."""
import json
import time
from pathlib import Path

import yaml

from recsys.reranker import rerank
from recsys.scorer import rank_candidates


class EventScorer:
    def __init__(self, assets, mapping, lambda_value, engine):
        assets = Path(assets)
        config = yaml.safe_load(Path("config/model.yaml").read_text())
        model = config["model"]
        self.stats = json.loads((assets / "item_stats.json").read_text())
        self.categories = json.loads((assets / "categories.json").read_text())
        self.groups = json.loads((assets / "publisher_by_item_{}.json".format(mapping)).read_text())
        self.targets = json.loads((assets / "target_shares_{}.json".format(mapping)).read_text())
        self.top_k = int(model["top_k"])
        self.weights = model["weights"]
        self.lambda_value = float(lambda_value)
        self.mapping = mapping
        self.engine = engine
        self.state = {"exposure": {}, "total": 0.0}

    def score(self, event):
        _, candidates = rank_candidates(
            event.get("candidates", []), event.get("history", []), self.stats,
            self.categories, len(event.get("candidates", [])), self.weights)
        served = rerank(
            candidates, self.groups, self.targets, self.top_k, self.lambda_value,
            state=self.state)
        return {
            "event_id": event["event_id"],
            "impression_id": event["impression_id"],
            "producer_timestamp_ms": event["producer_timestamp_ms"],
            "served_top_k": [row["news_id"] for row in served],
            "groups": {item: self.groups.get(item) for item in event.get("candidates", [])},
            "lambda": self.lambda_value,
            "mapping": self.mapping,
            "engine": self.engine,
            "sink_timestamp_ms": int(time.time() * 1000),
        }


def pass_through(event, engine):
    return {
        "event_id": event["event_id"],
        "impression_id": event["impression_id"],
        "producer_timestamp_ms": event["producer_timestamp_ms"],
        "served_top_k": event.get("candidates", [])[:5],
        "groups": {},
        "lambda": 0.0,
        "mapping": None,
        "engine": engine,
        "sink_timestamp_ms": int(time.time() * 1000),
    }


def validate_smoke_offsets(impressions, recommendations, max_dup_ratio=1.2):
    """Validate streaming smoke test offset counts with bounded at-least-once tolerance.

    Returns:
        tuple[bool, str]: (is_valid, status_message)
    """
    if impressions <= 0:
        return False, f"Zero input impressions produced ({impressions})"
    if recommendations < impressions:
        loss = impressions - recommendations
        return False, f"Missing outputs: {recommendations} < {impressions} (loss={loss})"
    max_allowed = int(impressions * max_dup_ratio)
    if recommendations > max_allowed:
        excess = recommendations - impressions
        return False, f"Excessive duplicates: {recommendations} > {max_allowed} (excess={excess})"
    return True, f"Parity check passed: {recommendations}/{impressions}"

