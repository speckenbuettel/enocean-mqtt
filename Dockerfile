# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml setup.py MANIFEST.in VERSION README.md LICENSE CREDITS.md ./
COPY src/ ./src/
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src HOME=/tmp
WORKDIR /app
COPY --from=builder /wheels/ /wheels/
RUN pip install --no-cache-dir --no-index /wheels/* && rm -rf /wheels \
    && groupadd --gid 1000 enocean && useradd --uid 1000 --gid 1000 --no-create-home enocean \
    && mkdir -p /app/config /app/data /app/export \
    && chown enocean:enocean /app/config /app/data /app/export
COPY src/ ./src/
COPY VERSION LICENSE CREDITS.md THIRD_PARTY_NOTICES.md enocean-mqtt.png ./
RUN python -m pip inspect --local > /app/python-packages.json
COPY eep/registry/ ./eep/registry/
COPY eep/semantic-aliases.json ./eep/semantic-aliases.json
COPY config/config.example.json config/device-controller-mappings.json /opt/enocean-defaults/
USER 1000:1000
EXPOSE 8001
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-m", "enocean_mqtt.container_runtime", "health"]
ENTRYPOINT ["python", "-m", "enocean_mqtt.container_runtime"]
