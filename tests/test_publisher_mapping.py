"""Offline mapping test; run after MIND-small download."""
import json
import statistics
from pathlib import Path


def test_manifest_has_six_configurations_after_generation():
    manifest = Path("data/processed/publishers/manifest.json")
    if not manifest.exists():
        return
    rows = json.loads(manifest.read_text())
    assert len(rows) == 6
    random_mean = statistics.mean(row["mean_top_category_share"] for row in rows
                                  if row["family"] == "random")
    correlated_mean = statistics.mean(row["mean_top_category_share"] for row in rows
                                      if row["family"] == "category_correlated")
    print("family=random mean_top_category_share={:.6f}".format(random_mean))
    print("family=category_correlated mean_top_category_share={:.6f}".format(
        correlated_mean))
    assert correlated_mean > random_mean
