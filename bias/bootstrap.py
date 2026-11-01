"""Bootstrap confidence intervals for saved per-impression metric rows."""
import argparse
import csv
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

try:
    from bias.offline_metrics import compute_exposure_l1, gini
except ModuleNotFoundError:
    from offline_metrics import compute_exposure_l1, gini


def bootstrap_ci(values, statistic, samples=1000, seed=20261028):
    if not values:
        return {"mean": 0.0, "low": 0.0, "high": 0.0, "n": 0}
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is not None and statistic is statistics.mean:
        array = np.asarray(values, dtype=float)
        rng = np.random.default_rng(seed)
        estimates = rng.choice(array, size=(samples, len(array))).mean(axis=1)
        estimates.sort()
        return {
            "mean": statistics.mean(values),
            "low": float(estimates[int(0.025 * (len(estimates) - 1))]),
            "high": float(estimates[int(0.975 * (len(estimates) - 1))]),
            "n": len(values),
        }
    rng = random.Random(seed)
    estimates = []
    for _ in range(samples):
        draw = [values[rng.randrange(len(values))] for _ in values]
        estimates.append(statistic(draw))
    estimates.sort()
    return {
        "mean": statistics.mean(values),
        "low": estimates[int(0.025 * (len(estimates) - 1))],
        "high": estimates[int(0.975 * (len(estimates) - 1))],
        "n": len(values),
    }


def family_summary(rows):
    grouped = defaultdict(list)
    for row in rows:
        family = "random" if row["mapping"].startswith("random_") else "category_correlated"
        grouped[(family, row["lambda"])].append(row)
    output = []
    for (family, lambda_value), values in sorted(grouped.items()):
        record = {"family": family, "lambda": lambda_value}
        candidate_fields = ("exposure_l1", "publisher_gini", "ndcg_at_5_served", "auc", "ndcg@10")
        for field in candidate_fields:
            if any(field in r for r in values):
                numbers = [float(row[field]) for row in values if field in row]
                record[field + "_mean"] = statistics.mean(numbers)
                record[field + "_std"] = statistics.stdev(numbers) if len(numbers) > 1 else 0.0
        output.append(record)
    return output


def family_bootstrap_summary(cis):
    grouped = defaultdict(list)
    for row in cis:
        family = "random" if row["mapping"].startswith("random_") else "category_correlated"
        grouped[(family, row["lambda"], row["metric"])].append(row)
    output = []
    for (family, lambda_value, metric), records in sorted(grouped.items()):
        estimates = [r["estimate"] for r in records]
        means = [r["bootstrap_mean"] for r in records]
        output.append({
            "family": family,
            "lambda": lambda_value,
            "metric": metric,
            "estimate_mean": statistics.mean(estimates),
            "estimate_std": statistics.stdev(estimates) if len(estimates) > 1 else 0.0,
            "bootstrap_mean_mean": statistics.mean(means),
            "bootstrap_mean_std": statistics.stdev(means) if len(means) > 1 else 0.0,
            "n_mappings": len(records),
        })
    return output


def prediction_rows(path, target_shares):
    try:
        from bias.offline_metrics import compute_auc, compute_ndcg, compute_served_ndcg
    except ModuleNotFoundError:
        from offline_metrics import compute_auc, compute_ndcg, compute_served_ndcg
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            served = record.get("served_top_k", [])[:5]
            exposure = defaultdict(float)
            for position, item in enumerate(served, 1):
                group = record.get("groups", {}).get(item)
                if group:
                    exposure[group] += 1.0 / math.log2(position + 1)
            labels = [record["labels"].get(item, 0)
                      for item in record.get("ranked_candidates", [])]
            served_labels = [record["labels"].get(item, 0) for item in served]
            yield {
                "exposure": exposure,
                "auc": compute_auc(labels),
                "ndcg_at_10": compute_ndcg(labels, 10),
                "ndcg_at_5_served": compute_served_ndcg(labels, served_labels, 5),
            }


def aggregate_bootstrap(rows, target_shares, samples, seed=20261028):
    import numpy as np
    groups = sorted(set(target_shares) | {
        group for row in rows for group in row["exposure"]
    })
    group_index = {group: index for index, group in enumerate(groups)}
    matrix = np.zeros((len(rows), len(groups)), dtype=float)
    ndcg = np.zeros(len(rows), dtype=float)
    has_auc = any("auc" in r for r in rows)
    has_ndcg10 = any("ndcg_at_10" in r for r in rows)
    if has_auc:
        auc = np.zeros(len(rows), dtype=float)
    if has_ndcg10:
        ndcg10 = np.zeros(len(rows), dtype=float)
    for row_index, row in enumerate(rows):
        for group, value in row["exposure"].items():
            matrix[row_index, group_index[group]] = value
        ndcg[row_index] = row.get("ndcg_at_5_served", 0.0)
        if has_auc:
            auc[row_index] = row.get("auc", 0.0)
        if has_ndcg10:
            ndcg10[row_index] = row.get("ndcg_at_10", 0.0)
    targets = {group: float(target_shares.get(group, 0.0)) for group in groups}
    total = matrix.sum(axis=0)
    baseline_exposure = {group: total[index] for index, group in enumerate(groups)}
    baseline = {
        "exposure_l1": compute_exposure_l1(baseline_exposure, targets),
        "publisher_gini": gini(total),
        "ndcg_at_5_served": float(ndcg.mean()),
    }
    if has_auc:
        baseline["auc"] = float(auc.mean())
    if has_ndcg10:
        baseline["ndcg_at_10"] = float(ndcg10.mean())
    rng = np.random.default_rng(seed)
    estimates = {metric: [] for metric in baseline}
    batch_size = max(2, min(10, samples))
    for start in range(0, samples, batch_size):
        count = min(batch_size, samples - start)
        indices = rng.integers(0, len(rows), size=(count, len(rows)))
        exposure_samples = matrix[indices].sum(axis=1)
        for sample_index in range(count):
            exposure = {
                group: exposure_samples[sample_index, index]
                for index, group in enumerate(groups)
            }
            estimates["exposure_l1"].append(compute_exposure_l1(exposure, targets))
            estimates["publisher_gini"].append(gini(exposure.values()))
        estimates["ndcg_at_5_served"].extend(ndcg[indices].mean(axis=1).tolist())
        if has_auc:
            estimates["auc"].extend(auc[indices].mean(axis=1).tolist())
        if has_ndcg10:
            estimates["ndcg_at_10"].extend(ndcg10[indices].mean(axis=1).tolist())
    result = {}
    for metric, values in estimates.items():
        values.sort()
        result[metric] = {
            "estimate": baseline[metric],
            "bootstrap_mean": float(sum(values) / len(values)),
            "low": float(values[int(0.025 * (len(values) - 1))]),
            "high": float(values[int(0.975 * (len(values) - 1))]),
            "n": len(rows),
            "resamples": samples,
        }
    return result


def paired_ndcg_bootstrap(rows_zero, rows_five, samples, seed=20261028):
    import numpy as np
    if len(rows_zero) != len(rows_five):
        raise ValueError("lambda 0 and lambda 5 files have different row counts")
    differences = np.asarray([
        zero["ndcg_at_5_served"] - five["ndcg_at_5_served"]
        for zero, five in zip(rows_zero, rows_five)
    ], dtype=float)
    rng = np.random.default_rng(seed)
    statistics_values = []
    batch_size = 100
    for start in range(0, samples, batch_size):
        count = min(batch_size, samples - start)
        indices = rng.integers(0, len(differences), size=(count, len(differences)))
        statistics_values.extend(differences[indices].mean(axis=1).tolist())
    statistics_values.sort()
    return {
        "estimate": float(differences.mean()),
        "bootstrap_mean": float(sum(statistics_values) / len(statistics_values)),
        "low": float(statistics_values[int(0.025 * (samples - 1))]),
        "high": float(statistics_values[int(0.975 * (samples - 1))]),
        "n": len(differences),
        "resamples": samples,
    }


def bootstrap_predictions(prediction_root, target_root, samples, mappings=None, lambdas=None, seed=20261028):
    results = []
    if lambdas is not None:
        lambdas = [str(l) for l in lambdas]
    current_mapping = None
    current_zero_rows = None
    for path in sorted(Path(prediction_root).glob("*/lambda_*.jsonl")):
        mapping = path.parent.name
        if mappings and mapping not in mappings:
            continue
        lambda_val = path.stem.split("lambda_", 1)[1]
        if lambdas and lambda_val not in lambdas:
            continue
        if mapping != current_mapping:
            current_mapping = mapping
            current_zero_rows = None
        target_path = Path(target_root) / "target_shares_{}.json".format(mapping)
        targets = json.loads(target_path.read_text(encoding="utf-8"))
        rows = list(prediction_rows(path, targets))
        if lambda_val == "0.0":
            current_zero_rows = rows
        for metric, result in aggregate_bootstrap(rows, targets, samples, seed=seed).items():
            results.append({
                "mapping": mapping,
                "lambda": lambda_val,
                "metric": metric,
                **result,
            })
        if path.name == "lambda_5.0.jsonl" and (lambdas is None or "0.0" in lambdas):
            zero_path = path.parent / "lambda_0.0.jsonl"
            zero_rows = current_zero_rows
            if zero_rows is None and zero_path.exists():
                zero_rows = list(prediction_rows(zero_path, targets))
            if zero_rows is not None:
                paired = paired_ndcg_bootstrap(zero_rows, rows, samples, seed=seed)
                results.append({
                    "mapping": mapping,
                    "lambda": "0.0_to_5.0",
                    "metric": "ndcg_at_5_served_difference",
                    **paired,
                })
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/processed/bias_summary.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/processed/analysis/bootstrap_summary.json"))
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--predictions-root", type=Path)
    parser.add_argument("--target-root", type=Path,
                        default=Path("data/processed/model_tables"))
    parser.add_argument("--mappings", nargs="*")
    parser.add_argument("--lambdas", nargs="*", default=["0.0", "5.0"])
    parser.add_argument("--seed", type=int, default=20261028)
    args = parser.parse_args()
    if args.predictions_root:
        cis = bootstrap_predictions(
            args.predictions_root, args.target_root, args.samples,
            args.mappings, args.lambdas, seed=args.seed
        )
        result = {
            "bootstrap_cis": cis,
            "family_summary": family_bootstrap_summary(cis),
        }
    else:
        with args.input.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        result = {"rows": rows, "family_summary": family_summary(rows)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("bootstrap_rows={}".format(len(result.get("bootstrap_cis", []))))


if __name__ == "__main__":
    main()
