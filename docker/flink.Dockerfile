FROM python:3.11-slim-bookworm
WORKDIR /opt/project
RUN apt-get update && apt-get install -y --no-install-recommends openjdk-17-jre-headless curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir apache-flink==1.20.1 confluent-kafka==2.6.1 PyYAML==6.0.2 \
    && mkdir -p /opt/flink/lib
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PYTHONPATH=/opt/project
ENV JAVA_OPTS=--add-opens=java.base/java.util=ALL-UNNAMED
ADD https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.3.0-1.20/flink-sql-connector-kafka-3.3.0-1.20.jar /opt/flink/lib/
COPY recsys recsys
COPY flink flink
COPY config config
