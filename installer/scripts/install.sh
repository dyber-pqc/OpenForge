#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# OpenForge EDA - Universal Install Script (Linux / macOS)
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/dyber-pqc/OpenForge/main/installer/scripts/install.sh | bash
#   # Or with options:
#   curl -fsSL ... | bash -s -- --version 0.1.0 --prefix ~/.local --with-docker
#
# Options:
#   --version VERSION    Install specific version (default: latest)
#   --prefix  PATH       Installation prefix (default: /usr/local)
#   --with-docker        Also pull Docker images for EDA tools
#   --no-rust            Skip Rust binary installation
#   --help               Show this help message
# ============================================================================

VERSION="latest"
PREFIX="/usr/local"
WITH_DOCKER=false
INSTALL_RUST=true
GITHUB_REPO="dyber-pqc/OpenForge"
GITHUB_API="https://api.github.com/repos/${GITHUB_REPO}"

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()     { error "$@"; exit 1; }

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version)     VERSION="$2";  shift 2 ;;
        --prefix)      PREFIX="$2";   shift 2 ;;
        --with-docker) WITH_DOCKER=true; shift ;;
        --no-rust)     INSTALL_RUST=false; shift ;;
        --help)
            head -n 20 "$0" | grep '^#' | sed 's/^# \?//'
            exit 0
            ;;
        *) die "Unknown option: $1" ;;
    esac
done

# ---------------------------------------------------------------------------
# Detect platform
# ---------------------------------------------------------------------------
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Linux)  PLATFORM="linux" ;;
    Darwin) PLATFORM="macos" ;;
    *)      die "Unsupported operating system: $OS" ;;
esac

case "$ARCH" in
    x86_64|amd64)  ARCH="x86_64" ;;
    aarch64|arm64) ARCH="aarch64" ;;
    *)             die "Unsupported architecture: $ARCH" ;;
esac

info "Detected platform: ${PLATFORM}-${ARCH}"

# ---------------------------------------------------------------------------
# Check prerequisites
# ---------------------------------------------------------------------------
info "Checking prerequisites..."

check_cmd() {
    if command -v "$1" &> /dev/null; then
        success "$1 found: $(command -v "$1")"
        return 0
    else
        return 1
    fi
}

# Python 3.12+
if check_cmd python3; then
    PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
    if [[ "$PY_MAJOR" -lt 3 ]] || [[ "$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 12 ]]; then
        die "Python 3.12+ required, found $PY_VERSION"
    fi
    success "Python $PY_VERSION"
else
    die "Python 3 not found. Install Python 3.12+ first:
  Linux: sudo apt install python3.12 python3.12-venv
  macOS: brew install python@3.12"
fi

check_cmd pip3 || check_cmd pip || die "pip not found. Install with: python3 -m ensurepip"
check_cmd curl || check_cmd wget || die "curl or wget required for downloads"

# ---------------------------------------------------------------------------
# Resolve version
# ---------------------------------------------------------------------------
if [[ "$VERSION" == "latest" ]]; then
    info "Resolving latest release..."
    if command -v curl &> /dev/null; then
        VERSION=$(curl -fsSL "${GITHUB_API}/releases/latest" | grep '"tag_name"' | sed 's/.*"v\(.*\)".*/\1/')
    else
        VERSION=$(wget -qO- "${GITHUB_API}/releases/latest" | grep '"tag_name"' | sed 's/.*"v\(.*\)".*/\1/')
    fi
    if [[ -z "$VERSION" ]]; then
        die "Could not determine latest version. Specify --version manually."
    fi
fi
info "Installing OpenForge EDA v${VERSION}"

# ---------------------------------------------------------------------------
# Create temp directory
# ---------------------------------------------------------------------------
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT
cd "$TMPDIR"

# ---------------------------------------------------------------------------
# Download helper
# ---------------------------------------------------------------------------
download() {
    local url="$1" dest="$2"
    info "Downloading: $(basename "$dest")"
    if command -v curl &> /dev/null; then
        curl -fsSL -o "$dest" "$url"
    else
        wget -q -O "$dest" "$url"
    fi
}

# ---------------------------------------------------------------------------
# Install Python packages
# ---------------------------------------------------------------------------
info "Installing Python packages..."
RELEASE_URL="https://github.com/${GITHUB_REPO}/releases/download/v${VERSION}"

PYTHON_PKGS=(
    "openforge_core-${VERSION}-py3-none-any.whl"
    "openforge_cli-${VERSION}-py3-none-any.whl"
    "openforge_api-${VERSION}-py3-none-any.whl"
    "openforge_desktop-${VERSION}-py3-none-any.whl"
    "openforge_crypto-${VERSION}-py3-none-any.whl"
)

for pkg in "${PYTHON_PKGS[@]}"; do
    download "${RELEASE_URL}/${pkg}" "${TMPDIR}/${pkg}" || {
        warn "Failed to download ${pkg}, skipping"
        continue
    }
done

pip3 install --user "${TMPDIR}"/*.whl 2>/dev/null || \
    pip3 install "${TMPDIR}"/*.whl

success "Python packages installed"

# ---------------------------------------------------------------------------
# Install Rust binaries
# ---------------------------------------------------------------------------
if [[ "$INSTALL_RUST" == "true" ]]; then
    info "Installing Rust tools..."

    RUST_ARCHIVE="openforge-rust-tools-${VERSION}-${PLATFORM}-${ARCH}.tar.gz"
    download "${RELEASE_URL}/${RUST_ARCHIVE}" "${TMPDIR}/${RUST_ARCHIVE}" || {
        warn "Rust tools archive not found for ${PLATFORM}-${ARCH}. Skipping."
        INSTALL_RUST=false
    }

    if [[ "$INSTALL_RUST" == "true" ]]; then
        mkdir -p "${TMPDIR}/rust-tools"
        tar -xzf "${TMPDIR}/${RUST_ARCHIVE}" -C "${TMPDIR}/rust-tools"

        BINDIR="${PREFIX}/bin"
        if [[ -w "$BINDIR" ]]; then
            cp "${TMPDIR}/rust-tools/"openforge-* "$BINDIR/"
        else
            info "Installing to ${BINDIR} requires sudo..."
            sudo mkdir -p "$BINDIR"
            sudo cp "${TMPDIR}/rust-tools/"openforge-* "$BINDIR/"
        fi
        chmod +x "${BINDIR}"/openforge-*
        success "Rust tools installed to ${BINDIR}"
    fi
fi

# ---------------------------------------------------------------------------
# Configure PATH
# ---------------------------------------------------------------------------
info "Configuring PATH..."

USER_BIN="$(python3 -m site --user-base)/bin"
SHELL_RC=""
case "$(basename "${SHELL:-/bin/bash}")" in
    bash) SHELL_RC="$HOME/.bashrc" ;;
    zsh)  SHELL_RC="$HOME/.zshrc" ;;
    fish) SHELL_RC="$HOME/.config/fish/config.fish" ;;
esac

PATH_UPDATED=false
if [[ -n "$SHELL_RC" ]]; then
    # Add user bin to PATH if not already present
    if ! grep -q "openforge" "$SHELL_RC" 2>/dev/null; then
        {
            echo ""
            echo "# OpenForge EDA"
            echo "export PATH=\"${USER_BIN}:\${PATH}\""
        } >> "$SHELL_RC"
        PATH_UPDATED=true
    fi

    # Also add /usr/local/bin if Rust tools installed there
    if [[ "$INSTALL_RUST" == "true" && "$PREFIX" != "/usr/local" ]]; then
        if ! grep -q "${PREFIX}/bin" "$SHELL_RC" 2>/dev/null; then
            echo "export PATH=\"${PREFIX}/bin:\${PATH}\"" >> "$SHELL_RC"
        fi
    fi
fi

export PATH="${USER_BIN}:${PREFIX}/bin:${PATH}"

# ---------------------------------------------------------------------------
# Docker images (optional)
# ---------------------------------------------------------------------------
if [[ "$WITH_DOCKER" == "true" ]]; then
    info "Pulling Docker images for EDA tools..."
    if check_cmd docker; then
        DOCKER_IMAGES=(
            "ghcr.io/dyber-pqc/openforge-yosys:latest"
            "ghcr.io/dyber-pqc/openforge-nextpnr:latest"
            "ghcr.io/dyber-pqc/openforge-verilator:latest"
            "ghcr.io/dyber-pqc/openforge-ghdl:latest"
        )
        for img in "${DOCKER_IMAGES[@]}"; do
            info "  Pulling $img"
            docker pull "$img" || warn "Failed to pull $img"
        done
        success "Docker images pulled"
    else
        warn "Docker not found. Skipping Docker image installation."
        warn "Install Docker: https://docs.docker.com/get-docker/"
    fi
fi

# ---------------------------------------------------------------------------
# Verify installation
# ---------------------------------------------------------------------------
info "Verifying installation..."

if command -v openforge &> /dev/null; then
    success "openforge CLI: $(openforge --version 2>/dev/null || echo 'installed')"
else
    warn "openforge CLI not found in PATH. You may need to restart your shell."
fi

if [[ "$INSTALL_RUST" == "true" ]]; then
    for tool in openforge-ct openforge-sca openforge-entropy openforge-lint openforge-wave; do
        if command -v "$tool" &> /dev/null; then
            success "$tool: installed"
        else
            warn "$tool: not found in PATH"
        fi
    done
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  OpenForge EDA v${VERSION} installed successfully!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "  Getting started:"
echo "    openforge --help           # CLI reference"
echo "    openforge init my-project  # Create a new project"
echo "    openforge-desktop          # Launch desktop GUI"
echo ""
if [[ "$PATH_UPDATED" == "true" ]]; then
    echo "  NOTE: Restart your shell or run:"
    echo "    source ${SHELL_RC}"
    echo ""
fi
echo "  Documentation: https://github.com/dyber-pqc/OpenForge"
echo "  Issues:        https://github.com/dyber-pqc/OpenForge/issues"
echo ""
