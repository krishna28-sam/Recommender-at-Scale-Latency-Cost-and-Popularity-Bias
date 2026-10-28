"""Convert MovieLens 25M ratings/movies to MIND-compatible train/dev TSVs."""
import argparse
import csv
import hashlib
import json
import random
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import yaml


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_time(value):
    return datetime.utcfromtimestamp(int(value)).strftime("%m/%d/%Y %H:%M:%S")


def read_movies(path):
    movies = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            movie_id = int(row["movieId"])
            genres = row["genres"].split("|") if row["genres"] else ["unknown"]
            movies[movie_id] = (genres[0], "|".join(genres), row["title"])
    return movies


def read_ratings(path, movies, max_users, rng):
    by_user = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            user_id = int(row["userId"])
            movie_id = int(row["movieId"])
            if movie_id not in movies:
                continue
            by_user[user_id].append((int(row["timestamp"]), movie_id, float(row["rating"])))
    users = sorted(by_user)
    if len(users) > max_users:
        users = sorted(rng.sample(users, max_users))
    return {user_id: sorted(by_user[user_id]) for user_id in users}


def write_news(path, movie_ids, movies):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        for movie_id in sorted(movie_ids):
            category, subcategory, title = movies[movie_id]
            writer.writerow([
                "N{}".format(movie_id), category, subcategory, title, "", "", "", "",
            ])


def choose_events(ratings, cutoff, limit, split, rng):
    positives = [rating for rating in ratings if rating[2] >= 4.0]
    selected = [rating for rating in positives
                if (rating[0] < cutoff if split == "train" else rating[0] >= cutoff)]
    if len(selected) > limit:
        selected = rng.sample(selected, limit)
    return sorted(selected)


def make_events(users, movies, cutoff, seed, split, train_cap, dev_cap):
    rng = random.Random(seed)
    catalog = sorted(movies)
    events = []
    item_ids = set()
    for user_id in sorted(users):
        ratings = users[user_id]
        limit = train_cap if split == "train" else dev_cap
        selected = choose_events(ratings, cutoff, limit, split, rng)
        rated = set(movie_id for _, movie_id, _ in ratings)
        negatives_pool = [movie_id for movie_id in catalog if movie_id not in rated]
        for timestamp, movie_id, _ in selected:
            if len(negatives_pool) < 19:
                continue
            negatives = rng.sample(negatives_pool, 19)
            candidates = ["N{}".format(movie_id)] + ["N{}".format(item) for item in negatives]
            rng.shuffle(candidates)
            history = ["N{}".format(item) for prior_time, item, rating in ratings
                       if prior_time < timestamp and rating >= 4.0]
            events.append([
                str(len(events) + 1), "U{}".format(user_id), parse_time(timestamp),
                " ".join(history), " ".join("{}-{}".format(item, 1 if item == "N{}".format(movie_id) else 0)
                                            for item in candidates),
            ])
            item_ids.update([movie_id] + negatives)
    return events, item_ids


def impression_items(events):
    items = set()
    for row in events:
        items.update(row[3].split())
        items.update(token.rsplit("-", 1)[0] for token in row[4].split())
    return items


def train_known_items(events):
    items = set()
    for row in events:
        for token in row[3].split():
            if token.startswith("N"):
                items.add(token)
        for token in row[4].split():
            item_id, label = token.rsplit("-", 1)
            if label == "1":
                items.add(item_id)
    return items


def dev_items(events):
    items = set()
    for row in events:
        items.update(row[3].split())
        items.update(token.rsplit("-", 1)[0] for token in row[4].split())
    return items


def compute_cold_start(train_events, dev_events):
    train_known = train_known_items(train_events)
    dev_item_set = dev_items(dev_events)
    dev_positive_items = {
        token.rsplit("-", 1)[0]
        for row in dev_events
        for token in row[4].split()
        if token.endswith("-1")
    }
    dev_candidate_items = {
        token.rsplit("-", 1)[0]
        for row in dev_events
        for token in row[4].split()
    }
    return {
        "train_known_items": len(train_known),
        "dev_items_not_in_train_known": len(dev_item_set - train_known),
        "dev_positives_cold_start_share": (
            len(dev_positive_items - train_known) / float(len(dev_positive_items))
            if dev_positive_items else 0.0
        ),
        "dev_candidate_cold_start_share": (
            len(dev_candidate_items - train_known) / float(len(dev_candidate_items))
            if dev_candidate_items else 0.0
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-root", type=Path, default=Path("data/raw"))
    parser.add_argument("--config", type=Path, default=Path("config/model.yaml"))
    args = parser.parse_args()
    source = args.data_root / "ml-25m"
    ratings_path, movies_path = source / "ratings.csv", source / "movies.csv"
    if not ratings_path.exists() or not movies_path.exists():
        raise SystemExit("MovieLens inputs required: {} and {}".format(ratings_path, movies_path))
    config = yaml.safe_load(args.config.read_text())["data"]
    seed = int(config["seed"])
    max_users = int(config["movielens_max_users"])
    train_cap = int(config["movielens_train_impressions_per_user"])
    dev_cap = int(config["movielens_dev_impressions_per_user"])
    rng = random.Random(seed)
    movies = read_movies(movies_path)
    users = read_ratings(ratings_path, movies, max_users, rng)
    positives = sorted(
        rating[0] for ratings in users.values() for rating in ratings if rating[2] >= 4.0)
    if not positives:
        raise SystemExit("No positive MovieLens ratings were found")
    cutoff = positives[int(0.8 * (len(positives) - 1))]
    train_events, train_items = make_events(
        users, movies, cutoff, seed, "train", train_cap, dev_cap)
    dev_events, dev_items = make_events(
        users, movies, cutoff, seed + 1, "dev", train_cap, dev_cap)
    train_dir = args.output_root / "MINDsmall_train"
    dev_dir = args.output_root / "MINDsmall_dev"
    train_dir.mkdir(parents=True, exist_ok=True)
    dev_dir.mkdir(parents=True, exist_ok=True)
    write_news(train_dir / "news.tsv", train_items, movies)
    write_news(dev_dir / "news.tsv", dev_items, movies)
    with (train_dir / "behaviors.tsv").open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(train_events)
    with (dev_dir / "behaviors.tsv").open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(dev_events)
    manifest = {
        "data_source": "movielens_converted",
        "source": "MovieLens 25M ratings.csv and movies.csv",
        "licence_note": "Use under the MovieLens dataset license/terms; do not redistribute source data.",
        "seed": seed,
        "max_users": max_users,
        "train_impressions_per_user_cap": train_cap,
        "dev_impressions_per_user_cap": dev_cap,
        "sampling_rule": "one impression per positive rating; 19 uniform negatives from movies not rated by that user",
        "positive_rating_threshold": 4.0,
        "split_rule": "single global timestamp cutoff at the 80th percentile of positive ratings; train before cutoff, dev on or after cutoff",
        "cutoff_timestamp": parse_time(cutoff),
        "cutoff_epoch": cutoff,
        "user_count": len(users),
        "train_impressions": len(train_events),
        "dev_impressions": len(dev_events),
        "positives_per_impression": 1.0,
        "candidates_per_impression": 20,
        "unique_users_with_train_impressions": len(set(row[1] for row in train_events)),
        "unique_users_with_dev_impressions": len(set(row[1] for row in dev_events)),
        "train_clicks": sum(
            token.endswith("-1") for row in train_events for token in row[4].split()),
        "dev_clicks": sum(
            token.endswith("-1") for row in dev_events for token in row[4].split()),
        "train_ctr": (
            sum(token.endswith("-1") for row in train_events for token in row[4].split()) /
            float(len(train_events) * 20) if train_events else 0.0
        ),
        "dev_ctr": (
            sum(token.endswith("-1") for row in dev_events for token in row[4].split()) /
            float(len(dev_events) * 20) if dev_events else 0.0
        ),
        "inputs": [
            {"file": str(ratings_path), "sha256": sha256(ratings_path)},
            {"file": str(movies_path), "sha256": sha256(movies_path)},
        ],
        "train_news": len(train_items), "dev_news": len(dev_items),
    }
    cold_start = compute_cold_start(train_events, dev_events)
    manifest["train_known_items"] = cold_start["train_known_items"]
    manifest["dev_items_not_in_train_known"] = cold_start["dev_items_not_in_train_known"]
    manifest["dev_positives_cold_start_share"] = cold_start["dev_positives_cold_start_share"]
    manifest["dev_candidate_cold_start_share"] = cold_start["dev_candidate_cold_start_share"]
    manifest["actual_train_ctr"] = manifest["train_clicks"] / float(
        sum(len(row[4].split()) for row in train_events) if train_events else 0.0)
    manifest["actual_dev_ctr"] = manifest["dev_clicks"] / float(
        sum(len(row[4].split()) for row in dev_events) if dev_events else 0.0)
    manifest_dir = args.output_root.parent / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "movielens_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    (args.output_root / "MOVIELENS_DERIVED_DATA.txt").write_text(
        "data_source=movielens_converted\nDo not report these metrics as MIND results.\n")
    print(json.dumps({key: manifest[key] for key in (
        "cutoff_timestamp", "cutoff_epoch", "user_count", "train_impressions",
        "dev_impressions", "positive_rating_threshold", "unique_users_with_train_impressions",
        "unique_users_with_dev_impressions", "candidates_per_impression",
        "positives_per_impression", "train_clicks", "train_ctr", "dev_clicks",
        "dev_ctr", "dev_positives_cold_start_share", "dev_candidate_cold_start_share",
        "dev_items_not_in_train_known"
    )}, indent=2))


if __name__ == "__main__":
    main()
