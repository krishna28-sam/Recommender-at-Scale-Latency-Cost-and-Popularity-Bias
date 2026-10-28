import csv
import json
from datetime import datetime
from pathlib import Path


def parse_timestamp(value):
    return datetime.strptime(value, "%m/%d/%Y %H:%M:%S")


def test_derived_events_respect_cutoff_and_history_order():
    manifest_path = Path("data/manifests/movielens_manifest.json")
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text())
    cutoff = parse_timestamp(manifest["cutoff_timestamp"])
    ratings = {}
    with Path("data/raw/ml-25m/ratings.csv").open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            ratings.setdefault(row["userId"], {})["N{}".format(row["movieId"])] = (
                datetime.utcfromtimestamp(int(row["timestamp"])))
    for split in ("train", "dev"):
        path = Path("data/raw") / "MINDsmall_{}".format(split) / "behaviors.tsv"
        with path.open(encoding="utf-8") as handle:
            for row in csv.reader(handle, delimiter="\t"):
                impression_time = parse_timestamp(row[2])
                if split == "train":
                    assert impression_time < cutoff
                else:
                    assert impression_time >= cutoff
                history_ids = set(row[3].split())
                assert all(item.startswith("N") for item in history_ids)
                user_id = row[1][1:]
                assert all(ratings[user_id][item] < impression_time for item in history_ids)


def test_cold_start_metrics_are_present_and_in_range():
    manifest_path = Path("data/manifests/movielens_manifest.json")
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text())
    assert "train_known_items" in manifest
    assert "dev_items_not_in_train_known" in manifest
    assert "dev_candidate_cold_start_share" in manifest
    assert 0.0 <= manifest["dev_positives_cold_start_share"] <= 1.0
    assert 0.0 <= manifest["dev_candidate_cold_start_share"] <= 1.0
