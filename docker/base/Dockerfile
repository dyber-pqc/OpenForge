FROM ubuntu:24.04

LABEL maintainer="Dyber Inc. <engineering@dyber.io>"
LABEL description="OpenForge EDA base image with common dependencies"

ENV DEBIAN_FRONTEND=noninteractive

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    libffi-dev \
    libssl-dev \
    pkg-config \
    curl \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Python virtual environment
RUN python3 -m venv /opt/openforge/venv
ENV PATH="/opt/openforge/venv/bin:${PATH}"

# Install uv for fast Python package management
RUN pip install uv

WORKDIR /workspace
