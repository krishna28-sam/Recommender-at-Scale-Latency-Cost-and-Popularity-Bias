SHELL := /bin/bash
PYTHON ?= python3
DATA_ROOT ?= data/raw
export PYTHONPATH := .

.PHONY: help data synthetic movielens eda mappings tables predictions offline hash-users up down topics test smoke probe matrix summarize bootstrap notebook report

help:
	@echo "make data DATA_ROOT=... | synthetic | movielens | eda | mappings | tables | predictions | offline | hash-users | up | down | topics | test | smoke | probe | matrix | summarize | bootstrap | notebook"

data:
	$(PYTHON) scripts/download_mind.py

synthetic:
	$(PYTHON) scripts/make_synthetic_mind.py --output-root data/synthetic

movielens:
	$(PYTHON) scripts/movielens_to_mind.py --data-root $(DATA_ROOT) --output-root data/movielens_derived

eda:
	$(PYTHON) scripts/eda.py --train $(DATA_ROOT)/MINDsmall_train --dev $(DATA_ROOT)/MINDsmall_dev --output data/processed/eda.json

mappings:
	$(PYTHON) scripts/generate_publishers.py --train-news $(DATA_ROOT)/MINDsmall_train/news.tsv --dev-news $(DATA_ROOT)/MINDsmall_dev/news.tsv --output-dir data/processed/publishers

tables:
	$(PYTHON) recsys/build_tables.py --train-dir $(DATA_ROOT)/MINDsmall_train --dev-dir $(DATA_ROOT)/MINDsmall_dev --output-dir data/processed/model_tables --publisher-dir data/processed/publishers

predictions:
	$(PYTHON) bias/make_predictions.py --behaviors $(DATA_ROOT)/MINDsmall_dev/behaviors.tsv --item-stats data/processed/model_tables/item_stats.json --target-dir data/processed/model_tables --train-news $(DATA_ROOT)/MINDsmall_train/news.tsv --dev-news $(DATA_ROOT)/MINDsmall_dev/news.tsv --mapping-dir data/processed/publishers --output-dir data/outputs/dev_predictions

offline:
	$(PYTHON) bias/offline_metrics.py --behaviors $(DATA_ROOT)/MINDsmall_dev/behaviors.tsv --train-behaviors $(DATA_ROOT)/MINDsmall_train/behaviors.tsv --predictions data/outputs/dev_predictions --item-stats data/processed/model_tables/item_stats.json --train-news $(DATA_ROOT)/MINDsmall_train/news.tsv --output data/processed/bias_summary.json

hash-users:
	@test -n "$$MIND_USER_HASH_SALT" || (echo "MIND_USER_HASH_SALT is required"; exit 1)
	$(PYTHON) scripts/hash_users.py --input $(DATA_ROOT)/MINDsmall_dev/behaviors.tsv --output data/processed/dev_behaviors_hashed.tsv

up:
	docker compose up -d kafka

down:
	docker compose down

topics:
	docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --create --if-not-exists --topic impressions --partitions $${KAFKA_PARTITIONS:-2} --replication-factor 1
	docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --create --if-not-exists --topic recommendations --partitions $${KAFKA_PARTITIONS:-2} --replication-factor 1 --config message.timestamp.type=LogAppendTime

test:
	$(PYTHON) -m compileall scripts recsys bias producer spark flink tests
	$(PYTHON) -m pytest -q

smoke:
	@test -n "$$MIND_USER_HASH_SALT" || (echo "MIND_USER_HASH_SALT is required"; exit 1)
	docker compose up -d kafka
	$(MAKE) topics
	@set -e; \
	reset_topics() { \
		docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --delete --topic impressions; \
		docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --delete --topic recommendations; \
		while topics=$$(docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --list); printf '%s\n' "$$topics" | grep -qE '^(impressions|recommendations)$$'; do sleep 1; done; \
		docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --create --if-not-exists --topic impressions --partitions $${KAFKA_PARTITIONS:-2} --replication-factor 1; \
		docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --create --if-not-exists --topic recommendations --partitions $${KAFKA_PARTITIONS:-2} --replication-factor 1 --config message.timestamp.type=LogAppendTime; \
		while [ "$$(offset_total impressions)" -ne 0 ] || [ "$$(offset_total recommendations)" -ne 0 ]; do sleep 1; done; \
	}; \
	offsets() { \
		docker compose exec -T kafka /opt/kafka/bin/kafka-run-class.sh org.apache.kafka.tools.GetOffsetShell --bootstrap-server kafka:9092 --topic "$$1"; \
	}; \
	offset_total() { offsets "$$1" | awk -F: '{sum += $$NF} END {print sum + 0}'; }; \
	reset_topics; \
	spark_id=$$(RUN_ID=smoke-spark ENGINE_MODE=pass-through BOOTSTRAP_SERVERS=kafka:9092 docker compose --profile spark run -d --rm spark); \
	sleep 5; \
	BOOTSTRAP_SERVERS=kafka:9092 docker compose --profile producer run --rm producer; \
	input_count=$$(offset_total impressions); \
	deadline=$$(($$(date +%s) + 30)); \
	while [ "$$(offset_total recommendations)" -lt "$$input_count" ] && [ "$$(date +%s)" -lt "$$deadline" ]; do sleep 1; done; \
	docker stop "$$spark_id" >/dev/null; \
	printf '\n--- spark impressions offsets ---\n'; offsets impressions; \
	printf '\n--- spark recommendations offsets ---\n'; offsets recommendations; \
	spark_impressions=$$(offset_total impressions); \
	spark_recommendations=$$(offset_total recommendations); \
	if [ "$$spark_impressions" -le 0 ]; then \
		echo "ERROR: spark impressions offset is non-positive ($$spark_impressions)"; exit 1; \
	fi; \
	if [ "$$spark_recommendations" -lt "$$spark_impressions" ]; then \
		echo "ERROR: spark recommendations ($$spark_recommendations) < impressions ($$spark_impressions); missing outputs: $$((spark_impressions - spark_recommendations))"; exit 1; \
	fi; \
	if [ "$$spark_recommendations" -gt $$((spark_impressions * 12 / 10)) ]; then \
		echo "ERROR: spark recommendations offsets exceed 1.2x impressions offsets ($$spark_recommendations > $$((spark_impressions * 12 / 10)))"; exit 1; \
	fi; \
	printf 'spark offset parity check passed: recommendations=%s impressions=%s\n' "$$spark_recommendations" "$$spark_impressions"; \
	reset_topics; \
	flink_id=$$(ENGINE_MODE=pass-through JAVA_OPTS='--add-opens=java.base/java.util=ALL-UNNAMED' BOOTSTRAP_SERVERS=kafka:9092 FLINK_PARALLELISM=1 docker compose --profile flink run -d --rm flink); \
	sleep 5; \
	BOOTSTRAP_SERVERS=kafka:9092 docker compose --profile producer run --rm producer; \
	input_count=$$(offset_total impressions); \
	deadline=$$(($$(date +%s) + 30)); \
	while [ "$$(offset_total recommendations)" -lt "$$input_count" ] && [ "$$(date +%s)" -lt "$$deadline" ]; do sleep 1; done; \
	docker stop "$$flink_id" >/dev/null; \
	printf '\n--- flink impressions offsets ---\n'; offsets impressions; \
	printf '\n--- flink recommendations offsets ---\n'; offsets recommendations; \
	flink_impressions=$$(offset_total impressions); \
	flink_recommendations=$$(offset_total recommendations); \
	if [ "$$flink_impressions" -le 0 ]; then \
		echo "ERROR: flink impressions offset is non-positive ($$flink_impressions)"; exit 1; \
	fi; \
	if [ "$$flink_recommendations" -lt "$$flink_impressions" ]; then \
		echo "ERROR: flink recommendations ($$flink_recommendations) < impressions ($$flink_impressions); missing outputs: $$((flink_impressions - flink_recommendations))"; exit 1; \
	fi; \
	if [ "$$flink_recommendations" -gt $$((flink_impressions * 12 / 10)) ]; then \
		echo "ERROR: flink recommendations offsets exceed 1.2x impressions offsets ($$flink_recommendations > $$((flink_impressions * 12 / 10)))"; exit 1; \
	fi; \
	printf 'flink offset parity check passed: recommendations=%s impressions=%s\n' "$$flink_recommendations" "$$flink_impressions";

probe:
	$(PYTHON) bench/probe.py --execute --output logs/probe_report.txt

matrix:
	$(PYTHON) bench/run.py --execute

summarize:
	$(PYTHON) bench/summarize_matrix.py

bootstrap:
	$(PYTHON) bias/bootstrap.py --predictions-root data/outputs/dev_predictions --output data/processed/analysis/bootstrap_summary.json --samples 1000 --lambdas 0.0 5.0

notebook:
	jupyter nbconvert --to notebook --execute --inplace notebooks/results.ipynb

report:
	$(PYTHON) report/build_report.py
