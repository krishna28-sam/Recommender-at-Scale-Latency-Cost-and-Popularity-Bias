FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir confluent-kafka==2.6.1
COPY producer ./producer
ENTRYPOINT ["python", "-m", "producer.replay"]
