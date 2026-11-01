FROM apache/spark:3.5.3-python3
USER root
RUN python3 --version && \
    apt-get update && \
    apt-get install -y --no-install-recommends curl gcc librdkafka-dev && \
    rm -rf /var/lib/apt/lists/* && \
    python3 -m pip install --no-cache-dir --upgrade pip && \
    python3 -m pip install --no-cache-dir confluent-kafka==2.6.1 PyYAML==6.0.2 && \
    curl -fsSL https://repo1.maven.org/maven2/org/apache/spark/spark-sql-kafka-0-10_2.12/3.5.3/spark-sql-kafka-0-10_2.12-3.5.3.jar -o /opt/spark/jars/spark-sql-kafka-0-10_2.12-3.5.3.jar && \
    curl -fsSL https://repo1.maven.org/maven2/org/apache/spark/spark-token-provider-kafka-0-10_2.12/3.5.3/spark-token-provider-kafka-0-10_2.12-3.5.3.jar -o /opt/spark/jars/spark-token-provider-kafka-0-10_2.12-3.5.3.jar && \
    curl -fsSL https://repo1.maven.org/maven2/org/apache/kafka/kafka-clients/3.4.1/kafka-clients-3.4.1.jar -o /opt/spark/jars/kafka-clients-3.4.1.jar && \
    curl -fsSL https://repo1.maven.org/maven2/org/apache/commons/commons-pool2/2.11.1/commons-pool2-2.11.1.jar -o /opt/spark/jars/commons-pool2-2.11.1.jar
COPY spark spark
COPY recsys recsys
COPY config config
USER spark
ENV PYTHONPATH=/opt/spark/work-dir
