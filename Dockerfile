FROM python:3.15-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.20 /uv /bin/uv

# Use the image's Python, and copy (not hardlink) out of the cache mount.
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy

WORKDIR /app

# Dependencies first, from uv.lock, so code changes reuse this layer.
# --no-build takes them as wheels only, the same as CI.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-build --no-install-project --no-editable

COPY pyproject.toml uv.lock README.md ./
COPY snmptrap2mqtt ./snmptrap2mqtt
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-build --no-editable


FROM python:3.15-slim

# Only the venv ships; uv and the source tree stay in the builder.
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Standalone: mount your config at /app/data/config.yaml (zigbee2mqtt
# convention). As a Home Assistant add-on, HA supplies /data/options.json
# instead and the entrypoint switches automatically.
VOLUME ["/app/data"]

ENTRYPOINT ["/docker-entrypoint.sh"]
