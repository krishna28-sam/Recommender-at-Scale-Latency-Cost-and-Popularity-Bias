"""Join saved bias and benchmark summaries into a mitigation-cost table."""
import argparse
import csv
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bias", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.bias.open(newline="", encoding="utf-8") as handle:
        bias_rows = list(csv.DictReader(handle))
    with args.benchmark.open(newline="", encoding="utf-8") as handle:
        benchmark_rows = list(csv.DictReader(handle))
    by_key = {(row["engine"], row["lambda"]): row for row in benchmark_rows}
    fields = ["engine", "lambda", "served_ndcg5_change", "added_p95_latency_ms",
              "throughput_drop", "extra_cpu_seconds", "extra_cost_assumed"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in bias_rows:
            key = (row.get("engine", ""), row["lambda"])
            benchmark = by_key.get(key)
            if benchmark is None:
                continue
            writer.writerow({field: row.get(field, benchmark.get(field, "NOT RUN"))
                             for field in fields})
    print("mitigation_cost=NOT RUN: requires final benchmark summary and stream metrics")


if __name__ == "__main__":
    main()
