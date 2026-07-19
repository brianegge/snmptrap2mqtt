FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY snmptrap2mqtt ./snmptrap2mqtt
RUN pip install --no-cache-dir .

# Config is mounted at /app/data/config.yaml (zigbee2mqtt convention).
VOLUME ["/app/data"]

CMD ["snmptrap2mqtt", "-c", "/app/data/config.yaml"]
