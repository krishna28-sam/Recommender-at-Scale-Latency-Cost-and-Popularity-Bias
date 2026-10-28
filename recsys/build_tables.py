"""Build train-only statistics and train+dev category lookups."""
import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
import yaml


def read_news(path):
    with path.open(encoding="utf-8") as handle:
        return {row[0]: {"category": row[1], "subcategory": row[2]}
                for row in csv.reader(handle, delimiter="\t") if len(row) == 8}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-dir", type=Path, required=True)
    parser.add_argument("--dev-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--publisher-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/model.yaml"))
    args = parser.parse_args()
    train_news = read_news(args.train_dir / "news.tsv")
    dev_news = read_news(args.dev_dir / "news.tsv")
    categories = dict(dev_news)
    categories.update(train_news)
    clicks, impressions = Counter(), Counter()
    total_clicks = total_impressions = 0
    with (args.train_dir / "behaviors.tsv").open(encoding="utf-8") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if len(row) != 5:
                continue
            for token in row[4].split():
                item_id, label = token.rsplit("-", 1)
                impressions[item_id] += 1
                total_impressions += 1
                if label == "1":
                    clicks[item_id] += 1
                    total_clicks += 1
    alpha = float(yaml.safe_load(args.config.read_text())["model"]["alpha"])
    global_ctr = total_clicks / float(total_impressions) if total_impressions else 0.0
    raw = {}
    for item_id in categories:
        item_impressions = impressions[item_id]
        smoothed = (clicks[item_id] + alpha * global_ctr) / (item_impressions + alpha)
        raw[item_id] = {
            "impressions": item_impressions,
            "clicks": clicks[item_id],
            "smoothed_ctr": smoothed,
            "popularity": math.log1p(item_impressions) * smoothed if item_impressions else 0.0,
        }
    values = [row["popularity"] for row in raw.values()]
    low, high = min(values, default=0.0), max(values, default=0.0)
    for row in raw.values():
        row["normalized_popularity"] = ((row["popularity"] - low) / (high - low)
                                         if high > low else 0.0)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "item_stats.json").write_text(json.dumps(raw, indent=2) + "\n")
    (args.output_dir / "categories.json").write_text(json.dumps(
        {item: info["category"] for item, info in categories.items()}, indent=2) + "\n")
    for mapping_path in sorted(args.publisher_dir.glob("*.tsv")):
        if mapping_path.name == "manifest.tsv":
            continue
        mapping = {}
        with mapping_path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                mapping[row["news_id"]] = row["synthetic_publisher"]
        counts = Counter(mapping[item] for item in train_news if item in mapping)
        total = sum(counts.values())
        target = {group: count / float(total) for group, count in counts.items()} if total else {}
        name = mapping_path.stem
        (args.output_dir / "target_shares_{}.json".format(name)).write_text(
            json.dumps(target, indent=2) + "\n")
        (args.output_dir / "publisher_by_item_{}.json".format(name)).write_text(
            json.dumps(mapping, indent=2) + "\n")
    print("wrote train-only item stats and per-mapping publisher target shares")


if __name__ == "__main__":
    main()
