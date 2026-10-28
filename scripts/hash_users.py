"""Hash MIND user IDs and refuse to write raw identifiers."""
import argparse
import csv
import hashlib
import os
from pathlib import Path


def hash_user(user_id, salt):
    return hashlib.sha256((salt + user_id).encode("utf-8")).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    salt = os.environ.get("MIND_USER_HASH_SALT")
    if not salt:
        raise SystemExit("MIND_USER_HASH_SALT must be set; refusing to process users")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw_ids = set()
    with args.input.open(encoding="utf-8") as source, args.output.open(
            "w", encoding="utf-8", newline="") as target:
        reader = csv.reader(source, delimiter="\t")
        writer = csv.writer(target, delimiter="\t")
        for index, row in enumerate(reader):
            if len(row) != 5:
                raise ValueError("behaviors.tsv row {} has {} fields".format(index + 1, len(row)))
            raw_ids.add(row[1])
            row[1] = hash_user(row[1], salt)
            writer.writerow(row)
    output_text = args.output.read_text()
    if any(raw_id and raw_id in output_text for raw_id in raw_ids):
        raise RuntimeError("raw user ID found in hashed output")
    print("hashed {} behavior rows; raw user IDs were not written".format(len(raw_ids)))


if __name__ == "__main__":
    main()
