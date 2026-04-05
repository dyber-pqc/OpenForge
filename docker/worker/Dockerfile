FROM python:3.12-slim

LABEL maintainer="Dyber Inc. <engineering@dyber.io>"
LABEL description="OpenForge EDA Celery worker"

WORKDIR /app

# System dependencies for EDA tool interaction
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git docker.io && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY packages/core/ /app/packages/core/
COPY packages/api/ /app/packages/api/
COPY packages/crypto/ /app/packages/crypto/

RUN uv pip install --system \
    -e /app/packages/core \
    -e /app/packages/api \
    -e /app/packages/crypto \
    celery[redis]

CMD ["celery", "-A", "openforge_api.tasks", "worker", "--loglevel=info", "--concurrency=4"]
