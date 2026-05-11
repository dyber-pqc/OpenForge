#!/usr/bin/env bash
# OpenForge sign-off binaries — one-line installer for Linux & macOS.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/dyber-pqc/OpenForge/main/scripts/install.sh | bash
#   curl -fsSL .../install.sh | bash -s -- --version v0.3.0 --prefix ~/.local/bin
#
# Downloads the latest (or pinned) signoff archive for the current platform,
# verifies the SHA-256 checksum, extracts the three binaries to the install
# prefix, and runs --version on each to confirm.
set -euo pipefail

REPO="dyber-pqc/OpenForge"
PREFIX="/usr/local/bin"
VERSION=""

usage() {
    cat <<EOF
OpenForge sign-off installer.

Options:
  --version <vX.Y.Z>   Install a specific tag (default: latest release)
  --prefix <dir>       Install directory (default: /usr/local/bin)
  -h, --help           Show this message

Environment:
  OPENFORGE_VERSION    Same as --version
  OPENFORGE_PREFIX     Same as --prefix
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --version) VERSION="$2"; shift 2 ;;
        --prefix)  PREFIX="$2";  shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown arg: $1" >&2; usage; exit 2 ;;
    esac
done
VERSION="${VERSION:-${OPENFORGE_VERSION:-}}"
PREFIX="${OPENFORGE_PREFIX:-$PREFIX}"

# -- Detect platform ---------------------------------------------------------
uname_s="$(uname -s)"
uname_m="$(uname -m)"
case "$uname_s" in
    Linux*)  PLATFORM="linux" ;;
    Darwin*) PLATFORM="macos" ;;
    *) echo "Unsupported OS: $uname_s" >&2; exit 1 ;;
esac
case "$uname_m" in
    x86_64|amd64) ARCH="x86_64" ;;
    arm64|aarch64) ARCH="x86_64" ; echo "warning: only x86_64 archives published; will try anyway" >&2 ;;
    *) echo "Unsupported arch: $uname_m" >&2; exit 1 ;;
esac

# -- Resolve version ---------------------------------------------------------
if [[ -z "$VERSION" ]]; then
    echo "==> Resolving latest release..."
    VERSION="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
               | grep -oE '"tag_name": *"[^"]+"' | head -n1 | sed -E 's/.*"([^"]+)"/\1/')"
    if [[ -z "$VERSION" ]]; then
        echo "Could not resolve latest release tag." >&2
        exit 1
    fi
fi
echo "==> Installing OpenForge sign-off ${VERSION} for ${PLATFORM}-${ARCH} into ${PREFIX}"

ARCHIVE="openforge-signoff-${PLATFORM}-${ARCH}.tar.gz"
URL="https://github.com/${REPO}/releases/download/${VERSION}/${ARCHIVE}"
SUMS_URL="https://github.com/${REPO}/releases/download/${VERSION}/checksums.txt"

# -- Download + verify -------------------------------------------------------
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> Downloading $URL"
curl -fsSL -o "$TMP/$ARCHIVE" "$URL"

echo "==> Verifying SHA-256"
if curl -fsSL -o "$TMP/checksums.txt" "$SUMS_URL"; then
    expected="$(grep " ${ARCHIVE}\$" "$TMP/checksums.txt" | awk '{print $1}')"
    if [[ -n "$expected" ]]; then
        if command -v sha256sum >/dev/null 2>&1; then
            actual="$(sha256sum "$TMP/$ARCHIVE" | awk '{print $1}')"
        else
            actual="$(shasum -a 256 "$TMP/$ARCHIVE" | awk '{print $1}')"
        fi
        if [[ "$expected" != "$actual" ]]; then
            echo "Checksum mismatch! expected=$expected actual=$actual" >&2
            exit 1
        fi
        echo "    OK ($actual)"
    else
        echo "    (no entry for ${ARCHIVE} in checksums.txt — skipping)"
    fi
else
    echo "    (checksums.txt unavailable — skipping verification)"
fi

# -- Extract + install -------------------------------------------------------
mkdir -p "$TMP/extract"
tar -xzf "$TMP/$ARCHIVE" -C "$TMP/extract"

SUDO=""
if [[ ! -w "$PREFIX" ]]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
        echo "==> $PREFIX is not writable; using sudo"
    else
        echo "$PREFIX is not writable and sudo is not available." >&2
        exit 1
    fi
fi
$SUDO mkdir -p "$PREFIX"

for tool in openforge-drc openforge-lvs openforge-xrc; do
    $SUDO install -m 0755 "$TMP/extract/$tool" "$PREFIX/$tool"
    echo "    installed $PREFIX/$tool"
done

# -- Verify ------------------------------------------------------------------
echo "==> Verifying install"
for tool in openforge-drc openforge-lvs openforge-xrc; do
    if ! "$PREFIX/$tool" --version >/dev/null 2>&1; then
        echo "warning: $tool --version failed" >&2
    else
        echo "    $($PREFIX/$tool --version)"
    fi
done

echo
echo "Done. Make sure $PREFIX is on your PATH:"
echo "    export PATH=\"$PREFIX:\$PATH\""
