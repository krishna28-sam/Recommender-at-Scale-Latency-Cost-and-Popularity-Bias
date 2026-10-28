"""Small, streaming-friendly MIND TSV inspection; outputs measured JSON only."""
import argparse
import json
from collections import Counter
from pathlib import Path


def news_stats(path: Path) -> dict:
    categories, subcategories = Counter(), Counter()
    count = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 8:
                raise ValueError("{}: expected 8 fields, got {}".format(path, len(fields)))
            count += 1
            categories[fields[1]] += 1
            subcategories[fields[2]] += 1
    return {"news_rows": count, "categories": len(categories), "subcategories": len(subcategories),
            "top_categories": categories.most_common(10)}


def behavior_stats(path: Path) -> dict:
    count = clicks = impressions = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) != 5:
                raise ValueError("{}: expected 5 fields, got {}".format(path, len(fields)))
            count += 1
            for candidate in fields[4].split():
                impressions += 1
                clicks += candidate.endswith("-1")
    return {"behavior_rows": count, "impressions": impressions, "clicks": clicks,
            "click_rate": clicks / impressions if impressions else None}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--dev", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    marker_dir = args.train.parent.parent
    manifest_path = marker_dir / "manifests" / "movielens_manifest.json"
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8") as handle:
            data_source = json.loads(handle.read()).get("data_source", "movielens_converted")
    else:
        data_source = "synthetic" if (marker_dir / "SYNTHETIC_DATA.txt").exists() else (
            "movielens_converted" if (marker_dir / "MOVIELENS_DERIVED_DATA.txt").exists() else "real")
    result = {"data_source": data_source}
    for split, directory in (("train", args.train), ("dev", args.dev)):
        result[split] = {
            "news": news_stats(directory / "news.tsv"),
            "behaviors": behavior_stats(directory / "behaviors.tsv"),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
