"""Create a deterministic, MIND-format synthetic dataset for pipeline tests."""
import argparse
import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path


CATEGORIES = [
    "news", "sports", "finance", "food", "travel", "lifestyle", "health",
    "entertainment", "technology", "autos", "video", "weather", "music",
    "movies", "tv", "gaming", "science",
]


def write_news(path, start, count, rng):
    rows = []
    for index in range(start, start + count):
        news_id = "N{}".format(index)
        category = CATEGORIES[index % len(CATEGORIES)]
        subcategory = "{}_{}".format(category, index % 5)
        rows.append([
            news_id, category, subcategory,
            "Synthetic {} headline {}".format(category, index),
            "Synthetic abstract for item {}".format(index),
            "https://synthetic.invalid/{}/{}".format(category, news_id),
            "[]", "[]",
        ])
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(rows)


def write_behaviors(path, count, news_count, user_count, rng, start_time):
    rows = []
    weights = [1.0 / ((index + 1) ** 1.15) for index in range(news_count)]
    for impression in range(count):
        impression_id = str(impression + 1)
        user_id = "U{}".format(rng.randint(1, user_count))
        timestamp = (start_time + timedelta(minutes=impression)).strftime("%m/%d/%Y %H:%M:%S")
        history_length = rng.randint(0, 10)
        history = ["N{}".format(rng.randrange(news_count)) for _ in range(history_length)]
        candidates = rng.sample(range(news_count), 10)
        click_index = max(range(len(candidates)), key=lambda position: (
            weights[candidates[position]] * (0.8 + 0.4 * rng.random())))
        impression_items = [
            "N{}-{}".format(item, 1 if position == click_index else 0)
            for position, item in enumerate(candidates)
        ]
        rows.append([impression_id, user_id, timestamp, " ".join(history),
                     " ".join(impression_items)])
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--seed", type=int, default=20261028)
    parser.add_argument("--train-news", type=int, default=20000)
    parser.add_argument("--dev-extra-news", type=int, default=1000)
    parser.add_argument("--train-impressions", type=int, default=30000)
    parser.add_argument("--dev-impressions", type=int, default=10000)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    train = args.output_root / "MINDsmall_train"
    dev = args.output_root / "MINDsmall_dev"
    train.mkdir(parents=True, exist_ok=True)
    dev.mkdir(parents=True, exist_ok=True)
    write_news(train / "news.tsv", 0, args.train_news, rng)
    write_news(dev / "news.tsv", 0, args.train_news + args.dev_extra_news, rng)
    start = datetime(2026, 1, 1, 0, 0, 0)
    write_behaviors(train / "behaviors.tsv", args.train_impressions,
                    args.train_news, 5000, rng, start)
    write_behaviors(dev / "behaviors.tsv", args.dev_impressions,
                    args.train_news + args.dev_extra_news, 5000, rng, start + timedelta(days=30))
    marker = (
        "SYNTHETIC_DATA=true\n"
        "This is generated test data, not MIND and not a MIND result.\n"
        "seed={}\n".format(args.seed)
    )
    (args.output_root / "SYNTHETIC_DATA.txt").write_text(marker)
    manifest = {
        "data_source": "synthetic",
        "seed": args.seed,
        "train_news": args.train_news,
        "dev_news": args.train_news + args.dev_extra_news,
        "train_impressions": args.train_impressions,
        "dev_impressions": args.dev_impressions,
        "categories": len(CATEGORIES),
    }
    (args.output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
