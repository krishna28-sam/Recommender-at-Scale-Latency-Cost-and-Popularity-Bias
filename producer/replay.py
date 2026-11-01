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
    if path.suffix == ".jsonl":
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                event = json.loads(line)
                yield event
        return
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
    parser.add_argument("--max-events", type=int, default=None)
    parser.add_argument("--event-id-prefix", default=None)
    args = parser.parse_args()
    salt = os.environ.get("MIND_USER_HASH_SALT")
    if not salt:
        raise SystemExit("MIND_USER_HASH_SALT must be set; refusing to send users")
    bootstrap = os.environ.get("BOOTSTRAP_SERVERS", "localhost:29092")
    producer = Producer({"bootstrap.servers": bootstrap})
    events = load_events(args.behaviors, salt)
    start = time.time()
    sent = 0
    cycle = 0
    next_send = time.monotonic()
    while time.time() - start < args.seconds and (
            args.max_events is None or sent < args.max_events):
        delay = next_send - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        try:
            event = next(events)
        except StopIteration:
            cycle += 1
            events = load_events(args.behaviors, salt)
            event = next(events)
        if "event_id" not in event:
            event["event_id"] = (
                "{}-{}".format(args.event_id_prefix, sent)
                if args.event_id_prefix else str(uuid.uuid4()))
        event["producer_timestamp_ms"] = int(time.time() * 1000)
        event["replay_cycle"] = cycle
        event["shifted_event_time_ms"] = event["producer_timestamp_ms"] + cycle * 86400000
        producer.produce(args.topic, key=event["event_id"],
                         value=json.dumps(event).encode())
        producer.poll(0)
        sent += 1
        next_send += 1.0 / args.rate
    producer.flush()
    elapsed = time.time() - start
    achieved = sent / elapsed if elapsed else 0.0
    print("target_rate={} achieved_rate={:.3f} events={} elapsed_seconds={:.3f}".format(
        args.rate, achieved, sent, elapsed))
    if achieved > args.rate * 1.10:
        print("rate_guard=FAIL achieved_rate_more_than_10_percent_above_target")
        raise SystemExit(1)
    if achieved < args.rate * 0.90:
        print("producer_bound=true")
    else:
        print("producer_bound=false")


if __name__ == "__main__":
    main()
