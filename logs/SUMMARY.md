# MVP execution summary

## Step 1 — environment

**PASS**

Measured values from `logs/1-environment.log`:

- Python: 3.11.17
- apache-flink: 1.20.1
- pyspark: 3.5.3
- confluent-kafka: 2.6.1
- PyYAML: 6.0.2
- pytest: 8.3.3

## Step 2 — data, EDA, mappings, hashing

**FAIL — stopped**

The official MIND-small train URL returned:

```text
HTTP Error 409: Public access is not permitted on this storage account.
```

No local MIND files were present, so the dependent EDA, mapping, and hashing
commands were not run after the fail-fast rerun.

- EDA row counts: NOT RUN
- Click counts and CTR: NOT RUN
- Publisher purity per family: NOT RUN
- Data file counts: NOT RUN

## Remaining steps

- Step 3 tests: NOT RUN
- Step 4 train tables: NOT RUN
- Step 5 predictions: NOT RUN
- Step 6 offline metrics: NOT RUN
- Step 7 Docker builds: NOT RUN
- Step 8 Kafka setup: NOT RUN
- Step 9 smoke test: NOT RUN
- Step 10 topic timestamp verification: NOT RUN
- Producer target rate: NOT RUN
- Producer achieved rate: NOT RUN
- Producer-bound flag: NOT RUN
- Spark recommendations messages: NOT RUN
- Flink recommendations messages: NOT RUN

## MovieLens-derived fallback

The converter was added and syntax-checked, but Step 2 cannot proceed because
the required licensed input files are absent:

```text
MovieLens inputs required: data/raw/ml-25m/ratings.csv and data/raw/ml-25m/movies.csv
```

- MovieLens conversion: NOT RUN
- MovieLens EDA: NOT RUN
- MovieLens mappings: NOT RUN
- MovieLens hashing: NOT RUN
- MovieLens bias metrics: NOT RUN
- MovieLens streaming smoke: NOT RUN
