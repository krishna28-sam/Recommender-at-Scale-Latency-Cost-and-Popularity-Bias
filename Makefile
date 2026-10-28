SHELL := /bin/bash
PYTHON ?= python3
DATA_ROOT ?= data/raw
export PYTHONPATH := .

.PHONY: help data synthetic movielens eda mappings tables predictions offline hash-users up down topics test smoke

help:
	@echo "make data DATA_ROOT=... | synthetic | eda | mappings | tables | predictions | offline | hash-users | up | down | topics | test | smoke"

data:
	$(PYTHON) scripts/download_mind.py

synthetic:
	$(PYTHON) scripts/make_synthetic_mind.py --output-root data/synthetic

movielens:
	$(PYTHON) scripts/movielens_to_mind.py --data-root $(DATA_ROOT) --output-root data/raw

eda:
	$(PYTHON) scripts/eda.py --train $(DATA_ROOT)/MINDsmall_train --dev $(DATA_ROOT)/MINDsmall_dev --output data/processed/eda.json

mappings:
	$(PYTHON) scripts/generate_publishers.py --train-news $(DATA_ROOT)/MINDsmall_train/news.tsv --dev-news $(DATA_ROOT)/MINDsmall_dev/news.tsv --output-dir data/processed/publishers

tables:
	$(PYTHON) recsys/build_tables.py --train-dir $(DATA_ROOT)/MINDsmall_train --dev-dir $(DATA_ROOT)/MINDsmall_dev --output-dir data/processed/model_tables --publisher-dir data/processed/publishers

predictions:
	$(PYTHON) bias/make_predictions.py --behaviors $(DATA_ROOT)/MINDsmall_dev/behaviors.tsv --item-stats data/processed/model_tables/item_stats.json --target-dir data/processed/model_tables --train-news $(DATA_ROOT)/MINDsmall_train/news.tsv --dev-news $(DATA_ROOT)/MINDsmall_dev/news.tsv --mapping-dir data/processed/publishers --output-dir data/outputs/dev_predictions

offline:
	$(PYTHON) bias/offline_metrics.py --behaviors $(DATA_ROOT)/MINDsmall_dev/behaviors.tsv --predictions data/outputs/dev_predictions --item-stats data/processed/model_tables/item_stats.json --train-news $(DATA_ROOT)/MINDsmall_train/news.tsv --output data/processed/bias_summary.json

hash-users:
	@test -n "$$MIND_USER_HASH_SALT" || (echo "MIND_USER_HASH_SALT is required"; exit 1)
	$(PYTHON) scripts/hash_users.py --input $(DATA_ROOT)/MINDsmall_dev/behaviors.tsv --output data/processed/dev_behaviors_hashed.tsv

up:
	docker compose up -d kafka

down:
	docker compose down

topics:
	docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --create --if-not-exists --topic impressions --partitions 2 --replication-factor 1
	docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --create --if-not-exists --topic recommendations --partitions 2 --replication-factor 1 --config message.timestamp.type=LogAppendTime

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
		docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --create --if-not-exists --topic impressions --partitions 2 --replication-factor 1; \
		docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --create --if-not-exists --topic recommendations --partitions 2 --replication-factor 1 --config message.timestamp.type=LogAppendTime; \
		while [ "$$(offset_total impressions)" -ne 0 ] || [ "$$(offset_total recommendations)" -ne 0 ]; do sleep 1; done; \
	}; \
	offsets() { \
		docker compose exec -T kafka /opt/kafka/bin/kafka-run-class.sh org.apache.kafka.tools.GetOffsetShell --bootstrap-server kafka:9092 --topic "$$1"; \
	}; \
	offset_total() { offsets "$$1" | awk -F: '{sum += $$NF} END {print sum + 0}'; }; \
	reset_topics; \
	spark_id=$$(RUN_ID=smoke-spark BOOTSTRAP_SERVERS=kafka:9092 docker compose --profile spark run -d --rm spark); \
	sleep 5; \
	BOOTSTRAP_SERVERS=kafka:9092 docker compose --profile producer run --rm producer; \
	docker stop "$$spark_id" >/dev/null; \
	printf '\n--- spark impressions offsets ---\n'; offsets impressions; \
	printf '\n--- spark recommendations offsets ---\n'; offsets recommendations; \
	spark_impressions=$$(offset_total impressions); \
	spark_recommendations=$$(offset_total recommendations); \
	if [ "$$spark_recommendations" -gt $$((spark_impressions * 12 / 10)) ]; then \
		echo "ERROR: spark recommendations offsets exceed 1.2x impressions offsets"; exit 1; \
	fi; \
	printf 'spark offset ratio check passed: recommendations=%s impressions=%s\n' "$$spark_recommendations" "$$spark_impressions"; \
	reset_topics; \
	flink_id=$$(BOOTSTRAP_SERVERS=kafka:9092 FLINK_PARALLELISM=1 docker compose --profile flink run -d --rm flink); \
	sleep 5; \
	BOOTSTRAP_SERVERS=kafka:9092 docker compose --profile producer run --rm producer; \
	docker stop "$$flink_id" >/dev/null; \
	printf '\n--- flink impressions offsets ---\n'; offsets impressions; \
	printf '\n--- flink recommendations offsets ---\n'; offsets recommendations; \
	flink_impressions=$$(offset_total impressions); \
	flink_recommendations=$$(offset_total recommendations); \
	if [ "$$flink_recommendations" -gt $$((flink_impressions * 12 / 10)) ]; then \
		echo "ERROR: flink recommendations offsets exceed 1.2x impressions offsets"; exit 1; \
	fi; \
	printf 'flink offset ratio check passed: recommendations=%s impressions=%s\n' "$$flink_recommendations" "$$flink_impressions";
