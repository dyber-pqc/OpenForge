#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# OpenForge EDA - Conda build script (Linux / macOS)
# ============================================================================

echo "==> Building OpenForge EDA for conda (${target_platform})"

# ---------------------------------------------------------------------------
# Build and install Python packages
# ---------------------------------------------------------------------------
echo "==> Installing Python packages"
for pkg in core cli api desktop crypto; do
    pkg_dir="${SRC_DIR}/packages/${pkg}"
    if [ -d "$pkg_dir" ]; then
        echo "    Installing $pkg..."
        $PYTHON -m pip install --no-deps --no-build-isolation "$pkg_dir"
    fi
done

# ---------------------------------------------------------------------------
# Build Rust tools
# ---------------------------------------------------------------------------
echo "==> Building Rust tools"
export CARGO_HOME="${SRC_DIR}/.cargo"
mkdir -p "$CARGO_HOME"

cd "$SRC_DIR"
cargo build --release

# Install Rust binaries
RUST_TOOLS="openforge-ct openforge-sca openforge-entropy openforge-lint openforge-wave"
for tool in $RUST_TOOLS; do
    src="${SRC_DIR}/target/release/${tool}"
    if [ -f "$src" ]; then
        install -Dm755 "$src" "${PREFIX}/bin/${tool}"
        echo "    Installed $tool"
    else
        echo "    WARNING: $tool not found"
    fi
done

# ---------------------------------------------------------------------------
# Build web frontend (optional, for bundled web IDE)
# ---------------------------------------------------------------------------
echo "==> Building web frontend"
WEB_DIR="${SRC_DIR}/packages/web"
if [ -f "${WEB_DIR}/package.json" ]; then
    cd "$WEB_DIR"
    npm ci
    npm run build
    if [ -d "${WEB_DIR}/build" ]; then
        mkdir -p "${PREFIX}/share/openforge/web"
        cp -r "${WEB_DIR}/build/"* "${PREFIX}/share/openforge/web/"
    fi
fi

echo "==> Build complete"
