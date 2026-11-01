"""Compare metrics from engine output JSONL with offline per-event records."""
import argparse
import json
from collections import Counter
from pathlib import Path

from bias.offline_metrics import compute_exposure_l1, gini


def metrics(path, target):
    exposure = Counter()
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            for rank, item in enumerate(row.get("served_top_k", [])[:5], 1):
                group = row.get("groups", {}).get(item)
                if group:
                    exposure[group] += 1.0 / __import__("math").log2(rank + 1)
    return {
        "exposure_l1": compute_exposure_l1(exposure, target),
        "publisher_gini": gini(exposure.values()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine-output", type=Path, required=True)
    parser.add_argument("--target-shares", type=Path, required=True)
    parser.add_argument("--offline-json", type=Path, required=True)
    args = parser.parse_args()
    result = {
        "stream": metrics(args.engine_output, json.loads(args.target_shares.read_text())),
        "offline_file": str(args.offline_json),
        "status": "NOT RUN: comparison requires final saved real-MIND outputs",
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
