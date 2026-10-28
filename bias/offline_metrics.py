"""Compute full-list ranking and served-top-5 publisher exposure metrics."""
import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path


def dcg(labels, k):
    return sum(label / math.log2(index + 2) for index, label in enumerate(labels[:k]))


def gini(values):
    values = sorted(float(value) for value in values)
    total = sum(values)
    if not values or total == 0:
        return 0.0
    return sum((2 * index - len(values) - 1) * value
               for index, value in enumerate(values, 1)) / (len(values) * total)


def compute_auc(labels):
    positives = [idx for idx, value in enumerate(labels) if value == 1]
    negatives = [idx for idx, value in enumerate(labels) if value == 0]
    if not positives or not negatives:
        return 0.5
    pairs = 0
    total = 0
    for pos in positives:
        for neg in negatives:
            total += 1
            if pos < neg:
                pairs += 1
    return pairs / float(total)


def compute_mrr(labels):
    for index, value in enumerate(labels, 1):
        if value == 1:
            return 1.0 / float(index)
    return 0.0


def compute_ndcg(labels, k):
    if k <= 0:
        return 0.0
    ideal = sorted(labels, reverse=True)[:k]
    return dcg(labels[:k], k) / float(dcg(ideal, k)) if dcg(ideal, k) else 0.0


def iter_prediction_files(predictions):
    if predictions.is_file():
        yield predictions
    else:
        for path in sorted(predictions.rglob("*.jsonl")):
            if path.is_file():
                yield path


def summarize_prediction_file(path, catalog, item_stats, train_known, output_dir):
    mapping_name = path.parent.name
    lambda_name = path.stem.split("lambda_", 1)[1]
    exposure = Counter()
    item_exposure = Counter()
    category_exposure = Counter()
    aucs, mrrs, ndcg5, ndcg10 = [], [], [], []
    cold_aucs, cold_ndcg5, cold_ndcg10, cold_mrrs = [], [], [], []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            labels = [record["labels"].get(item, 0) for item in record["ranked_candidates"]]
            scores = [record["scores"][item] for item in record["ranked_candidates"]]
            aucs.append(compute_auc(labels))
            mrrs.append(compute_mrr(labels))
            ndcg5.append(compute_ndcg(labels, 5))
            ndcg10.append(compute_ndcg(labels, 10))
            cold_items = [item for item in record["ranked_candidates"] if item not in train_known]
            if cold_items:
                cold_labels = [record["labels"].get(item, 0) for item in cold_items]
                cold_aucs.append(compute_auc(cold_labels))
                cold_mrrs.append(compute_mrr(cold_labels))
                cold_ndcg5.append(compute_ndcg(cold_labels, 5))
                cold_ndcg10.append(compute_ndcg(cold_labels, 10))
            for rank, item in enumerate(record.get("served_top_k", [])[:5], 1):
                group = record["groups"].get(item)
                if not group:
                    continue
                value = 1.0 / math.log2(rank + 1)
                exposure[group] += value
                item_exposure[item] += value
                category_exposure[catalog.get(item, "unknown")] += value
    long_tail_cutoff = sorted(item_stat["impressions"] for item_stat in item_stats.values())
    cutoff = long_tail_cutoff[len(long_tail_cutoff) // 2] if long_tail_cutoff else 0
    catalog_counts = Counter(catalog.values())
    total_catalog = float(sum(catalog_counts.values()) or 1)
    total_exposure = float(sum(exposure.values()) or 1)
    result = {
        "auc": sum(aucs) / len(aucs) if aucs else 0.0,
        "mrr": sum(mrrs) / len(mrrs) if mrrs else 0.0,
        "ndcg@5": sum(ndcg5) / len(ndcg5) if ndcg5 else 0.0,
        "ndcg@10": sum(ndcg10) / len(ndcg10) if ndcg10 else 0.0,
        "cold_auc": sum(cold_aucs) / len(cold_aucs) if cold_aucs else 0.0,
        "cold_mrr": sum(cold_mrrs) / len(cold_mrrs) if cold_mrrs else 0.0,
        "cold_ndcg@5": sum(cold_ndcg5) / len(cold_ndcg5) if cold_ndcg5 else 0.0,
        "cold_ndcg@10": sum(cold_ndcg10) / len(cold_ndcg10) if cold_ndcg10 else 0.0,
        "publisher_gini": gini(exposure.values()),
        "item_gini": gini(item_exposure.values()),
        "category_gini": gini(category_exposure.values()),
        "catalog_coverage": len(item_exposure) / float(len(catalog) or 1),
        "long_tail_share": sum(
            value for item, value in item_exposure.items()
            if item_stats.get(item, {}).get("impressions", 0) <= cutoff
        ) / float(total_exposure or 1),
        "arp": sum(item_stats.get(item, {}).get("popularity", 0.0) * value
                   for item, value in item_exposure.items()) / float(total_exposure or 1),
        "publisher_exposure_share": {group: value / float(total_exposure or 1)
                                     for group, value in exposure.items()},
        "train_catalog_share": {group: value / float(total_catalog or 1)
                                for group, value in catalog_counts.items()},
        "exposure_vs_catalog_share": {
            group: exposure[group] / float(total_exposure or 1) - catalog_counts[group] / float(total_catalog or 1)
            for group in set(exposure) | set(catalog_counts)
        },
    }
    return mapping_name, lambda_name, result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--behaviors", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--item-stats", type=Path, required=True)
    parser.add_argument("--train-news", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    item_stats = json.loads(args.item_stats.read_text())
    catalog = {}
    with args.train_news.open(encoding="utf-8") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if len(row) == 8:
                catalog[row[0]] = row[1]
    train_known = set()
    with args.behaviors.open(encoding="utf-8") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if len(row) != 5:
                continue
            for token in row[3].split():
                if token.startswith("N"):
                    train_known.add(token)
            for token in row[4].split():
                item_id, label = token.rsplit("-", 1)
                if label == "1":
                    train_known.add(item_id)

    all_results = {}
    for prediction_file in iter_prediction_files(args.predictions):
        mapping_name, lambda_name, result = summarize_prediction_file(
            prediction_file, catalog, item_stats, train_known, args.output.parent)
        all_results.setdefault(mapping_name, {})[lambda_name] = result

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(all_results, indent=2) + "\n")

    csv_rows = []
    for mapping_name, lambdas in all_results.items():
        for lambda_name, result in lambdas.items():
            row = {"mapping": mapping_name, "lambda": lambda_name}
            row.update({k: v for k, v in result.items() if isinstance(v, (int, float, str))})
            csv_rows.append(row)
    csv_path = args.output.with_suffix(".csv")
    fieldnames = ["mapping", "lambda"] + sorted({k for row in csv_rows for k in row if k not in {"mapping", "lambda"}})
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in csv_rows:
            writer.writerow(row)

    print("wrote {} and {}".format(args.output, csv_path))
    print("mapping\tlambda\tauc\tndcg@10\tpublisher_gini")
    for mapping_name, lambdas in all_results.items():
        for lambda_name, result in lambdas.items():
            print("{}\t{}\t{:.6f}\t{:.6f}\t{:.6f}".format(
                mapping_name, lambda_name, result["auc"], result["ndcg@10"], result["publisher_gini"]))


if __name__ == "__main__":
    main()
