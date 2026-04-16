# OpenForge EDA - production container
#
# Build:   docker build -f installer/Dockerfile -t openforge-eda:latest .
# Run CLI: docker run --rm -v ./workspace:/workspace openforge-eda openforge --help
# Run API: docker run -p 8000:8000 openforge-eda openforge serve --port 8000
# Run GUI: docker run -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix openforge-eda openforge-desktop

# ============================================================================
# Stage 1: builder -- install everything, compile what's needed
# ============================================================================
FROM ubuntu:24.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# -- system build deps -------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-dev python3.12-venv python3-pip \
    build-essential cmake git curl wget ca-certificates gnupg \
    software-properties-common \
 && rm -rf /var/lib/apt/lists/*

# -- EDA tools from apt (Ubuntu 24.04 repos) ---------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    yosys \
    iverilog verilator \
    ngspice \
    magic netgen-lvs \
    klayout \
    fpga-icestorm \
    openfpgaloader \
 && rm -rf /var/lib/apt/lists/*

# -- nextpnr (ice40 + ecp5) from YosysHQ nightly PPA or binary ---------------
RUN set -eux; \
    add-apt-repository -y ppa:yosyshq/tabby-cad 2>/dev/null \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        nextpnr-ice40 nextpnr-ecp5 \
    || echo "[warn] nextpnr packages not available from PPA, skipping"; \
    rm -rf /var/lib/apt/lists/*

# -- OpenROAD binary release --------------------------------------------------
RUN set -eux; \
    mkdir -p /opt/openroad; \
    curl -fsSL \
        "https://github.com/The-OpenROAD-Project/OpenROAD/releases/latest/download/openroad-ubuntu-24.04.tar.gz" \
        -o /tmp/openroad.tgz \
    && tar -xzf /tmp/openroad.tgz -C /opt/openroad --strip-components=1 \
    && ln -sf /opt/openroad/bin/openroad /usr/local/bin/openroad \
    || echo "[warn] OpenROAD binary not available for this arch, skipping"; \
    rm -f /tmp/openroad.tgz

# -- Verilator from source (get a recent version) ----------------------------
# Ubuntu 24.04 ships verilator ~5.x which is fine; skip source build.

# -- Python packages ----------------------------------------------------------
WORKDIR /opt/openforge
COPY pyproject.toml ./
COPY packages ./packages
COPY share ./share

RUN python3.12 -m pip install --no-cache-dir --break-system-packages \
      -e packages/core \
      -e packages/cli \
      -e packages/api \
      -e packages/crypto \
      -e packages/desktop \
 || python3.12 -m pip install --no-cache-dir --break-system-packages \
      -e packages/core \
      -e packages/cli

# ============================================================================
# Stage 2: runtime -- slim image with only what's needed
# ============================================================================
FROM ubuntu:24.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    QT_QPA_PLATFORM=offscreen \
    OPENFORGE_SHARE=/opt/openforge/share

# -- runtime system libs (no build tools) -------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv python3-pip \
    # PySide6 / Qt runtime
    libgl1 libglib2.0-0 libxkbcommon0 libdbus-1-3 libfontconfig1 \
    libx11-xcb1 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 \
    libxrender1 libxi6 libegl1 \
    # EDA tool runtime deps
    libtcl8.6 libtk8.6 libffi8 libreadline8t64 \
    ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

# -- Copy EDA tools from builder ----------------------------------------------
COPY --from=builder /usr/bin/yosys*          /usr/bin/
COPY --from=builder /usr/share/yosys/        /usr/share/yosys/
COPY --from=builder /usr/bin/iverilog        /usr/bin/
COPY --from=builder /usr/bin/vvp             /usr/bin/
COPY --from=builder /usr/bin/verilator*      /usr/bin/
COPY --from=builder /usr/bin/ngspice         /usr/bin/
COPY --from=builder /usr/bin/magic           /usr/bin/
COPY --from=builder /usr/bin/netgen          /usr/bin/
COPY --from=builder /usr/bin/klayout         /usr/bin/
COPY --from=builder /usr/bin/icepack         /usr/bin/
COPY --from=builder /usr/bin/iceprog         /usr/bin/
COPY --from=builder /usr/bin/openFPGALoader  /usr/bin/
# nextpnr (may not exist if PPA install failed)
COPY --from=builder /usr/bin/nextpnr*        /usr/bin/
# OpenROAD
COPY --from=builder /opt/openroad/           /opt/openroad/
RUN ln -sf /opt/openroad/bin/openroad /usr/local/bin/openroad 2>/dev/null || true

# -- Copy Python installation from builder ------------------------------------
COPY --from=builder /usr/lib/python3*/       /usr/lib/python3/
COPY --from=builder /usr/local/lib/python3*/ /usr/local/lib/python3.12/
COPY --from=builder /usr/local/bin/openforge* /usr/local/bin/

# -- Copy openforge source + share -------------------------------------------
WORKDIR /opt/openforge
COPY --from=builder /opt/openforge/ /opt/openforge/

ENV PATH="/opt/openforge/bin:/opt/openroad/bin:${PATH}"

EXPOSE 8000

# Default entrypoint: the openforge CLI. Override for desktop or API.
ENTRYPOINT ["openforge"]
CMD ["--help"]
