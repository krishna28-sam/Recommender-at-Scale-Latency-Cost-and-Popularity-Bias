"""Create dev predictions for every lambda and synthetic publisher mapping."""
import argparse
import csv
import json
import multiprocessing as mp
from collections import defaultdict
from pathlib import Path

import yaml

from recsys.reranker import rerank
from recsys.scorer import rank_candidates


def parse_csv_args(value, default):
    if value is None:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def load_behaviors(path, limit=None):
    rows = []
    with path.open(encoding="utf-8", newline="") as handle:
        for index, row in enumerate(csv.reader(handle, delimiter="\t")):
            if len(row) != 5:
                continue
            if limit is not None and len(rows) >= limit:
                break
            labels = {}
            candidates = []
            for token in row[4].split():
                item_id, label = token.rsplit("-", 1)
                labels[item_id] = int(label)
                candidates.append(item_id)
            rows.append({
                "impression_id": row[0],
                "user_id": row[1],
                "time": row[2],
                "history": row[3].split() if row[3] else [],
                "candidates": candidates,
                "labels": labels,
            })
    return rows


def compute_scores_for_impression(impression, stats, categories, weights):
    _, full = rank_candidates(
        impression["candidates"],
        impression["history"],
        stats,
        categories,
        len(impression["candidates"]),
        weights,
    )
    assert len([row["news_id"] for row in full]) == len(impression["candidates"])
    return {
        "impression_id": impression["impression_id"],
        "ranked_candidates": [row["news_id"] for row in full],
        "scores": {row["news_id"]: row["score"] for row in full},
        "labels": impression["labels"],
        "groups": {},
    }


def process_one(mapping_path, lambda_value, behaviors, stats, categories, weights, target_dir, output_dir, config):
    mapping_name = mapping_path.stem
    output = output_dir / mapping_name / "lambda_{}.jsonl".format(lambda_value)
    if output.exists():
        return output
    mapping = {}
    with mapping_path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            mapping[row["news_id"]] = row["synthetic_publisher"]
    target_path = target_dir / "target_shares_{}.json".format(mapping_name)
    targets = json.loads(target_path.read_text())
    state = {"exposure": defaultdict(float), "total": 0.0}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for impression in behaviors:
            base = compute_scores_for_impression(impression, stats, categories, weights)
            assert len(base["ranked_candidates"]) == len(impression["candidates"]), (
                "candidate mismatch for impression {}".format(impression["impression_id"]))
            served = rerank(
                [
                    {"news_id": item_id, "score": base["scores"][item_id], "smoothed_ctr": 0.0,
                     "popularity": 0.0, "group": mapping.get(item_id)}
                    for item_id in base["ranked_candidates"]
                ],
                {item_id: mapping.get(item_id) for item_id in impression["candidates"]},
                targets,
                config["top_k"],
                float(lambda_value),
                state=state,
            )
            record = {
                "impression_id": impression["impression_id"],
                "ranked_candidates": base["ranked_candidates"],
                "scores": base["scores"],
                "labels": base["labels"],
                "groups": {item_id: mapping.get(item_id) for item_id in impression["candidates"]},
                "served_top_k": [item["news_id"] for item in served],
            }
            handle.write(json.dumps(record) + "\n")
    size = output.stat().st_size
    print("wrote {} bytes={}".format(output, size))
    return output


def process_bundle(args):
    mapping_path, lambda_value, behaviors, stats, categories, weights, target_dir, output_dir, config = args
    return process_one(mapping_path, lambda_value, behaviors, stats, categories, weights, target_dir, output_dir, config)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--behaviors", type=Path, required=True)
    parser.add_argument("--item-stats", type=Path, required=True)
    parser.add_argument("--target-dir", type=Path, required=True)
    parser.add_argument("--train-news", type=Path, required=True)
    parser.add_argument("--dev-news", type=Path, required=True)
    parser.add_argument("--mapping-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/model.yaml"))
    parser.add_argument("--limit-impressions", type=int, default=None)
    parser.add_argument("--mappings", type=str, default=None)
    parser.add_argument("--lambdas", type=str, default=None)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    config = yaml.safe_load(args.config.read_text())["model"]
    stats = json.loads(args.item_stats.read_text())
    categories = {}
    for news_path in (args.train_news, args.dev_news):
        with news_path.open(encoding="utf-8") as handle:
            for row in csv.reader(handle, delimiter="\t"):
                if len(row) == 8:
                    categories[row[0]] = row[1]
    behaviors = sorted(
        load_behaviors(args.behaviors, limit=args.limit_impressions),
        key=lambda row: (row["time"], row["impression_id"]),
    )
    mapping_names = parse_csv_args(args.mappings, None)
    mapping_paths = []
    for path in sorted(args.mapping_dir.glob("*.tsv")):
        if mapping_names is None or path.stem in mapping_names:
            mapping_paths.append(path)
    if not mapping_paths:
        raise SystemExit("No mapping files matched --mappings={}".format(args.mappings))
    lambda_values = parse_csv_args(args.lambdas, config["offline_reranker_lambdas"])
    tasks = []
    for mapping_path in mapping_paths:
        for lambda_value in lambda_values:
            output = args.output_dir / mapping_path.stem / "lambda_{}.jsonl".format(lambda_value)
            if output.exists():
                continue
            tasks.append((mapping_path, lambda_value))
    if not tasks:
        print("skipped all existing outputs under {}".format(args.output_dir))
        return

    bundle_tasks = [
        (mapping_path, lambda_value, behaviors, stats, categories, config["weights"],
         args.target_dir, args.output_dir, config)
        for mapping_path, lambda_value in tasks
    ]
    with mp.Pool(processes=min(args.workers, len(bundle_tasks))) as pool:
        for _ in pool.imap_unordered(process_bundle, bundle_tasks):
            pass


if __name__ == "__main__":
    main()
