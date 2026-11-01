# Technical specification

The primary dataset is the public MIND-small dataset supplied under the
Microsoft Research License. The current run uses the real
`data/raw/MINDsmall_train` and `data/raw/MINDsmall_dev` files. The
MovieLens-derived conversion is retained only as a documented fallback under
`data/raw/movielens_derived_*`; fallback outputs are not reported as MIND
results.

## Data split and leakage control

`MINDsmall_train` is the only source for popularity, CTR, and target synthetic
publisher shares. `MINDsmall_train/news.tsv` plus `MINDsmall_dev/news.tsv`
provide category lookups, using the union by `NewsID`; every exposure group in
this MVP is a synthetic publisher from one of the six mappings. `MINDsmall_dev` is
used for replay and offline evaluation. Click labels are never sent in Kafka
payloads; evaluation joins predictions to the original dev impression by
`impression_id` offline.

Training-only statistics use the train impression table only. The train-known set
is defined as all items appearing either as a positive in a train impression or in
any train history entry. Cold-start metrics compare dev items against this
train-known set, not against the static dev catalog. For example,
`dev_items_not_in_train_known` is the number of dev candidate/history items not in
train-known, and `dev_positives_cold_start_share` is the share of dev positive
items not in train-known. Items unseen in train have `impressions=0`,
`popularity=0`, and `smoothed_ctr=global_ctr`; category affinity can still apply.

User IDs are replaced with a salted SHA-256 digest before any derived event is
written. The salt is supplied through `MIND_USER_HASH_SALT` and is never
committed.

## Tier 1 scorer

For item `i`, training data supplies:

```text
global_ctr = total clicks / total item impressions
smoothed_ctr_i = (clicks_i + alpha * global_ctr) / (impressions_i + alpha)
popularity_i = log1p(impressions_i) * smoothed_ctr_i
```

`alpha=10`, `popularity_weight=0.7`, and `category_affinity_weight=0.3` are
stored in `config/model.yaml`. Popularity is min-max normalized using training
statistics. Items unseen in train have impressions and popularity zero, and
smoothed CTR equal to `global_ctr`; their category affinity still applies.
For an event history, category affinity is the count of valid history items
whose category equals the candidate category divided by the number of valid
history items. Empty/unknown history has affinity zero.

The final score is:

```text
0.7 * normalized_popularity_i + 0.3 * category_affinity(i, history)
```

Candidates are the impression's supplied candidates. Results contain at most
`top_k` items. Ties are resolved by final score descending, smoothed CTR
descending, popularity descending, then lexicographically ascending `NewsID`.

## Re-ranking

The deterministic re-ranker uses a fixed group-share target table computed
from the MIND-small training catalog and a running exposure state over the
entire scoring pass. For position `r`, `d(r)=1/log2(r+1)`. At each slot,
for each remaining candidate `i` in group `g`, compute:

```text
penalty(i) = lambda * max(0,
  exposure[g] / max(total, eps) - target_share[g])
adjusted_score(i) = base_score(i) - penalty(i)
```

with `exposure[g]` and `total` updated by the discounted exposure from the
already selected items in the running pass. The candidate with the maximum
`adjusted_score`, then score, then smoothed CTR, then popularity, then
lexicographic `NewsID` is chosen. After selection, `exposure[g] += d(r)` and
`total += d(r)`. The target is the candidate publisher's fixed train-catalog
share from the mapping-specific `target_shares_<name>.json`. Exposure is
measured over the served top-5 lists. Ranking metrics (AUC, MRR, nDCG@5, and
nDCG@10) rank the full candidate list, while exposure metrics use the served
top-5 only. A difference between exposure share and catalog share is
descriptive and is not automatically unfair; relevance, demand, candidate
composition, and catalog size must be considered.

## Real MIND limitations

MIND-small has no publisher field, so publisher groups are synthetic mappings
used only for controlled exposure analysis. Exposure share is not the same as
unfairness. News is short-lived, so a train-period popularity table can become
stale; rolling or time-decayed popularity is future work. The MIND candidate
lists are variable length (typically about 35–40), and the implementation must
never assume 20 candidates.

## MovieLens-derived fallback

If the official MIND-small host is unavailable, no unofficial mirror is used.
With licensed MovieLens 25M `ratings.csv` and `movies.csv` under
`DATA_ROOT/ml-25m`, `scripts/movielens_to_mind.py` creates MIND-format files
under the fallback paths.
It samples 10,000 users using a fixed seed, computes one global timestamp
cutoff at the 80th percentile of positive ratings (`rating >= 4.0`), assigns
ratings before the cutoff to train and ratings on or after it to dev, and caps each
user at 20 train and 10 dev impressions using the fixed seed. Each synthetic
impression contains 1 positive and 19 uniformly sampled negatives. The
constructed candidate-level CTR is 0.05 by construction. These uniform negatives
favour popularity-based scorers and are not equivalent to real recommendation
candidates. Histories contain previous positive events only. The resulting data
source is `movielens_derived`; its metrics are pipeline tests only and must never
be reported as MIND results.

## Streaming and latency

The producer sends dev impressions without click labels, cycles with fresh event
IDs, and shifts timestamps for scale tests. Each output records the producer
timestamp, impression ID, served top-k, groups, lambda, mapping, engine, and
application sink timestamp. Click labels are never sent. Kafka output uses
`LogAppendTime`; Kafka append-time latency is reported separately. Below-
saturation means consumer-group lag does not trend upward during measurement;
above-saturation means it does.

Both engines import the same pure-Python `recsys.scorer` and
`recsys.reranker`. For parity and benchmark runs, the impressions topic has one
partition and the stateful operator is single-threaded: Spark processes each
micro-batch in partition/offset order with a driver-side state dictionary, and
Flink uses parallelism one. This state is not checkpointed. Both jobs retain a
pass-through mode for measuring engine overhead. Python execution overhead is a
limitation of this demonstration.

The accepted parity run used one impressions partition and Flink parallelism
one. The matrix design uses two input partitions; every run creates fresh
two-partition topics. The lambda-zero grid contains Spark default trigger, Spark
1-second trigger, Flink parallelism one, and Flink parallelism two. Its output
is compared with the offline reference as an order-independent set of
`served_top_k` values per `event_id`.

Re-ranking overhead runs use Spark default trigger and Flink parallelism one
only, at lambdas 0, 0.3, and 0.6. They validate aggregate exposure shares
against the offline reference within the configured tolerance, rather than
requiring byte equality. The runner rejects stateful lambda runs with Flink
parallelism greater than one. This keeps running-share state in one task.

With one partition, Flink parallelism two leaves one task idle; it is not a
meaningful scale comparison. With two partitions and parallelism two, state is
partition-local and global ordering changes. A meaningful p1 versus p2
comparison therefore requires explicit deterministic partition keys and keyed
state, with throughput/lag/resource comparison treated as a separate experiment
from the one-task parity semantics.

The `movielens` Make target writes only to `data/movielens_derived`. The
converter refuses `data/raw`, any descendant of `data/raw`, and any output
directory already containing a `MINDsmall_*` directory.

The planned probe uses two fresh input partitions for every rate step and
runs each engine alone for 30 seconds at 100, 250, 500, 1000, 2000, and 4000
events/s. It covers Spark default/lambda 0, Spark 1-second/lambda 0, Flink
parallelism 1/lambda 0, Flink parallelism 2/lambda 0, Spark
default/lambda 0.6, and Flink parallelism 1/lambda 0.6. The probe command is
`make probe`; it writes `logs/probe_report.txt` and refuses to start when the
preflight load or swap limit is exceeded.
