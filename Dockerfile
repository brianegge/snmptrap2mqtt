FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY snmptrap2mqtt ./snmptrap2mqtt
RUN pip install --no-cache-dir .

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Standalone: mount your config at /app/data/config.yaml (zigbee2mqtt
# convention). As a Home Assistant add-on, HA supplies /data/options.json
# instead and the entrypoint switches automatically.
VOLUME ["/app/data"]

ENTRYPOINT ["/docker-entrypoint.sh"]
