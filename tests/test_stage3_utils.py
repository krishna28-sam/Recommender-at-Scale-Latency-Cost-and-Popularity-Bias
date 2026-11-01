import argparse
import csv
import json
from pathlib import Path
import pytest

from bias.bootstrap import (
    aggregate_bootstrap,
    bootstrap_ci,
    family_summary,
    family_bootstrap_summary,
    paired_ndcg_bootstrap,
)
from bias.offline_metrics import (
    compute_auc,
    compute_ndcg,
    compute_served_ndcg,
    compute_exposure_l1,
)
from bench.run import (
    compare_served_sets,
    load_expected_event_ids,
    smoke,
    validate_matrix_configuration,
    validate_output,
    validate_event_id_set,
    validate_producer_rate,
    compute_drain_and_loss,
    write_manifest,
    matrix_steps,
)
from bench.probe import (
    RATES,
    CONFIGS,
    CSV_COLUMNS,
    step_specs,
    parse_only,
    is_saturated,
    check_row_flags,
    print_rate_summary,
    step_environment,
    estimated_wall_seconds,
)


def test_bootstrap_ci_is_reproducible_and_bounded():
    result = bootstrap_ci([0.0, 0.5, 1.0], statistics_mean, samples=50, seed=7)
    assert result["n"] == 3
    assert result["low"] <= result["mean"] <= result["high"]


def statistics_mean(values):
    return sum(values) / len(values)


def test_family_summary_has_mean_and_std():
    rows = [
        {"mapping": "random_101", "lambda": "0.0", "exposure_l1": "0.1",
         "publisher_gini": "0.2", "ndcg_at_5_served": "0.8"},
        {"mapping": "random_202", "lambda": "0.0", "exposure_l1": "0.3",
         "publisher_gini": "0.4", "ndcg_at_5_served": "0.9"},
    ]
    result = family_summary(rows)
    assert result[0]["family"] == "random"
    assert result[0]["exposure_l1_mean"] == 0.2
    assert result[0]["exposure_l1_std"] > 0


def test_aggregate_bootstrap_has_estimate_and_bootstrap_mean():
    rows = [
        {"exposure": {"a": 1.0}, "ndcg_at_5_served": 0.5, "auc": 0.6, "ndcg_at_10": 0.4},
        {"exposure": {"b": 1.0}, "ndcg_at_5_served": 1.0, "auc": 0.8, "ndcg_at_10": 0.7},
    ]
    result = aggregate_bootstrap(rows, {"a": 0.5, "b": 0.5}, 20)
    assert set(("estimate", "bootstrap_mean", "low", "high")).issubset(
        result["exposure_l1"])
    assert "auc" in result
    assert "ndcg_at_10" in result
    assert 0.6 <= result["auc"]["estimate"] <= 0.8

    cis = [
        {"mapping": "random_101", "lambda": "0.0", "metric": "auc", "estimate": 0.7, "bootstrap_mean": 0.7},
        {"mapping": "random_202", "lambda": "0.0", "metric": "auc", "estimate": 0.72, "bootstrap_mean": 0.72},
    ]
    fam = family_bootstrap_summary(cis)
    assert len(fam) == 1
    assert fam[0]["family"] == "random"
    assert fam[0]["metric"] == "auc"
    assert fam[0]["estimate_mean"] == pytest.approx(0.71)


def test_paired_ndcg_bootstrap_has_difference_estimate():
    zero = [{"ndcg_at_5_served": 1.0}, {"ndcg_at_5_served": 0.5}]
    five = [{"ndcg_at_5_served": 0.8}, {"ndcg_at_5_served": 0.4}]
    result = paired_ndcg_bootstrap(zero, five, 20)
    assert result["estimate"] == pytest.approx(0.15)
    assert "bootstrap_mean" in result


def test_bootstrap_schema_and_path_resolution(tmp_path):
    historical_path = Path("data/processed/analysis/bootstrap_cis.json")
    if historical_path.exists():
        data = json.loads(historical_path.read_text(encoding="utf-8"))
        assert "bootstrap_cis" in data
        assert len(data["bootstrap_cis"]) > 0
        first = data["bootstrap_cis"][0]
        required_keys = {"mapping", "lambda", "metric", "estimate", "bootstrap_mean", "low", "high", "n", "resamples"}
        assert required_keys.issubset(first.keys())

    summary_file = tmp_path / "bootstrap_summary.json"
    cis_file = tmp_path / "bootstrap_cis.json"
    cis_file.write_text(json.dumps({"bootstrap_cis": [{"metric": "historical"}]}))

    chosen = summary_file if summary_file.exists() else cis_file
    assert chosen == cis_file

    summary_file.write_text(json.dumps({"bootstrap_cis": [{"metric": "new"}]}))
    chosen = summary_file if summary_file.exists() else cis_file
    assert chosen == summary_file



def test_runner_rejects_output_config_mismatch(tmp_path):
    path = tmp_path / "records.jsonl"
    row = {
        "event_id": "e1", "impression_id": "i1",
        "producer_timestamp_ms": 1, "served_top_k": [],
        "groups": {}, "lambda": 0.3, "mapping": "category_404",
        "engine": "spark", "sink_timestamp_ms": 2,
    }
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="lambda mismatch"):
        validate_output(path, "spark", "category_404", 0.0, 1, first_count=1)


def test_validate_event_id_set_detects_equal_counts_different_ids():
    actual = ["e1", "e2", "e3"]
    expected = ["e1", "e2", "e4"]
    with pytest.raises(ValueError, match="event_id set mismatch: missing=1, unexpected=1"):
        validate_event_id_set(actual, expected)


def test_validate_event_id_set_detects_duplicate_output_ids():
    actual = ["e1", "e2", "e2"]
    expected = ["e1", "e2", "e3"]
    with pytest.raises(ValueError, match="duplicate output event_ids detected"):
        validate_event_id_set(actual, expected)


def test_validate_event_id_set_passes_on_exact_set():
    assert validate_event_id_set(["e1", "e2"], ["e2", "e1"]) is True


def test_load_expected_event_ids_from_jsonl_and_txt(tmp_path):
    jsonl_path = tmp_path / "events.jsonl"
    jsonl_path.write_text('{"event_id": "ev-1", "payload": "x"}\n{"event_id": "ev-2"}\n')
    assert load_expected_event_ids(jsonl_path) == ["ev-1", "ev-2"]
    assert load_expected_event_ids(jsonl_path, limit=1) == ["ev-1"]

    txt_path = tmp_path / "events.txt"
    txt_path.write_text("ev-10\nev-20\n")
    assert load_expected_event_ids(txt_path) == ["ev-10", "ev-20"]


def test_smoke_runner_rejects_mismatched_event_ids_integration(tmp_path):
    records = tmp_path / "actual.jsonl"
    row = {
        "event_id": "ev_actual_1", "impression_id": "i1",
        "producer_timestamp_ms": 1, "served_top_k": [],
        "groups": {}, "lambda": 0.0, "mapping": "category_404",
        "engine": "spark", "sink_timestamp_ms": 2,
    }
    records.write_text(json.dumps(row) + "\n")

    expected_input = tmp_path / "expected.jsonl"
    expected_input.write_text(json.dumps({"event_id": "ev_expected_1"}) + "\n")

    args = argparse.Namespace(
        output=tmp_path / "results",
        run_id="test_run_mismatch",
        command='echo "target_rate=50 achieved_rate=50.0 events=1 elapsed_seconds=1.0"',
        target_rate=50.0,
        records=records,
        expected_input=expected_input,
        expected_engine="spark",
        mapping="category_404",
        lambda_value=0.0,
        expected_count=1,
        container=None,
    )
    exit_code = smoke(args)
    assert exit_code != 0

    csv_path = tmp_path / "results" / "test_run_mismatch.csv"
    assert csv_path.exists()
    with csv_path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["status"] == "FAIL"
    assert "event_id set mismatch" in rows[0]["error"]


def test_smoke_runner_passes_matching_event_ids_integration(tmp_path):
    records = tmp_path / "actual_pass.jsonl"
    row = {
        "event_id": "ev_matching_1", "impression_id": "i1",
        "producer_timestamp_ms": 1, "served_top_k": [],
        "groups": {}, "lambda": 0.0, "mapping": "category_404",
        "engine": "spark", "sink_timestamp_ms": 2,
    }
    records.write_text(json.dumps(row) + "\n")

    expected_input = tmp_path / "expected_pass.jsonl"
    expected_input.write_text(json.dumps({"event_id": "ev_matching_1"}) + "\n")

    args = argparse.Namespace(
        output=tmp_path / "results",
        run_id="test_run_pass",
        command='echo "target_rate=50 achieved_rate=50.0 events=1 elapsed_seconds=1.0"',
        target_rate=50.0,
        records=records,
        expected_input=expected_input,
        expected_engine="spark",
        mapping="category_404",
        lambda_value=0.0,
        expected_count=1,
        container=None,
    )
    exit_code = smoke(args)
    assert exit_code == 0

    csv_path = tmp_path / "results" / "test_run_pass.csv"
    assert csv_path.exists()
    with csv_path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["status"] == "PASS"
    assert rows[0]["error"] == ""


def test_compute_auc_deterministic_and_single_class():
    # Perfect ranking: positive at rank 0, negative at rank 1
    assert compute_auc([1, 0]) == 1.0
    # Inverted ranking: negative at rank 0, positive at rank 1
    assert compute_auc([0, 1]) == 0.0
    # Equal split: [1, 0, 0, 1] -> pairs: pos0 < neg1 (yes), pos0 < neg2 (yes), pos3 < neg1 (no), pos3 < neg2 (no) -> 2/4 = 0.5
    assert compute_auc([1, 0, 0, 1]) == 0.5
    # Single-class edge cases: all 1s or all 0s must return 0.5
    assert compute_auc([1, 1, 1]) == 0.5
    assert compute_auc([0, 0, 0]) == 0.5
    assert compute_auc([]) == 0.5


def test_compute_ndcg_and_served_ndcg_deterministic():
    import math
    # Labels [1, 0]: DCG@2 = 1.0 / log2(2) = 1.0; IDCG@2 = 1.0 -> nDCG = 1.0
    assert compute_ndcg([1, 0], 2) == pytest.approx(1.0)
    # Labels [0, 1]: DCG@2 = 0 + 1.0 / log2(3); IDCG@2 = 1.0 -> nDCG = 1.0 / log2(3)
    assert compute_ndcg([0, 1], 2) == pytest.approx(1.0 / math.log2(3))
    # All zero labels: IDCG is 0 -> nDCG must return 0.0
    assert compute_ndcg([0, 0, 0], 3) == 0.0

    # Served nDCG: candidate pool [1, 1, 0], served prefix [0, 1]
    # Candidate ideal top 2 DCG: 1/log2(2) + 1/log2(3)
    # Served top 2 DCG: 0 + 1/log2(3)
    expected_served_ndcg = (1.0 / math.log2(3)) / (1.0 / math.log2(2) + 1.0 / math.log2(3))
    assert compute_served_ndcg([1, 1, 0], [0, 1], 2) == pytest.approx(expected_served_ndcg)


def test_aggregate_bootstrap_deterministic_and_single_class():
    targets = {"g1": 0.5, "g2": 0.5}
    rows = [
        {"exposure": {"g1": 1.0}, "ndcg_at_5_served": 0.8, "auc": 0.7, "ndcg_at_10": 0.75},
        {"exposure": {"g2": 1.0}, "ndcg_at_5_served": 0.6, "auc": 0.5, "ndcg_at_10": 0.65},
        {"exposure": {"g1": 0.5, "g2": 0.5}, "ndcg_at_5_served": 0.7, "auc": 0.5, "ndcg_at_10": 0.70},
    ]
    res1 = aggregate_bootstrap(rows, targets, samples=10, seed=20261028)
    res2 = aggregate_bootstrap(rows, targets, samples=10, seed=20261028)
    for m in res1:
        assert res1[m]["estimate"] == res2[m]["estimate"]
        assert res1[m]["bootstrap_mean"] == res2[m]["bootstrap_mean"]
        assert res1[m]["low"] == res2[m]["low"]
        assert res1[m]["high"] == res2[m]["high"]
        assert res1[m]["low"] <= res1[m]["high"]
    # Point estimate check
    assert res1["ndcg_at_5_served"]["estimate"] == pytest.approx((0.8 + 0.6 + 0.7) / 3.0)




def test_runner_rejects_producer_rate_above_target():
    with pytest.raises(ValueError, match="more than 10% above"):
        validate_producer_rate("target_rate=50 achieved_rate=56.0", 50)


def test_runner_flags_producer_bound_below_target():
    achieved, producer_bound = validate_producer_rate(
        "target_rate=50 achieved_rate=40.0", 50)
    assert achieved == 40.0
    assert producer_bound is True


def test_order_independent_served_set_match():
    actual = [{"event_id": "e1", "served_top_k": ["b", "a"]}]
    reference = [{"event_id": "e1", "served_top_k": ["a", "b"]}]
    assert compare_served_sets(actual, reference)


def test_stateful_lambda_rejects_flink_parallelism_two():
    with pytest.raises(ValueError, match="stateful lambda"):
        validate_matrix_configuration("flink", 2, 0.3, 2)


def test_lambda_zero_allows_flink_parallelism_two():
    validate_matrix_configuration("flink", 2, 0.0, 2)


def test_every_probe_step_uses_two_partitions():
    specs = step_specs(CONFIGS)
    assert len(specs) == 42
    assert all(step["partitions"] == 2 for step in specs)


def test_flink_p2_rate_1000_uses_two_partitions():
    step = next(step for step in step_specs(CONFIGS)
                if step["config"] == "flink-p2" and step["target_rate"] == 1000)
    assert step["partitions"] == 2


def test_flink_p1_tuned_step_spec_and_environment():
    step = next(step for step in step_specs(CONFIGS)
                if step["config"] == "flink-p1-tuned" and step["target_rate"] == 100)
    assert step["partitions"] == 2
    assert step["lambda"] == 0.0
    assert step["engine"] == "flink"
    assert step["settings"] == "parallelism=1"
    env = step_environment(step)
    assert env["FLINK_PARALLELISM"] == "1"
    assert env["FLINK_BUNDLE_TIME_MS"] == "50"

    p1_step = next(step for step in step_specs(CONFIGS)
                   if step["config"] == "flink-p1" and step["target_rate"] == 100)
    env_p1 = step_environment(p1_step)
    assert "FLINK_BUNDLE_TIME_MS" not in env_p1

    assert estimated_wall_seconds() == 2310


def test_execute_path_is_not_stubbed():
    source = open("bench/probe.py", encoding="utf-8").read()
    assert "execution=NOT RUN" not in source
    assert parse_only("spark-default:100") == ("spark-default", 100.0)


def test_probe_metric_columns_are_numeric_and_status_is_separate(tmp_path):
    report = tmp_path / "report.csv"
    report.write_text(
        ",".join(CSV_COLUMNS) + "\n"
        "spark-default,0.0,100,100.0,false,100.0,1.0,2.0,3.0,"
        "4.0,5.0,6.0,0.0,0.0,1.0,2,cgroup_v2_usage_usec,DEBUG\n"
    )
    with report.open(newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    metric_columns = set(CSV_COLUMNS) - {
        "config", "lambda", "target_rate", "cpu_method", "status",
        "producer_bound",
    }
    for column in metric_columns:
        float(row[column])
    assert row["status"] == "DEBUG"


def _make_probe_row(
    config="flink-p1",
    lambda_val=0.0,
    target_rate=100,
    achieved_rate=100.0,
    producer_bound="false",
    output_throughput=100.0,
    lag_trend=0.0,
    loss=0.0,
    latency=10.0,
    status="PASS",
):
    return {
        "config": config,
        "lambda": str(lambda_val),
        "target_rate": str(target_rate),
        "achieved_rate": str(achieved_rate),
        "producer_bound": str(producer_bound),
        "output_throughput": str(output_throughput),
        "latency_p50_app": str(latency),
        "latency_p95_app": str(latency),
        "latency_p99_app": str(latency),
        "latency_p50_kafka": str(latency),
        "latency_p95_kafka": str(latency),
        "latency_p99_kafka": str(latency),
        "lag_trend": str(lag_trend),
        "loss": str(loss),
        "cpu_seconds": "1.0",
        "peak_memory_bytes": "1000",
        "cpu_method": "cgroup_v2_usage_usec",
        "status": status,
    }


def test_clearly_sustainable_at_low_rate():
    row = _make_probe_row(target_rate=100, achieved_rate=100.0,
                          output_throughput=100.0, lag_trend=0.0, loss=0.0)
    assert not is_saturated(row)


def test_saturated_by_lag_slope():
    row_ok = _make_probe_row(target_rate=100, lag_trend=20.0)
    assert not is_saturated(row_ok)
    row_sat = _make_probe_row(target_rate=100, lag_trend=20.01)
    assert is_saturated(row_sat)


def test_saturated_by_throughput_below_95pct_of_achieved():
    row_ok = _make_probe_row(achieved_rate=100.0, output_throughput=95.0)
    assert not is_saturated(row_ok)
    row_sat = _make_probe_row(achieved_rate=100.0, output_throughput=94.9)
    assert is_saturated(row_sat)


def test_saturated_by_loss():
    row_ok = _make_probe_row(loss=0.0)
    assert not is_saturated(row_ok)
    row_sat = _make_probe_row(loss=0.001)
    assert is_saturated(row_sat)


def test_producer_bound_never_chosen_as_high_rate():
    rows = [
        _make_probe_row(config="flink-p1", target_rate=100, achieved_rate=100.0,
                        output_throughput=100.0),
        _make_probe_row(config="flink-p1", target_rate=250, achieved_rate=150.0,
                        output_throughput=100.0, producer_bound="true"),
        _make_probe_row(config="flink-p1", target_rate=500, achieved_rate=500.0,
                        output_throughput=400.0, producer_bound="false"),
    ]
    summary = print_rate_summary(rows, CONFIGS)
    assert summary["proposed_high_rate"] == 500


def test_debug_rows_ignored_in_saturation_and_summary():
    debug_row = _make_probe_row(target_rate=100, loss=0.5, status="DEBUG")
    assert not is_saturated(debug_row)
    summary = print_rate_summary([debug_row], CONFIGS)
    assert summary["saturation_rates"]["flink-p1"] == "NONE"
    assert summary["proposed_high_rate"] == "NONE"


def test_flag_throughput_exceeds_achieved_rate_by_over_5_percent():
    row_ok = _make_probe_row(achieved_rate=100.0, output_throughput=105.0)
    assert not check_row_flags(row_ok)
    row_flagged = _make_probe_row(achieved_rate=100.0, output_throughput=105.1)
    flags = check_row_flags(row_flagged)
    assert any("throughput_exceeds" in f for f in flags)


def test_flag_latency_zero_or_negative():
    row_zero = _make_probe_row(latency=0.0)
    flags_zero = check_row_flags(row_zero)
    assert any("latency_p50_app_non_positive" in f for f in flags_zero)

    row_neg = _make_probe_row(latency=-2.5)
    flags_neg = check_row_flags(row_neg)
    assert any("latency_p50_app_non_positive" in f for f in flags_neg)


def test_flagged_row_not_dropped_in_summary():
    row = _make_probe_row(config="flink-p1", target_rate=100, achieved_rate=100.0,
                          output_throughput=110.0, loss=0.01)
    summary = print_rate_summary([row], CONFIGS)
    assert len(summary["flagged_rows"]) == 1
    assert summary["saturation_rates"]["flink-p1"] == 100


def test_drain_and_loss_4000_ev_s_case():
    """At 4000 ev/s, 120,001 events were produced. When the 30 s drain timeout
    fired, the offset sampler had only counted 95,000 events. But consuming
    the topic yielded all 120,001 distinct event IDs."""
    input_count = 120001
    sampler_output_count = 95000
    distinct_output_ids = 120001

    drain_result, loss = compute_drain_and_loss(
        input_count, sampler_output_count, distinct_output_ids
    )
    assert drain_result == "PASS"
    assert loss == 0.0

    # Conversely, when events are genuinely lost, loss is positive and drain fails
    fail_result, fail_loss = compute_drain_and_loss(
        input_count=1000, output_count=800, distinct_output_ids=800
    )
    assert fail_result == "FAIL"
    assert fail_loss == pytest.approx(0.2)


def test_manifest_contains_spark_trigger_and_flink_bundle_time(tmp_path):
    import argparse
    manifest_path = tmp_path / "test.manifest.json"
    args = argparse.Namespace(
        run_id="test_run",
        seed=20261028,
        config="config/model.yaml",
        expected_engine="spark",
        mapping="category_404",
        lambda_value=0.0,
        expected_count=100,
        spark_trigger="1s",
        flink_bundle_time_ms=None,
    )
    write_manifest(manifest_path, args, limits="NOT RUN")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["spark_trigger"] == "1s"
    assert data["flink_bundle_time_ms"] is None

    args_flink = argparse.Namespace(
        run_id="test_flink_run",
        seed=20261028,
        config="config/model.yaml",
        expected_engine="flink",
        mapping="category_404",
        lambda_value=0.0,
        expected_count=100,
        spark_trigger=None,
        flink_bundle_time_ms="50",
    )
    write_manifest(manifest_path, args_flink, limits="NOT RUN")
    data_flink = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data_flink["spark_trigger"] is None
    assert data_flink["flink_bundle_time_ms"] == "50"


def test_matrix_steps_order_and_count():
    steps = matrix_steps()
    assert len(steps) == 42
    first_14 = steps[:14]
    assert all(s["rep"] == 1 for s in first_14)
    pairs = {(s["config"], s["target_rate"]) for s in first_14}
    assert len(pairs) == 14
    configs = {s["config"] for s in first_14}
    assert len(configs) == 7
    rates = {s["target_rate"] for s in first_14}
    assert rates == {1000, 2000}



