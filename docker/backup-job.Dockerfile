# syntax=docker/dockerfile:1

FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    I4G_RUNTIME__PROJECT_ROOT=/app

WORKDIR /app

# Install build deps, postgresql-client (for pg_dump), and cloud-sql-proxy.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    postgresql-client \
    && curl -fsSL https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.14.3/cloud-sql-proxy.linux.amd64 \
    -o /usr/local/bin/cloud-sql-proxy \
    && chmod +x /usr/local/bin/cloud-sql-proxy \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md VERSION.txt LICENSE ./
COPY src ./src

RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir .

RUN mkdir -p /app/data \
    && chown -R 65532:65532 /app

USER 65532:65532

ENV I4G_ENV=dev

ENTRYPOINT ["i4g", "jobs", "backup-db"]
