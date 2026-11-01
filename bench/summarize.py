"""Summarize only saved non-SMOKE benchmark CSV files."""
import argparse
import csv
import statistics
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    rows = []
    for path in sorted(args.directory.glob("*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("flag") != "SMOKE" and str(row.get("status", "")).upper() not in {"DEBUG", "FAILED"}:
                    rows.append(row)
    if not rows:
        print("summary=NOT RUN: no non-SMOKE raw CSV files")
        return 0
    for field in ("latency_p50_ms", "latency_p95_ms", "latency_p99_ms",
                  "throughput_events_s", "cpu_seconds", "cost_assumed",
                  "drain_seconds", "backlog_at_window_end"):
        values = [float(row[field]) for row in rows
                  if row.get(field) not in (None, "", "NOT RUN")]
        if values:
            print("{} mean={:.6f} std={:.6f} n={}".format(
                field, statistics.mean(values),
                statistics.stdev(values) if len(values) > 1 else 0.0, len(values)))
        else:
            print("{}=NOT RUN".format(field))
    suspicious = [
        row.get("run_id", "unknown") for row in rows
        if float(row.get("loss_count", "0")) > 0
        or float(row.get("latency_p50_ms", "1")) <= 0
        or row.get("producer_bound", "").lower() == "true"
    ]
    print("suspicious_results={}".format(",".join(suspicious) if suspicious else "none"))


if __name__ == "__main__":
    main()
