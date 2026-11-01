"""Build and compare a fixed ordered real-MIND parity fixture.

The fixture is written to a caller-selected temporary path, never to the
repository data directories. Engine output files must be JSONL records with
event_id and served_top_k fields.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from recsys.streaming import EventScorer

def fixture(source, output, limit=500):
    rows = []
    with Path(source).open(encoding="utf-8") as handle:
        for index, row in enumerate(csv.reader(handle, delimiter="\t")):
            if len(row) != 5:
                continue
            candidates = [token.rsplit("-", 1)[0] for token in row[4].split()]
            rows.append({
                "event_id": "parity-{}".format(index),
                "impression_id": row[0],
                "producer_timestamp_ms": index,
                "user_id": hashlib.sha256(row[1].encode()).hexdigest(),
                "time": row[2],
                "history": row[3].split() if row[3] else [],
                "candidates": candidates,
            })
            if len(rows) == limit:
                break
    if len(rows) != limit:
        raise SystemExit("expected {} real-MIND rows, found {}".format(limit, len(rows)))
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    print("fixture_rows={}".format(len(rows)))
    print("candidate_count_min={}".format(min(map(lambda r: len(r["candidates"]), rows))))
    print("candidate_count_max={}".format(max(map(lambda r: len(r["candidates"]), rows))))


def load(path):
    with Path(path).open(encoding="utf-8") as handle:
        return {row["event_id"]: row["served_top_k"] for row in map(json.loads, handle)}


def offline_reference(fixture_path, output_path, assets, mapping, lambda_value):
    scorer = EventScorer(assets, mapping, lambda_value, "offline")
    output_path = Path(output_path)
    with Path(fixture_path).open(encoding="utf-8") as source, output_path.open(
            "w", encoding="utf-8") as target:
        for line in source:
            target.write(json.dumps(scorer.score(json.loads(line))) + "\n")
    with output_path.open(encoding="utf-8") as handle:
        count = sum(1 for _ in handle)
    print("offline_reference_events={}".format(count))


def compare(spark, flink, offline):
    outputs = {"spark": load(spark), "flink": load(flink), "offline": load(offline)}
    keys = sorted(set().union(*[set(value) for value in outputs.values()]))
    differences = []
    for key in keys:
        values = {name: outputs[name].get(key) for name in outputs}
        if len(set(json.dumps(value, sort_keys=True) for value in values.values())) != 1:
            differences.append({"event_id": key, "values": values})
    print("spark_events={}".format(len(outputs["spark"])))
    print("flink_events={}".format(len(outputs["flink"])))
    print("offline_events={}".format(len(outputs["offline"])))
    print("differences={}".format(len(differences)))
    if differences:
        print(json.dumps(differences, sort_keys=True))
        return 1
    print("PARITY_GATE=PASS")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-source", type=Path)
    parser.add_argument("--fixture-output", type=Path)
    parser.add_argument("--spark-output", type=Path)
    parser.add_argument("--flink-output", type=Path)
    parser.add_argument("--offline-output", type=Path)
    parser.add_argument("--offline-reference", action="store_true")
    parser.add_argument("--assets", type=Path, default=Path("data/processed/model_tables"))
    parser.add_argument("--mapping", default="category_404")
    parser.add_argument("--lambda-value", type=float, default=0.0)
    args = parser.parse_args()
    if args.fixture_source and not args.offline_reference:
        fixture(args.fixture_source, args.fixture_output)
    if args.offline_reference:
        offline_reference(args.fixture_source, args.offline_output, args.assets,
                          args.mapping, args.lambda_value)
        return 0
    if args.spark_output and args.flink_output and args.offline_output:
        return compare(args.spark_output, args.flink_output, args.offline_output)
    if not args.fixture_source:
        parser.error("provide fixture arguments or all three output arguments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
