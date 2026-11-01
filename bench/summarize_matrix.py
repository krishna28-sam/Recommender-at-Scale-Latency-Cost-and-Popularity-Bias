"""Per-config summary of the 42 matrix runs. Reads bench/results/<config>_r<rate>_rep<n>.csv only."""
import csv, re, statistics
from pathlib import Path

RESULTS = Path("bench/results")
OUT = Path("data/processed/analysis")
PAT = re.compile(r"^(?P<config>.+)_r(?P<rate>1000|2000)_rep(?P<rep>[123])\.csv$")
WINDOW = 60.0
CPU_PRICE = 0.0001    # ASSUMED, config/model.yaml (illustrative, not a quote)
GB_S_PRICE = 0.00001  # ASSUMED, config/model.yaml
NUM = ["achieved_rate", "output_throughput", "latency_p50_app", "latency_p95_app", "latency_p99_app",
       "latency_p50_kafka", "latency_p95_kafka", "latency_p99_kafka", "lag_trend", "loss",
       "cpu_seconds", "peak_memory_bytes", "drain_seconds", "backlog_at_window_end"]
METRICS = ["latency_p50_kafka", "latency_p95_kafka", "latency_p99_kafka", "latency_p50_app",
           "output_throughput", "lag_trend", "drain_seconds", "backlog_at_window_end",
           "cpu_seconds", "cpu_per_1k_events", "peak_memory_bytes", "cost_per_1m_events_assumed"]
ORDER = ["spark-default", "spark-1s", "flink-p1", "flink-p1-tuned", "flink-p2",
         "spark-default-rerank", "flink-p1-rerank"]


def ms(values):
    return statistics.mean(values), (statistics.stdev(values) if len(values) > 1 else 0.0)


def load():
    cells, problems, total = {}, [], 0
    for path in sorted(RESULTS.glob("*.csv")):
        m = PAT.match(path.name)
        if not m:
            continue
        with path.open(encoding="utf-8") as handle:
            row = next(csv.DictReader(handle))
        rec = {k: float(row[k]) for k in NUM}
        events = rec["achieved_rate"] * WINDOW
        rec["cpu_per_1k_events"] = rec["cpu_seconds"] / (events / 1000.0)
        cost = rec["cpu_seconds"] * CPU_PRICE + rec["peak_memory_bytes"] / 1e9 * WINDOW * GB_S_PRICE
        rec["cost_per_1m_events_assumed"] = cost / events * 1e6
        if row["status"] != "PASS" or row["producer_bound"] != "false" or rec["loss"] > 0:
            problems.append(path.name)
        cells.setdefault((m["config"], int(m["rate"])), []).append(rec)
        total += 1
    return cells, problems, total


def main():
    cells, problems, total = load()
    print("runs_read={} (expected 42) problems={}".format(total, problems or "none"))
    for key, recs in cells.items():
        if len(recs) != 3:
            print("WARN {} has n={}".format(key, len(recs)))
    OUT.mkdir(parents=True, exist_ok=True)
    keys = sorted(cells, key=lambda k: (ORDER.index(k[0]) if k[0] in ORDER else 99, k[1]))
    with (OUT / "matrix_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        w = csv.writer(handle)
        w.writerow(["config", "rate", "n"] + [m + s for m in METRICS for s in ("_mean", "_std")])
        for k in keys:
            row = [k[0], k[1], len(cells[k])]
            for m in METRICS:
                row += list(ms([r[m] for r in cells[k]]))
            w.writerow([round(x, 4) if isinstance(x, float) else x for x in row])
    print("\nconfig rate | p50k p95k p99k (ms) | thr ev/s | backlog | drain s | cpu s | cpu s/1k ev | cost/1M (ASSUMED)")
    for k in keys:
        c = cells[k]
        f = lambda m, d=1: "{:.{d}f}±{:.{d}f}".format(*ms([r[m] for r in c]), d=d)
        print("{:22s} {:5d} | {} {} {} | {} | {} | {} | {} | {} | {}".format(
            k[0], k[1], f("latency_p50_kafka", 0), f("latency_p95_kafka", 0), f("latency_p99_kafka", 0),
            f("output_throughput", 0), f("backlog_at_window_end", 0), f("drain_seconds"),
            f("cpu_seconds"), f("cpu_per_1k_events", 3), f("cost_per_1m_events_assumed", 4)))
    print("\nRERANK OVERHEAD (lambda 0.6 vs 0.0, same engine; mean over 3 reps; n=3 so read with the std)")
    rows = [["engine", "rate", "metric", "base_mean", "base_std", "rerank_mean", "rerank_std", "pct_change"]]
    for base, rer in (("spark-default", "spark-default-rerank"), ("flink-p1", "flink-p1-rerank")):
        for rate in (1000, 2000):
            for m in ("latency_p50_kafka", "latency_p95_kafka", "output_throughput",
                      "backlog_at_window_end", "cpu_per_1k_events"):
                b, r = ms([x[m] for x in cells[(base, rate)]]), ms([x[m] for x in cells[(rer, rate)]])
                pct = (r[0] - b[0]) / b[0] * 100 if b[0] else 0.0
                rows.append([base, rate, m, round(b[0], 3), round(b[1], 3), round(r[0], 3), round(r[1], 3), round(pct, 2)])
                print("{:14s} {:5d} {:22s} base {:10.2f}±{:8.2f} rerank {:10.2f}±{:8.2f} change {:+6.1f}%".format(
                    base, rate, m, b[0], b[1], r[0], r[1], pct))
    with (OUT / "rerank_overhead.csv").open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows)
    print("\nwrote {}/matrix_summary.csv and rerank_overhead.csv".format(OUT))


if __name__ == "__main__":
    main()
