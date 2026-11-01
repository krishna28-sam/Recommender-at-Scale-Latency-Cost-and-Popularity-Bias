"""PyFlink local pass-through; requires the Kafka connector jar at runtime."""
import argparse
import json
import os

from pyflink.common import Configuration, Types, WatermarkStrategy
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.connectors.kafka import KafkaOffsetsInitializer, KafkaSource, KafkaSink
from pyflink.datastream.connectors.kafka import KafkaRecordSerializationSchema
from pyflink.common.serialization import SimpleStringSchema
from recsys.streaming import EventScorer, pass_through


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-topic", default="impressions")
    parser.add_argument("--output-topic", default="recommendations")
    parser.add_argument("--parallelism", type=int, default=1)
    parser.add_argument("--mode", choices=("score", "pass-through"), default=os.environ.get("ENGINE_MODE", "score"))
    parser.add_argument("--mapping", default=os.environ.get("MAPPING", "random_101"))
    parser.add_argument("--lambda-value", type=float, default=float(os.environ.get("LAMBDA", "0.0")))
    args = parser.parse_args()
    print("engine_parallelism={}".format(args.parallelism), flush=True)
    bootstrap = os.environ.get("BOOTSTRAP_SERVERS", "localhost:29092")
    scorer = None
    if args.mode == "score":
        scorer = EventScorer(os.environ.get("MODEL_TABLE_DIR", "data/processed/model_tables"),
                             args.mapping, args.lambda_value, "flink")
    configuration = Configuration()
    bundle_time = os.environ.get("FLINK_BUNDLE_TIME_MS")
    if bundle_time:
        configuration.set_string("python.fn-execution.bundle.time", str(bundle_time))
    env = StreamExecutionEnvironment.get_execution_environment(configuration)
    env.add_jars("file:///opt/flink/lib/flink-sql-connector-kafka-3.3.0-1.20.jar")
    env.set_parallelism(args.parallelism)
    source = (KafkaSource.builder().set_bootstrap_servers(bootstrap)
              .set_topics(args.input_topic).set_group_id("recommender-flink-pass-through")
              .set_starting_offsets(KafkaOffsetsInitializer.earliest())
              .set_value_only_deserializer(SimpleStringSchema()).build())
    sink = (KafkaSink.builder().set_bootstrap_servers(bootstrap)
            .set_record_serializer(KafkaRecordSerializationSchema.builder()
                                   .set_topic(args.output_topic)
                                   .set_value_serialization_schema(SimpleStringSchema())
                                   .build()).build())
    def process(value):
        event = json.loads(value)
        result = pass_through(event, "flink") if scorer is None else scorer.score(event)
        return json.dumps(result)

    env.from_source(source, WatermarkStrategy.no_watermarks(), "kafka-source").map(
        process, output_type=Types.STRING()).sink_to(sink)
    env.execute("recommender-flink-pass-through")


if __name__ == "__main__":
    main()
