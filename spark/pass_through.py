"""Spark Structured Streaming Kafka pass-through."""
import argparse
import json
import os

from pyspark.sql import SparkSession

from recsys.streaming import EventScorer, pass_through


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-topic", default="impressions")
    parser.add_argument("--output-topic", default="recommendations")
    parser.add_argument("--mode", choices=("score", "pass-through"), default=os.environ.get("ENGINE_MODE", "score"))
    parser.add_argument("--mapping", default=os.environ.get("MAPPING", "random_101"))
    parser.add_argument("--lambda-value", type=float, default=float(os.environ.get("LAMBDA", "0.0")))
    args = parser.parse_args()
    print("engine_parallelism=2", flush=True)
    bootstrap = os.environ.get("BOOTSTRAP_SERVERS", "localhost:29092")
    spark = (SparkSession.builder.appName("recommender-spark")
             .config("spark.sql.shuffle.partitions", "1")
             .getOrCreate())
    scorer = None
    if args.mode == "score":
        scorer = EventScorer(os.environ.get("MODEL_TABLE_DIR", "data/processed/model_tables"),
                             args.mapping, args.lambda_value, "spark")

    from confluent_kafka import Producer
    # One producer for the whole job: creating a new one per micro-batch pays a
    # connection/metadata round trip on every batch and inflates Kafka latency.
    producer = Producer({"bootstrap.servers": bootstrap})

    def process_batch(batch, batch_id):
        rows = batch.select("value", "partition", "offset").orderBy("partition", "offset").collect()
        for row in rows:
            event = json.loads(row["value"])
            result = pass_through(event, "spark") if scorer is None else scorer.score(event)
            producer.produce(args.output_topic, key=event["event_id"],
                             value=json.dumps(result).encode())
            producer.poll(0)
        producer.flush()

    query = (spark.readStream.format("kafka")
             .option("kafka.bootstrap.servers", bootstrap)
             .option("subscribe", args.input_topic)
             .option("startingOffsets", "earliest")
             .load()
             .selectExpr("CAST(value AS STRING) AS value", "partition", "offset")
             .writeStream.foreachBatch(process_batch)
             .option("checkpointLocation", "/tmp/ckpt-{}".format(os.environ.get("RUN_ID", "default")))
             .outputMode("append"))
    trigger = os.environ.get("SPARK_TRIGGER")
    print("spark_trigger={}".format(trigger or "default"), flush=True)
    if trigger:
        query = query.trigger(processingTime=trigger)
    query = query.start()
    query.awaitTermination()


if __name__ == "__main__":
    main()
