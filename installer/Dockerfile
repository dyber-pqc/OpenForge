# OpenForge EDA - production container
#
# Build:   docker build -f installer/Dockerfile -t openforge-eda:latest .
# Run CLI: docker run --rm -v ./workspace:/workspace openforge-eda --help
# Run API: docker run -p 8000:8000 openforge-eda serve --port 8000

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    QT_QPA_PLATFORM=offscreen

# -- System packages + EDA tools ---------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    build-essential git curl wget ca-certificates \
    # EDA tools available in Ubuntu 24.04
    yosys iverilog verilator ngspice magic klayout \
    # Qt runtime deps
    libgl1 libglib2.0-0 libxkbcommon0 libdbus-1-3 libfontconfig1 libegl1 \
 && rm -rf /var/lib/apt/lists/*

# -- Optional tools (skip if not in apt) --------------------------------------
RUN apt-get update \
 && for pkg in fpga-icestorm nextpnr-ice40 nextpnr-ecp5 openfpgaloader; do \
      apt-get install -y --no-install-recommends "$pkg" 2>/dev/null || true; \
    done \
 && rm -rf /var/lib/apt/lists/*

# -- Python deps --------------------------------------------------------------
RUN pip install --no-cache-dir --break-system-packages \
    pydantic pyyaml numpy typer rich networkx

# -- Copy OpenForge source ----------------------------------------------------
WORKDIR /opt/openforge
COPY packages ./packages
COPY share ./share
COPY pyproject.toml README.md LICENSE ./
COPY examples ./examples

ENV PYTHONPATH="/opt/openforge/packages/core/src:/opt/openforge/packages/cli/src:/opt/openforge/packages/desktop/src:/opt/openforge/packages/api/src" \
    OPENFORGE_SHARE="/opt/openforge/share"

EXPOSE 8000

ENTRYPOINT ["python3", "-m", "openforge_cli.main"]
CMD ["--help"]
