"""Capacity-probe entry point with machine-safety preflight.

The probe is deliberately not run during repository preparation. When invoked
through ``make probe``, this module performs the requested preflight and then
delegates each measured case to the benchmark runner.
"""
import argparse
import os
import subprocess
import time
import csv
import re
from pathlib import Path


RATES = (100, 250, 500, 1000, 2000, 4000)
CONFIGS = (
    ("spark-default", "spark", 0.0),
    ("spark-1s", "spark", 0.0),
    ("flink-p1", "flink", 0.0),
    ("flink-p1-tuned", "flink", 0.0),
    ("flink-p2", "flink", 0.0),
    ("spark-default-rerank", "spark", 0.6),
    ("flink-p1-rerank", "flink", 0.6),
)
OUTPUT_COLUMNS = (
    "config lambda target_rate achieved_rate producer_bound "
    "output_throughput latency_p50_app latency_p95_app latency_p99_app "
    "latency_p50_kafka latency_p95_kafka latency_p99_kafka lag_trend "
    "loss cpu_seconds peak_memory_bytes cpu_method status"
)
CSV_COLUMNS = tuple(OUTPUT_COLUMNS.split())


def step_specs(configs):
    return [
        {
            "config": name,
            "engine": engine,
            "settings": engine_settings(name, engine, lambda_value),
            "partitions": 2,
            "lambda": lambda_value,
            "target_rate": rate,
            "duration_seconds": 30,
        }
        for name, engine, lambda_value in configs
        for rate in RATES
    ]


def completed_steps(csv_path):
    if not csv_path.exists():
        return set()
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return {
            (row["config"], row["target_rate"])
            for row in csv.DictReader(handle)
            if row.get("status") not in {"DEBUG", "FAILED"}
        }


def append_step_result(report_path, csv_path, row):
    report_path.parent.mkdir(parents=True, exist_ok=True)
    existing_rows = []
    csv_exists = csv_path.exists() and csv_path.stat().st_size > 0
    if csv_exists:
        with csv_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            existing_rows = list(reader)
            csv_exists = reader.fieldnames == list(CSV_COLUMNS)
    new_rows = []
    replaced = False
    for r in existing_rows:
        if (r.get("config"), str(r.get("target_rate"))) == (row.get("config"), str(row.get("target_rate"))):
            new_rows.append({field: row.get(field, "") for field in CSV_COLUMNS})
            replaced = True
        else:
            new_rows.append(r)
    if not replaced:
        new_rows.append({field: row.get(field, "") for field in CSV_COLUMNS})
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for r in new_rows:
            r.setdefault("status", "PASS")
            writer.writerow({field: r.get(field, "") for field in CSV_COLUMNS})
    with report_path.open("a", encoding="utf-8") as handle:
        handle.write("result " + " ".join(
            "{}={}".format(field, row.get(field, "")) for field in CSV_COLUMNS
        ) + "\n")


def step_environment(spec):
    env = os.environ.copy()
    env.update({
        "BOOTSTRAP_SERVERS": "kafka:9092",
        "RUN_ID": "probe-{}-{}".format(spec["config"], spec["target_rate"]),
        "MAPPING": "category_404",
        "LAMBDA": str(spec["lambda"]),
        "PRODUCER_RATE": str(spec["target_rate"]),
        "PRODUCER_SECONDS": str(spec["duration_seconds"]),
        "KAFKA_PARTITIONS": str(spec["partitions"]),
        "ENGINE_MODE": "score",
    })
    if spec["engine"] == "flink":
        env["FLINK_PARALLELISM"] = str(
            2 if spec["config"] == "flink-p2" else 1)
        if spec["config"] == "flink-p1-tuned":
            env["FLINK_BUNDLE_TIME_MS"] = "50"
        else:
            env.pop("FLINK_BUNDLE_TIME_MS", None)
    if spec["config"] in {"spark-1s"}:
        env["SPARK_TRIGGER"] = "1 second"
    return env


def parse_only(value):
    match = re.fullmatch(r"([^:]+):([0-9]+(?:\.[0-9]+)?)", value)
    if not match:
        raise argparse.ArgumentTypeError("--only must be <config>:<rate>")
    return match.group(1), float(match.group(2))


def base_row(spec, status="DEBUG"):
    row = {
        "config": spec["config"],
        "lambda": spec["lambda"],
        "target_rate": spec["target_rate"],
        "status": status,
    }
    return row


def is_saturated(row):
    if str(row.get("status", "")).upper() in {"DEBUG", "FAILED"}:
        return False
    if str(row.get("producer_bound", "")).lower() == "true":
        return False
    try:
        return (
            float(row["lag_trend"]) > 20.0
            or float(row["output_throughput"]) <
            float(row["achieved_rate"]) * 0.95
            or float(row.get("loss", 0.0)) > 0.0
        )
    except (KeyError, TypeError, ValueError):
        return False


def check_row_flags(row):
    """Flags anomalies: throughput > 105% of achieved rate or non-positive latencies."""
    flags = []
    try:
        achieved = float(row.get("achieved_rate", 0))
        output_tp = float(row.get("output_throughput", 0))
        if achieved > 0 and output_tp > achieved * 1.05:
            flags.append("output_throughput_exceeds_achieved_rate_by_over_5pct")
        elif achieved <= 0 and output_tp > 0:
            flags.append("output_throughput_exceeds_achieved_rate_by_over_5pct")
    except (KeyError, TypeError, ValueError):
        pass

    latency_keys = [k for k in row if k.startswith("latency_")]
    if not latency_keys:
        latency_keys = [
            "latency_p50_app", "latency_p95_app", "latency_p99_app",
            "latency_p50_kafka", "latency_p95_kafka", "latency_p99_kafka",
        ]
    for key in latency_keys:
        val = row.get(key)
        if val not in (None, ""):
            try:
                if float(val) <= 0:
                    flags.append("{}_non_positive".format(key))
            except (TypeError, ValueError):
                pass
    return flags


def print_rate_summary(csv_path_or_rows, configs):
    if isinstance(csv_path_or_rows, (str, Path)):
        csv_path = Path(csv_path_or_rows)
        rows = []
        if csv_path.exists():
            with csv_path.open(newline="", encoding="utf-8") as handle:
                rows = [row for row in csv.DictReader(handle)
                        if str(row.get("status", "")).upper() not in {"DEBUG", "FAILED"}
                        and str(row.get("producer_bound", "")).lower() != "true"]
    else:
        rows = [row for row in csv_path_or_rows
                if str(row.get("status", "")).upper() not in {"DEBUG", "FAILED"}
                and str(row.get("producer_bound", "")).lower() != "true"]

    flagged_rows = []
    for row in rows:
        reasons = check_row_flags(row)
        if reasons:
            flagged_rows.append((row, reasons))
            print("FLAG config={} target_rate={} reason={}".format(
                row.get("config"), row.get("target_rate"), ",".join(reasons)))

    summary_saturation = {}
    for config, _, _ in configs:
        config_rows = [row for row in rows if row["config"] == config]
        saturated_rates = sorted(
            int(float(row["target_rate"])) for row in config_rows if is_saturated(row))
        rate_val = saturated_rates[0] if saturated_rates else "NONE"
        summary_saturation[config] = rate_val
        print("saturation_rate config={} rate={}".format(config, rate_val))

    zero_rows = [row for row in rows
                 if float(row["lambda"]) == 0.0]
    zero_saturation = [int(float(row["target_rate"])) for row in zero_rows
                       if is_saturated(row)
                       and str(row.get("producer_bound", "")).lower() != "true"]
    high = min(zero_saturation) if zero_saturation else "NONE"
    low = "NONE"
    if zero_saturation:
        candidate = min(zero_saturation) * 0.70
        low = min(RATES, key=lambda rate: abs(rate - candidate))
        rerank_rows = [row for row in rows if float(row["lambda"]) == 0.6]
        while low > min(RATES) and any(
                is_saturated(row) and int(float(row["target_rate"])) == low
                for row in rerank_rows):
            low = RATES[max(0, RATES.index(low) - 1)]
    print("proposed_low_rate={}".format(low))
    print("proposed_high_rate={}".format(high))
    return {
        "saturation_rates": summary_saturation,
        "proposed_low_rate": low,
        "proposed_high_rate": high,
        "flagged_rows": flagged_rows,
    }


def engine_settings(name, engine, lambda_value):
    if name == "spark-default":
        return "trigger=default spark_master=local[2]"
    if name == "spark-1s":
        return "trigger=1s spark_master=local[2]"
    if name in {"flink-p1", "flink-p1-tuned"}:
        return "parallelism=1"
    if name == "flink-p2":
        return "parallelism=2"
    if name == "spark-default-rerank":
        return "trigger=default spark_master=local[2]"
    return "parallelism=1"


def dry_run(configs):
    print("DRY_RUN=TRUE")
    print("partitions=2")
    print("duration_seconds=30")
    print("environment=BOOTSTRAP_SERVERS and MIND_USER_HASH_SALT inherited by docker compose engine and producer containers")
    print("restart_policy=restart_cleanly: every step deletes and recreates fresh two-partition topics; completed steps are not resumed")
    print("python=make probe invokes $(PYTHON), default python3; activate .venv so python3 resolves to .venv/bin/python3")
    print("output_columns={}".format(OUTPUT_COLUMNS))
    print("latency_window=exclude the first 5 seconds of every 30-second step from latency statistics")
    print("saturation_rule=saturated if lag slope > 1 percent of target rate per second OR output throughput < 95 percent of achieved producer rate OR loss > 0")
    print("low_rate_rule=70 percent of the lowest saturation rate across all lambda-0 configurations, rounded to an existing ramp rate or nearest 50; it must also be non-saturated for both lambda-0.6 configurations")
    print("high_rate_rule=lowest ramp rate that saturates at least one engine and is not producer-bound")
    print("persistence=append each completed result immediately to logs/probe_report.txt and logs/probe_report.csv; on restart skip matching config and target_rate rows")
    for spec in step_specs(configs):
        print("step config={} engine={} settings={} partitions={} lambda={} target_rate={} duration_seconds={}".format(
            spec["config"], spec["engine"], spec["settings"], spec["partitions"],
            spec["lambda"], spec["target_rate"], spec["duration_seconds"]))
    print("estimated_total_wall_seconds={} ({} steps x 55 seconds; topic and engine startup/drain overhead not yet measured for the probe)".format(
        estimated_wall_seconds(configs), len(step_specs(configs))))


def machine_state():
    uptime = subprocess.check_output(["uptime"], text=True).strip()
    memory = subprocess.check_output(["free", "-h"], text=True).strip()
    with open("/proc/loadavg", encoding="utf-8") as handle:
        load = float(handle.read().split()[0])
    with open("/proc/meminfo", encoding="utf-8") as handle:
        swap = {line.split(":")[0]: int(line.split()[1])
                for line in handle if line.startswith(("SwapTotal:", "SwapFree:"))}
    swap_used_mib = (swap["SwapTotal"] - swap["SwapFree"]) / 1024
    print(uptime)
    print(memory)
    print("swap_used_mib={:.1f}".format(swap_used_mib))
    print("load_average_1m={:.2f}".format(load))
    return load, swap_used_mib


def estimated_wall_seconds(configs=None):
    if configs is None:
        configs = CONFIGS
    return len(configs) * len(RATES) * 55


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=("spark", "flink"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("logs/probe_report.txt"))
    parser.add_argument("--only", type=parse_only)
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--stop-on-error", action=argparse.BooleanOptionalAction,
                        default=True)
    args = parser.parse_args()
    if args.engine:
        configs = [config for config in CONFIGS if config[1] == args.engine]
    else:
        configs = CONFIGS
    print("rates={}".format(",".join(str(rate) for rate in RATES)))
    if args.dry_run:
        dry_run(configs)
        return 0
    if not args.execute:
        print("capacity_probe=NOT RUN")
        return 0
    if args.only:
        configs = [config for config in configs if config[0] == args.only[0]]
        if not configs or args.only[1] not in RATES:
            parser.error("--only does not name a configured rate")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    csv_output = args.output.with_suffix(".csv")
    done = completed_steps(csv_output)
    report_exists = args.output.exists() and args.output.stat().st_size
    with args.output.open("a", encoding="utf-8") as report:
        if not report_exists:
            report.write("CAPACITY PROBE\n")
            report.write("schema={}\n".format(OUTPUT_COLUMNS))
            report.write("csv_output={}\n".format(csv_output))
        if args.skip_preflight:
            print("PREFLIGHT SKIPPED - NOT A VALID MEASUREMENT")
            report.write("PREFLIGHT SKIPPED - NOT A VALID MEASUREMENT\n")
        else:
            load, swap = machine_state()
            if swap > 500 or load > 1.0:
                raise SystemExit(
                    "ABORT: preflight limit exceeded; load_average_1m={:.2f} "
                    "swap_used_mib={:.1f}".format(load, swap))
            report.write("preflight=PASS\n")
        started = time.monotonic()
        selected = step_specs(configs)
        if args.only:
            selected = [spec for spec in selected
                        if spec["target_rate"] == args.only[1]]
        for spec in selected:
            key = (spec["config"], str(spec["target_rate"]))
            if not args.only and key in done:
                print("SKIP completed config={} target_rate={}".format(*key))
                continue
            print("step config={} target_rate={}".format(
                spec["config"], spec["target_rate"]))
            row = base_row(spec, "DEBUG" if args.skip_preflight else "FAILED")
            try:
                try:
                    from bench.run import run_probe_step
                except ModuleNotFoundError:
                    from run import run_probe_step
                row.update(run_probe_step(spec))
                if args.skip_preflight:
                    row["status"] = "DEBUG"
                report.flush()
                append_step_result(args.output, csv_output, row)
                print("step status={} config={} target_rate={}".format(
                    "DEBUG" if args.skip_preflight else "PASS",
                    spec["config"], spec["target_rate"]))
            except Exception as exc:
                print("step={} command=probe exit_code=1 stderr={}".format(
                    spec["config"], exc))
                report.flush()
                append_step_result(args.output, csv_output, row)
                if args.stop_on_error:
                    raise
        print("total_wall_seconds={:.3f}".format(time.monotonic() - started))
        if not args.only:
            print_rate_summary(csv_output, configs)
    print("probe_report={}".format(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
