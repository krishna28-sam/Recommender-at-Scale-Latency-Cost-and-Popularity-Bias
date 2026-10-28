"""PyFlink local pass-through; requires the Kafka connector jar at runtime."""
import argparse
import os

from pyflink.common import Configuration, WatermarkStrategy
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.connectors.kafka import KafkaOffsetsInitializer, KafkaSource, KafkaSink
from pyflink.datastream.connectors.kafka import KafkaRecordSerializationSchema
from pyflink.common.serialization import SimpleStringSchema


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-topic", default="impressions")
    parser.add_argument("--output-topic", default="recommendations")
    parser.add_argument("--parallelism", type=int, default=1)
    args = parser.parse_args()
    bootstrap = os.environ.get("BOOTSTRAP_SERVERS", "localhost:29092")
    configuration = Configuration()
    env = StreamExecutionEnvironment.get_execution_environment(configuration)
    env.add_jars("file:///opt/flink/lib/flink-sql-connector-kafka-3.3.0-1.20.jar")
    env.set_parallelism(args.parallelism)
    source = (KafkaSource.builder().set_bootstrap_servers(bootstrap)
              .set_topics(args.input_topic).set_group_id("recommender-flink-pass-through")
              .set_starting_offsets(KafkaOffsetsInitializer.latest())
              .set_value_only_deserializer(SimpleStringSchema()).build())
    sink = (KafkaSink.builder().set_bootstrap_servers(bootstrap)
            .set_record_serializer(KafkaRecordSerializationSchema.builder()
                                   .set_topic(args.output_topic)
                                   .set_value_serialization_schema(SimpleStringSchema())
                                   .build()).build())
    env.from_source(source, WatermarkStrategy.no_watermarks(), "kafka-source").sink_to(sink)
    env.execute("recommender-flink-pass-through")


if __name__ == "__main__":
    main()
