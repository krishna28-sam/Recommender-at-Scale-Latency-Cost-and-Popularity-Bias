"""Unattended benchmark runner scaffolding and raw-run summarizer.

The full matrix is intentionally not launched by this module. Use --plan to
print the matrix, or --smoke with an explicit engine command in a controlled
environment. Completed run IDs are skipped.
"""
import argparse
import csv
import json
import os
import statistics
import subprocess
import time
import threading
import re
from datetime import datetime, timezone
from pathlib import Path


SYSTEM_CONFIGS = (
    ("spark-default", "spark", "default", 0.0),
    ("spark-1s", "spark", "1s", 0.0),
    ("flink-p1", "flink", "parallelism-1", 0.0),
    ("flink-p1-tuned", "flink", "parallelism-1-tuned", 0.0),
    ("flink-p2", "flink", "parallelism-2", 0.0),
)
RERANK_CONFIGS = (
    ("spark-default-rerank", "spark", "default", 0.6),
    ("flink-p1-rerank", "flink", "parallelism-1", 0.6),
)
RATES = (1000, 2000)
REPS = 3
MEASUREMENT_SECONDS = 60
LAMBDAS = (0.0, 0.6)
REQUIRED_OUTPUT_FIELDS = {
    "event_id", "impression_id", "producer_timestamp_ms", "served_top_k",
    "groups", "lambda", "mapping", "engine", "sink_timestamp_ms",
}


def cgroup_cpu_counter(container):
    result = subprocess.check_output(
        ["docker", "exec", container, "sh", "-c",
         "if [ -r /sys/fs/cgroup/cpu.stat ]; then printf 'v2 '; awk '/usage_usec/ {print $2}' /sys/fs/cgroup/cpu.stat; "
         "elif [ -r /sys/fs/cgroup/cpuacct/cpuacct.usage ]; then printf 'v1 '; cat /sys/fs/cgroup/cpuacct/cpuacct.usage; "
         "else exit 2; fi"], text=True).strip()
    method, value = result.split()
    divisor = 1_000_000 if method == "v2" else 1_000_000_000
    return float(value) / divisor, method


def memory_sample(container):
    result = subprocess.check_output(
        ["docker", "exec", container, "sh", "-c",
         "if [ -r /sys/fs/cgroup/memory.current ]; then cat /sys/fs/cgroup/memory.current; "
         "elif [ -r /sys/fs/cgroup/memory/memory.usage_in_bytes ]; then cat /sys/fs/cgroup/memory/memory.usage_in_bytes; "
         "else exit 2; fi"], text=True).strip()
    return int(result)


def resource_window(container, seconds, interval=1):
    start, method = cgroup_cpu_counter(container)
    peak_memory = 0
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            peak_memory = max(peak_memory, memory_sample(container))
        except subprocess.CalledProcessError:
            pass
        time.sleep(interval)
    end, _ = cgroup_cpu_counter(container)
    return {
        "cpu_seconds": end - start,
        "cpu_method": "cgroup_{}_{}".format(
            "v2" if method == "v2" else "v1", 
            "usage_usec" if method == "v2" else "cpuacct.usage"),
        "peak_memory_bytes": peak_memory,
        "memory_method": "cgroup_v2_memory.current_or_v1_memory.usage_in_bytes",
    }


def validate_producer_rate(output, target_rate):
    marker = "achieved_rate="
    line = next((line for line in output.splitlines() if marker in line), None)
    if line is None:
        raise ValueError("producer output did not contain achieved_rate")
    achieved = float(line.split(marker, 1)[1].split()[0])
    if achieved > target_rate * 1.10:
        raise ValueError("achieved_rate {:.3f} is more than 10% above target {:.3f}".format(
            achieved, target_rate))
    return achieved, achieved < target_rate * 0.90


def _percentile(values, percentile):
    if not values:
        raise ValueError("no latency samples remain after the first 5 seconds")
    values = sorted(values)
    index = min(len(values) - 1, int(round((percentile / 100) * (len(values) - 1))))
    return "{:.3f}".format(values[index])


def _topic_offsets(topic):
    output = subprocess.check_output(
        ["docker", "compose", "exec", "-T", "kafka",
         "/opt/kafka/bin/kafka-run-class.sh",
         "org.apache.kafka.tools.GetOffsetShell",
         "--bootstrap-server", "kafka:9092", "--topic", topic],
        text=True,
    )
    return sum(int(line.rsplit(":", 1)[1]) for line in output.splitlines()
               if line.strip() and line.rsplit(":", 1)[1].isdigit())


def _consume_probe_records():
    records = []
    try:
        from confluent_kafka import Consumer, TopicPartition
        consumer = Consumer({
            "bootstrap.servers": "localhost:29092",
            "group.id": "probe-reader-{}".format(time.time_ns()),
            "auto.offset.reset": "earliest",
        })
        metadata = consumer.list_topics("recommendations", timeout=10)
        partitions = metadata.topics["recommendations"].partitions
        consumer.assign([TopicPartition("recommendations", partition, 0)
                        for partition in partitions])
        idle = 0
        while idle < 3:
            message = consumer.poll(1)
            if message is None:
                idle += 1
                continue
            if message.error():
                continue
            idle = 0
            records.append((message.timestamp()[1], json.loads(message.value())))
        consumer.close()
    except (ImportError, KeyError, TypeError, ValueError):
        pass
    return records


def _engine_log_parallelism(container, engine):
    logs = subprocess.run(
        ["docker", "logs", container], text=True, capture_output=True,
        check=False,
    )
    text = logs.stdout + logs.stderr
    if not text:
        logs = subprocess.run(
            ["docker", "compose", "logs", "--no-color", engine],
            text=True, capture_output=True, check=False,
        )
        text = logs.stdout + logs.stderr
    patterns = {
        "flink": r"(?i)(?:engine_parallelism|parallelism)\s*[:= ]\s*(\d+)",
        "spark": r"(?i)(?:engine_parallelism\s*[:= ]\s*|local\[|spark\.sql\.shuffle\.partitions[ =])(\d+)",
    }
    match = re.search(patterns[engine], text)
    return match.group(1) if match else "NOT FOUND"


def _slope(points):
    """Least-squares slope of (t, value) points; 0.0 with fewer than 2 points."""
    if len(points) < 2:
        return 0.0
    n = float(len(points))
    mean_t = sum(t for t, _ in points) / n
    mean_v = sum(v for _, v in points) / n
    denominator = sum((t - mean_t) ** 2 for t, _ in points)
    if denominator == 0:
        return 0.0
    return sum((t - mean_t) * (v - mean_v) for t, v in points) / denominator


def _window_throughput(samples, t_start, t_end):
    """Output records per second between two times, from (t, in, out) samples."""
    inside = [s for s in samples if t_start <= s[0] <= t_end]
    if len(inside) < 2 or inside[-1][0] <= inside[0][0]:
        return 0.0
    return (inside[-1][2] - inside[0][2]) / (inside[-1][0] - inside[0][0])


def _end_offset_total(consumer, topic, partitions):
    from confluent_kafka import TopicPartition
    total = 0
    for partition in range(partitions):
        _, high = consumer.get_watermark_offsets(
            TopicPartition(topic, partition), timeout=5, cached=False)
        total += high
    return total


def _new_offset_consumer():
    from confluent_kafka import Consumer
    return Consumer({
        "bootstrap.servers": "localhost:29092",
        "group.id": "probe-offsets-{}".format(time.time_ns()),
        "enable.auto.commit": False,
    })


def _wait_until_engine_ready(consumer, partitions, timeout=180):
    """Send one marker event and wait for its output, so engine startup is
    excluded from the measurement. Returns (in_base, out_base, seconds)."""
    from confluent_kafka import Producer
    started = time.monotonic()
    producer = Producer({"bootstrap.servers": "localhost:29092"})
    producer.produce("impressions", key="ready-0", value=json.dumps({
        "event_id": "ready-0", "impression_id": "ready",
        "producer_timestamp_ms": int(time.time() * 1000),
        "history": [], "candidates": []}).encode())
    producer.flush(10)
    while time.monotonic() - started < timeout:
        if _end_offset_total(consumer, "recommendations", partitions) >= 1:
            return (_end_offset_total(consumer, "impressions", partitions),
                    _end_offset_total(consumer, "recommendations", partitions),
                    time.monotonic() - started)
        time.sleep(1)
    raise RuntimeError("engine produced no output for the readiness marker "
                       "within {} s".format(timeout))


def compute_drain_and_loss(input_count, output_count, distinct_output_ids):
    """Compute drain_result and loss from offset counts and distinct event_ids.

    When distinct_output_ids meets or exceeds input_count, all events were successfully
    processed, meaning zero true loss occurred and drain succeeded.
    """
    effective_output = max(output_count, distinct_output_ids) if distinct_output_ids >= input_count else output_count
    drain_result = "PASS" if effective_output >= input_count else "FAIL"
    loss = max(0, input_count - effective_output) / input_count if input_count else 0.0
    return drain_result, loss


def run_probe_step(spec):
    """Run one probe step; the probe owns selection and persistence.

    Differences from the first version: engine startup is excluded (readiness
    marker), CPU is measured over the producer window only, lag and output
    throughput are sampled once per second during the window, and loss is
    computed after a drain wait.
    """
    try:
        from bench.probe import step_environment
    except ModuleNotFoundError:
        from probe import step_environment

    recreate_topics("kafka", partitions=spec["partitions"])
    env = step_environment(spec)
    service = spec["engine"]
    partitions = spec["partitions"]
    container = None
    sampler = None
    stop = threading.Event()
    samples = []
    peak_memory = [0]
    sampler_error = []
    try:
        start = subprocess.run(
            ["docker", "compose", "--profile", service, "run", "-d", "--rm",
             service],
            env=env, text=True, capture_output=True, check=True)
        container = start.stdout.strip().splitlines()[-1]
        offsets = _new_offset_consumer()
        in_base, out_base, ready_seconds = _wait_until_engine_ready(
            offsets, partitions)
        print("engine_ready_seconds={:.1f}".format(ready_seconds))

        def sample_loop():
            sampling = _new_offset_consumer()
            try:
                while not stop.is_set():
                    now = time.time()
                    try:
                        samples.append((
                            now,
                            _end_offset_total(sampling, "impressions", partitions) - in_base,
                            _end_offset_total(sampling, "recommendations", partitions) - out_base))
                        peak_memory[0] = max(peak_memory[0], memory_sample(container))
                    except Exception as exc:  # keep sampling; record the last error
                        sampler_error.append(str(exc))
                    stop.wait(1.0)
            finally:
                sampling.close()

        sampler = threading.Thread(target=sample_loop, daemon=True)
        sampler.start()
        cpu_start, method = cgroup_cpu_counter(container)
        window_start = time.time()
        producer = subprocess.run(
            ["docker", "compose", "--profile", "producer", "run", "--rm",
             "producer"], env=env, text=True, capture_output=True, check=False)
        window_end = time.time()
        cpu_end, _ = cgroup_cpu_counter(container)
        if producer.stdout:
            print(producer.stdout, end="")
        if producer.stderr:
            print(producer.stderr, end="")
        if producer.returncode:
            raise RuntimeError("producer command failed")
        achieved, producer_bound = validate_producer_rate(
            producer.stdout, spec["target_rate"])

        # Backlog at the end of the producer window
        window_samples = [s for s in samples if s[0] <= window_end]
        if window_samples:
            backlog_at_window_end = max(0, window_samples[-1][1] - window_samples[-1][2])
        elif samples:
            backlog_at_window_end = max(0, samples[0][1] - samples[0][2])
        else:
            backlog_at_window_end = 0

        # Drain wait (up to 30 s); the sampler keeps running.
        drain_start = time.monotonic()
        drain_deadline = drain_start + 30
        while time.monotonic() < drain_deadline:
            if samples and samples[-1][2] >= samples[-1][1]:
                break
            time.sleep(1)
        drain_seconds = time.monotonic() - drain_start
        stop.set()
        sampler.join(timeout=5)
        if not samples:
            raise RuntimeError("no offset samples collected: {}".format(
                sampler_error[-1] if sampler_error else "unknown"))
        input_count = samples[-1][1]
        output_count = samples[-1][2]
        records = [(ts, rec) for ts, rec in _consume_probe_records()
                   if not str(rec.get("event_id", "")).startswith("ready-")]
        distinct_output_ids = len({record["event_id"] for _, record in records})
        drain_result, loss = compute_drain_and_loss(
            input_count, output_count, distinct_output_ids)
        actual_parallelism = _engine_log_parallelism(container, service)
        print("input_event_count={} output_distinct_event_id_count={} drain_result={} "
              "drain_seconds={:.3f} backlog_at_window_end={} "
              "partitions={} parallelism_actual={} cpu_method={}".format(
                  input_count, distinct_output_ids, drain_result,
                  drain_seconds, backlog_at_window_end,
                  partitions, actual_parallelism, method))
        measure_from = window_start + 5
        window_points = [(t, i - o) for t, i, o in samples
                         if measure_from <= t <= window_end]
        lag_slope = _slope(window_points)
        throughput = _window_throughput(samples, measure_from, window_end)
        app_latencies, kafka_latencies, raw_timestamps = [], [], []
        for append_timestamp, record in records:
            missing = REQUIRED_OUTPUT_FIELDS.difference(record)
            if missing:
                raise ValueError("probe output missing fields: {}".format(
                    sorted(missing)))
            if (record["engine"] != spec["engine"]
                    or record["mapping"] != "category_404"
                    or float(record["lambda"]) != float(spec["lambda"])):
                raise ValueError("probe output schema/config mismatch")
            producer_timestamp = int(record["producer_timestamp_ms"])
            if len(raw_timestamps) < 3:
                raw_timestamps.append((producer_timestamp,
                                       int(record["sink_timestamp_ms"]),
                                       append_timestamp))
            if producer_timestamp < int(measure_from * 1000):
                continue
            app_latencies.append(int(record["sink_timestamp_ms"]) - producer_timestamp)
            kafka_latencies.append(append_timestamp - producer_timestamp)
        if not app_latencies or not kafka_latencies:
            raise ValueError("no latency samples after the first 5 seconds of the window")
        print("latency_samples_used={} app_min={} app_max={} kafka_min={} kafka_max={}".format(
            len(app_latencies), min(app_latencies), max(app_latencies),
            min(kafka_latencies), max(kafka_latencies)))
        for index, (p, s, k) in enumerate(raw_timestamps, 1):
            print("raw_output_{} producer_timestamp_ms={} sink_timestamp_ms={} "
                  "kafka_append_time={}".format(index, p, s, k))
        return {
            "achieved_rate": "{:.3f}".format(achieved),
            "producer_bound": str(producer_bound).lower(),
            "output_throughput": "{:.3f}".format(throughput),
            "latency_p50_app": _percentile(app_latencies, 50),
            "latency_p95_app": _percentile(app_latencies, 95),
            "latency_p99_app": _percentile(app_latencies, 99),
            "latency_p50_kafka": _percentile(kafka_latencies, 50),
            "latency_p95_kafka": _percentile(kafka_latencies, 95),
            "latency_p99_kafka": _percentile(kafka_latencies, 99),
            "lag_trend": "{:.3f}".format(lag_slope),
            "loss": "{:.6f}".format(loss),
            "cpu_seconds": "{:.3f}".format(cpu_end - cpu_start),
            "peak_memory_bytes": str(peak_memory[0]),
            "cpu_method": "cgroup_{}_{}".format(
                "v2" if method == "v2" else "v1",
                "usage_usec" if method == "v2" else "cpuacct.usage"),
            "status": "PASS",
            "drain_seconds": "{:.3f}".format(drain_seconds),
            "backlog_at_window_end": str(int(backlog_at_window_end)),
        }
    finally:
        stop.set()
        if sampler and sampler.is_alive():
            sampler.join(timeout=2)
        if container:
            subprocess.run(["docker", "stop", container], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["docker", "rm", "-f", container], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def plan():
    system_runs = len(SYSTEM_CONFIGS) * len(RATES) * REPS
    rerank_runs = len(RERANK_CONFIGS) * len(RATES) * REPS
    total = system_runs + rerank_runs
    seconds = total * 96
    print("matrix_configs={}".format(
        ", ".join(c[0] for c in SYSTEM_CONFIGS + RERANK_CONFIGS)))
    print("rates={}".format(",".join(str(r) for r in RATES)))
    print("reps={}".format(REPS))
    print("measurement_window_seconds={}".format(MEASUREMENT_SECONDS))
    print("system_runs={}".format(system_runs))
    print("reranking_cost_runs={}".format(rerank_runs))
    print("total_runs={}".format(total))
    print("base_seconds_per_step=96")
    print("projected_hours={:.3f}".format(seconds / 3600.0))


def validate_matrix_configuration(engine, partitions, lambda_value,
                                  flink_parallelism):
    if lambda_value != 0.0 and engine == "flink" and flink_parallelism > 1:
        raise ValueError(
            "stateful lambda requires Flink parallelism <= 1; "
            "requested lambda={} parallelism={}".format(
                lambda_value, flink_parallelism))


def compare_served_sets(actual, reference):
    actual_rows = {row["event_id"]: set(row["served_top_k"]) for row in actual}
    reference_rows = {
        row["event_id"]: set(row["served_top_k"]) for row in reference
    }
    return actual_rows == reference_rows


def recreate_topics(bootstrap, input_topic="impressions",
                    output_topic="recommendations", partitions=2):
    for topic in (input_topic, output_topic):
        subprocess.run(
            ["docker", "compose", "exec", "-T", "kafka",
             "/opt/kafka/bin/kafka-topics.sh", "--bootstrap-server", "kafka:9092",
             "--delete", "--topic", topic],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    for topic in (input_topic, output_topic):
        command = [
            "docker", "compose", "exec", "-T", "kafka",
            "/opt/kafka/bin/kafka-topics.sh", "--bootstrap-server", "kafka:9092",
            "--create", "--topic", topic, "--partitions", str(partitions),
            "--replication-factor", "1",
        ]
        if topic == output_topic:
            command.extend(["--config", "message.timestamp.type=LogAppendTime"])
        subprocess.run(command, check=True)


def inspect_limits(container):
    output = subprocess.check_output(
        ["docker", "inspect", container,
         "--format", "{{.HostConfig.NanoCpus}},{{.HostConfig.Memory}}"],
        text=True,
    ).strip()
    cpu, memory = output.split(",", 1)
    return {"nano_cpus": int(cpu), "memory_bytes": int(memory)}


def load_expected_event_ids(path, limit=None):
    """Extract canonical event IDs from an input file without retaining payloads."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError("expected input file not found: {}".format(path))
    ids = []
    if p.suffix == ".jsonl":
        with p.open(encoding="utf-8") as handle:
            for line in handle:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    record = json.loads(line_str)
                    if "event_id" in record:
                        ids.append(record["event_id"])
                        if limit is not None and len(ids) >= limit:
                            break
                except json.JSONDecodeError:
                    continue
    else:
        with p.open(encoding="utf-8") as handle:
            for line in handle:
                token = line.strip()
                if token:
                    ids.append(token)
                    if limit is not None and len(ids) >= limit:
                        break
    return ids


def validate_event_id_set(actual_ids, expected_ids):
    """Detect missing, unexpected, and duplicate event IDs."""
    actual_list = list(actual_ids)
    actual_set = set(actual_list)
    expected_set = set(expected_ids)
    if len(actual_list) != len(actual_set):
        duplicates = len(actual_list) - len(actual_set)
        raise ValueError("duplicate output event_ids detected: count={}".format(duplicates))
    missing = expected_set - actual_set
    unexpected = actual_set - expected_set
    if missing or unexpected:
        raise ValueError(
            "event_id set mismatch: missing={}, unexpected={}, expected_total={}, actual_total={}".format(
                len(missing), len(unexpected), len(expected_set), len(actual_set)
            )
        )
    return True


def validate_output(path, expected_engine, expected_mapping, expected_lambda,
                    expected_count, first_count=20, expected_event_ids=None):
    rows = []
    actual_ids = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("invalid JSON at {}:{}".format(path, line_number)) from exc
            missing = REQUIRED_OUTPUT_FIELDS.difference(row)
            if missing:
                raise ValueError("missing output fields at {}:{}: {}".format(
                    path, line_number, sorted(missing)))
            if row["engine"] != expected_engine:
                raise ValueError("engine mismatch at {}:{}".format(path, line_number))
            if row["mapping"] != expected_mapping:
                raise ValueError("mapping mismatch at {}:{}".format(path, line_number))
            if float(row["lambda"]) != float(expected_lambda):
                raise ValueError("lambda mismatch at {}:{}".format(path, line_number))
            if not isinstance(row["served_top_k"], list):
                raise ValueError("served_top_k is not a list at {}:{}".format(path, line_number))
            actual_ids.append(row["event_id"])
            if len(rows) < max(first_count, 3):
                rows.append(row)
            if len(actual_ids) == first_count:
                print("first_{}_records=PASS".format(first_count))
    distinct_ids = set(actual_ids)
    if len(actual_ids) != expected_count:
        raise ValueError("distinct output count {} != expected {}".format(
            len(distinct_ids), expected_count))
    if len(distinct_ids) != len(actual_ids):
        raise ValueError("duplicate event_id in {}".format(path))
    if expected_event_ids is not None:
        validate_event_id_set(actual_ids, expected_event_ids)
    print("first_raw_output_rows=")
    for row in rows[:3]:
        print(json.dumps(row, sort_keys=True))
    print("validated_output_rows={}".format(len(actual_ids)))
    return rows


def write_manifest(path, args, limits):
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = getattr(args, "expected_engine", None)
    spark_trigger = (
        getattr(args, "spark_trigger", None)
        or os.environ.get("SPARK_TRIGGER")
        or ("default" if engine == "spark" else None)
    )
    flink_bundle_time_ms = (
        getattr(args, "flink_bundle_time_ms", None)
        or os.environ.get("FLINK_BUNDLE_TIME_MS")
        or ("default" if engine == "flink" else None)
    )
    try:
        git_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        git_commit = "SUBMISSION_ARCHIVE"
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": getattr(args, "run_id", "unknown"),
        "seed": getattr(args, "seed", 20261028),
        "git_commit": git_commit,
        "config_snapshot": Path(getattr(args, "config", "config/model.yaml")).read_text(encoding="utf-8"),
        "container_limits": limits,
        "warmup_seconds": 30,
        "measurement_seconds": MEASUREMENT_SECONDS,
        "latency_definition": "Kafka LogAppendTime minus producer_timestamp_ms",
        "application_latency_definition": "sink_timestamp_ms minus producer_timestamp_ms",
        "cost_prices": "ASSUMED illustrative prices from config; NOT A QUOTE",
        "expected_engine": engine,
        "expected_mapping": getattr(args, "mapping", "category_404"),
        "expected_lambda": getattr(args, "lambda_value", 0.0),
        "expected_count": getattr(args, "expected_count", 500),
        "spark_trigger": spark_trigger,
        "flink_bundle_time_ms": flink_bundle_time_ms,
    }
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def smoke(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    raw = output / "{}.csv".format(args.run_id)
    if raw.exists():
        print("SKIP completed run_id={}".format(args.run_id))
        return 0
    if not args.command:
        print("SMOKE=NOT RUN: --command is required")
        return 2
    started = time.time()
    completed = subprocess.run(args.command, shell=True, text=True,
                               capture_output=True)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="")
    validation_error = None
    producer_bound = False
    if completed.returncode == 0:
        try:
            _, producer_bound = validate_producer_rate(
                completed.stdout, args.target_rate)
            print("producer_bound={}".format(str(producer_bound).lower()))
        except ValueError as exc:
            validation_error = str(exc)
            print("producer_rate_guard=FAIL error={}".format(validation_error))
    if completed.returncode == 0 and args.records:
        try:
            expected_ids = None
            if getattr(args, "expected_input", None):
                expected_ids = load_expected_event_ids(args.expected_input, args.expected_count)
            validate_output(args.records, args.expected_engine, args.mapping,
                            args.lambda_value, args.expected_count,
                            expected_event_ids=expected_ids)
        except (OSError, ValueError) as exc:
            validation_error = str(exc)
            print("output_validation=FAIL error={}".format(validation_error))
    elif completed.returncode == 0:
        validation_error = "--records is required for a smoke run"
        print("output_validation=FAIL error={}".format(validation_error))
    status = completed.returncode == 0 and validation_error is None
    output_count = 0
    if args.records and Path(args.records).exists():
        output_count = sum(1 for _ in Path(args.records).open(encoding="utf-8"))
    error = validation_error or (None if completed.returncode == 0 else
                                 "command_exit_{}".format(completed.returncode))
    with raw.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "run_id", "flag", "status", "elapsed_seconds", "engine",
            "mapping", "lambda", "input_count", "output_count",
            "drain_result", "error"])
        writer.writeheader()
        writer.writerow({
            "run_id": args.run_id, "flag": "SMOKE",
            "status": "PASS" if status else "FAIL",
            "elapsed_seconds": time.time() - started,
            "engine": args.expected_engine or "NOT RUN",
            "mapping": args.mapping,
            "lambda": args.lambda_value,
            "input_count": args.expected_count,
            "output_count": output_count,
            "drain_result": "PASS" if output_count == args.expected_count else "FAIL",
            "error": error or "",
        })
    limits = "NOT RUN"
    if args.container:
        try:
            limits = inspect_limits(args.container)
        except subprocess.CalledProcessError:
            limits = "NOT AVAILABLE"
    write_manifest(output / "{}.manifest.json".format(args.run_id), args, limits)
    print("SMOKE status={} run_id={}".format(
        "PASS" if status else "FAIL", args.run_id))
    return 0 if status else (completed.returncode or 1)


def matrix_steps():
    steps = []
    for rep in range(1, REPS + 1):
        for name, engine, setting, lambda_val in SYSTEM_CONFIGS + RERANK_CONFIGS:
            for rate in RATES:
                run_id = "{}_r{}_rep{}".format(name, rate, rep)
                steps.append({
                    "run_id": run_id,
                    "config": name,
                    "engine": engine,
                    "settings": setting,
                    "lambda": lambda_val,
                    "target_rate": rate,
                    "rep": rep,
                    "partitions": 2,
                    "duration_seconds": MEASUREMENT_SECONDS,
                })
    return steps


def execute_matrix(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    steps = matrix_steps()
    for spec in steps:
        raw = output / "{}.csv".format(spec["run_id"])
        if raw.exists():
            print("SKIP completed run_id={}".format(spec["run_id"]))
            continue
        print("step run_id={} config={} target_rate={} lambda={}".format(
            spec["run_id"], spec["config"], spec["target_rate"], spec["lambda"]))
        row = run_probe_step(spec)
        with raw.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
            writer.writeheader()
            writer.writerow(row)
        step_args = argparse.Namespace(
            run_id=spec["run_id"],
            seed=args.seed,
            config=args.config,
            expected_engine=spec["engine"],
            mapping="category_404",
            lambda_value=spec["lambda"],
            expected_count=int(spec["target_rate"] * spec["duration_seconds"]),
            spark_trigger=args.spark_trigger or ("1s" if "1s" in spec["config"] else "default"),
            flink_bundle_time_ms=args.flink_bundle_time_ms or ("50" if "tuned" in spec["config"] else "default"),
        )
        write_manifest(output / "{}.manifest.json".format(spec["run_id"]), step_args, "NOT RUN")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--command")
    parser.add_argument("--run-id", default="smoke")
    parser.add_argument("--output", type=Path, default=Path("bench/results"))
    parser.add_argument("--config", type=Path, default=Path("config/model.yaml"))
    parser.add_argument("--seed", type=int, default=20261028)
    parser.add_argument("--container")
    parser.add_argument("--records", type=Path)
    parser.add_argument("--expected-input", type=Path, default=None,
                        help="Path to input jsonl/txt to extract expected event_ids")
    parser.add_argument("--expected-engine", choices=("spark", "flink"))
    parser.add_argument("--mapping", default="category_404")
    parser.add_argument("--lambda-value", type=float, default=0.0)
    parser.add_argument("--expected-count", type=int, default=500)
    parser.add_argument("--target-rate", type=float, default=50.0)
    parser.add_argument("--partitions", type=int, default=2)
    parser.add_argument("--flink-parallelism", type=int, default=1)
    parser.add_argument("--spark-trigger", default=os.environ.get("SPARK_TRIGGER"))
    parser.add_argument("--flink-bundle-time-ms", default=os.environ.get("FLINK_BUNDLE_TIME_MS"))
    args = parser.parse_args()
    if args.plan:
        plan()
        return 0
    if args.execute:
        return execute_matrix(args)
    if args.smoke:
        try:
            validate_matrix_configuration(
                args.expected_engine, args.partitions, args.lambda_value,
                args.flink_parallelism)
        except ValueError as exc:
            parser.error(str(exc))
        return smoke(args)
    parser.error("use --plan, --execute, or --smoke")


if __name__ == "__main__":
    raise SystemExit(main())
