FROM python:3.12-slim

LABEL maintainer="Dyber Inc. <engineering@dyber.io>"
LABEL description="OpenForge EDA API server"

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git && \
    rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
RUN pip install --no-cache-dir uv

# Copy and install Python packages
COPY packages/core/ /app/packages/core/
COPY packages/api/ /app/packages/api/
COPY packages/crypto/ /app/packages/crypto/

RUN uv pip install --system \
    -e /app/packages/core \
    -e /app/packages/api \
    -e /app/packages/crypto

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "openforge_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
