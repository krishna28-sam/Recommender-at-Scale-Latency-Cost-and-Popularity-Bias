"""Generate deterministic synthetic publisher mappings over train+dev news."""
import argparse
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import yaml


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_news(path):
    rows = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if len(row) == 8:
                rows.append((row[0], row[1]))
    return rows


def union_news(paths):
    by_id = {}
    for path in paths:
        for news_id, category in read_news(path):
            by_id.setdefault(news_id, category)
    return sorted(by_id.items())


def publisher_names(count):
    return ["synthetic_publisher_{:03d}".format(i) for i in range(count)]


def make_mapping(news, family, seed, count):
    publishers = publisher_names(count)
    rng = random.Random(seed)
    if family == "random":
        return [(news_id, rng.choice(publishers), category)
                for news_id, category in news]
    grouped = defaultdict(list)
    for news_id, category in news:
        grouped[category].append(news_id)
    categories = sorted(grouped)
    category_sizes = Counter(category for _, category in news)
    weighted_categories = []
    for category in categories:
        weighted_categories.extend([category] * category_sizes[category])
    rng.shuffle(weighted_categories)
    primary = {publisher: weighted_categories[index % len(weighted_categories)]
               for index, publisher in enumerate(publishers)}
    by_category = defaultdict(list)
    for publisher, category in primary.items():
        by_category[category].append(publisher)
    output = []
    for news_id, category in news:
        if by_category[category] and rng.random() < 0.8:
            publisher = rng.choice(by_category[category])
        else:
            publisher = rng.choice(publishers)
        output.append((news_id, publisher, category))
    return output


def top_category_share(rows):
    by_publisher = defaultdict(Counter)
    for _, publisher, category in rows:
        by_publisher[publisher][category] += 1
    shares = []
    for counts in by_publisher.values():
        shares.append(max(counts.values()) / float(sum(counts.values())))
    return sum(shares) / len(shares) if shares else 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-news", type=Path, required=True)
    parser.add_argument("--dev-news", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/model.yaml"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text())
    data_config = config["data"]
    news_paths = [args.train_news, args.dev_news]
    news = union_news(news_paths)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    marker_dir = args.train_news.parent.parent
    data_source = "synthetic" if (marker_dir / "SYNTHETIC_DATA.txt").exists() else (
        "movielens_derived" if (marker_dir / "MOVIELENS_DERIVED_DATA.txt").exists() else "real")
    manifest = []
    family_shares = defaultdict(list)
    for item in data_config["publisher_configs"]:
        rows = make_mapping(news, item["family"], int(item["seed"]),
                            int(data_config["publisher_count"]))
        output = args.output_dir / "{}.tsv".format(item["name"])
        with output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t")
            writer.writerow(["news_id", "synthetic_publisher", "mapping_family", "seed", "category"])
            writer.writerows((news_id, publisher, item["family"], item["seed"], category)
                             for news_id, publisher, category in rows)
        share = top_category_share(rows)
        family_shares[item["family"]].append(share)
        manifest.append({
            "data_source": data_source,
            "name": item["name"], "family": item["family"], "seed": item["seed"],
            "publisher_count": data_config["publisher_count"],
            "distribution": data_config["publisher_distribution"],
            "method": "random assignment" if item["family"] == "random"
            else "category-primary allocation; 0.8 own-category, 0.2 uniform",
            "inputs": [{"file": str(path), "sha256": sha256(path)} for path in news_paths],
            "news_count": len(news), "mean_top_category_share": share,
        })
        print("{}: {} assignments; mean_top_category_share={:.6f}".format(
            output, len(rows), share))
    random_mean = sum(family_shares["random"]) / len(family_shares["random"])
    category_mean = sum(family_shares["category_correlated"]) / len(
        family_shares["category_correlated"])
    print("family=random mean_top_category_share={:.6f}".format(random_mean))
    print("family=category_correlated mean_top_category_share={:.6f}".format(category_mean))
    if not category_mean > random_mean:
        raise RuntimeError("category_correlated must exceed random top-category share")
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Wrote {}".format(args.output_dir / "manifest.json"))


if __name__ == "__main__":
    main()
