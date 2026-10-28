"""Spark Structured Streaming Kafka pass-through."""
import argparse
import os

from pyspark.sql import SparkSession


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-topic", default="impressions")
    parser.add_argument("--output-topic", default="recommendations")
    args = parser.parse_args()
    bootstrap = os.environ.get("BOOTSTRAP_SERVERS", "localhost:29092")
    spark = (SparkSession.builder.appName("recommender-pass-through")
             .getOrCreate())
    query = (spark.readStream.format("kafka")
             .option("kafka.bootstrap.servers", bootstrap)
             .option("subscribe", args.input_topic)
             .option("startingOffsets", "latest")
             .load()
             .selectExpr("CAST(key AS STRING) AS key", "value", "timestamp")
             .selectExpr("key", "value")
             .writeStream.format("kafka")
             .option("kafka.bootstrap.servers", bootstrap)
             .option("topic", args.output_topic)
             .option("checkpointLocation", "/tmp/ckpt-{}".format(os.environ.get("RUN_ID", "default")))
             .outputMode("append").start())
    query.awaitTermination()


if __name__ == "__main__":
    main()
