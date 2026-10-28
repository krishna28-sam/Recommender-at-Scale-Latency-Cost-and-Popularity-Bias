"""Replay MIND dev impressions without click labels."""
import argparse
import csv
import hashlib
import os
import time
import uuid
import json
from pathlib import Path

from confluent_kafka import Producer


def load_events(path, salt):
    with path.open(encoding="utf-8") as handle:
        for row in csv.reader(handle, delimiter="\t"):
            if len(row) != 5:
                continue
            candidates = [token.rsplit("-", 1)[0] for token in row[4].split()]
            yield {
                "impression_id": row[0],
                "user_id": hashlib.sha256((salt + row[1]).encode()).hexdigest(),
                "time": row[2],
                "history": row[3].split() if row[3] else [],
                "candidates": candidates,
            }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--behaviors", type=Path, required=True)
    parser.add_argument("--topic", default="impressions")
    parser.add_argument("--rate", type=float, required=True)
    parser.add_argument("--seconds", type=int, default=120)
    args = parser.parse_args()
    salt = os.environ.get("MIND_USER_HASH_SALT")
    if not salt:
        raise SystemExit("MIND_USER_HASH_SALT must be set; refusing to send users")
    bootstrap = os.environ.get("BOOTSTRAP_SERVERS", "localhost:29092")
    producer = Producer({"bootstrap.servers": bootstrap})
    events = load_events(args.behaviors, salt)
    start = time.time()
    sent = 0
    tick_seconds = 0.01
    per_tick = max(1, int(round(args.rate * tick_seconds)))
    cycle = 0
    while time.time() - start < args.seconds:
        tick_start = time.time()
        for _ in range(per_tick):
            try:
                event = next(events)
            except StopIteration:
                cycle += 1
                events = load_events(args.behaviors, salt)
                event = next(events)
            event["event_id"] = str(uuid.uuid4())
            event["producer_timestamp_ms"] = int(time.time() * 1000)
            event["replay_cycle"] = cycle
            event["shifted_event_time_ms"] = event["producer_timestamp_ms"] + cycle * 86400000
            producer.produce(args.topic, key=event["event_id"],
                             value=json.dumps(event).encode())
            producer.poll(0)
            sent += 1
        delay = tick_seconds - (time.time() - tick_start)
        if delay > 0:
            time.sleep(delay)
    producer.flush()
    elapsed = time.time() - start
    achieved = sent / elapsed if elapsed else 0.0
    print("target_rate={} achieved_rate={:.3f} events={} elapsed_seconds={:.3f}".format(
        args.rate, achieved, sent, elapsed))
    if achieved < args.rate * 0.95:
        print("producer_bound=true")
    else:
        print("producer_bound=false")


if __name__ == "__main__":
    main()
