#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# OpenForge EDA - macOS DMG Builder
#
# Creates a signed .app bundle and packages it into a DMG disk image.
#
# Usage:
#   ./create_dmg.sh [--version 0.1.0] [--sign "Developer ID"] [--notarize]
#
# Requirements:
#   - macOS 12+
#   - Python 3.12+
#   - Rust toolchain
#   - Node.js 20+
#   - create-dmg (brew install create-dmg)
#   - Xcode command line tools
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERSION=""
SIGN_IDENTITY=""
NOTARIZE=false
ARCH="$(uname -m)"  # arm64 or x86_64

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version)  VERSION="$2";        shift 2 ;;
        --sign)     SIGN_IDENTITY="$2";  shift 2 ;;
        --notarize) NOTARIZE=true;       shift ;;
        *)          echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Resolve version from pyproject.toml if not specified
if [[ -z "$VERSION" ]]; then
    VERSION=$(grep -m1 'version' "$REPO_ROOT/packages/core/pyproject.toml" \
        | sed 's/.*"\(.*\)".*/\1/')
fi

echo "==> Building OpenForge EDA v${VERSION} for macOS ${ARCH}"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BUILD_DIR="$SCRIPT_DIR/build"
APP_NAME="OpenForge EDA.app"
APP_DIR="$BUILD_DIR/$APP_NAME"
CONTENTS="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
FRAMEWORKS="$CONTENTS/Frameworks"
OUTPUT_DIR="$SCRIPT_DIR/output"
DMG_NAME="OpenForge-EDA-${VERSION}-macos-${ARCH}.dmg"

# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------
echo "==> Cleaning build directory"
rm -rf "$BUILD_DIR"
mkdir -p "$MACOS_DIR" "$RESOURCES" "$FRAMEWORKS" "$OUTPUT_DIR"

# ---------------------------------------------------------------------------
# Build Python packages
# ---------------------------------------------------------------------------
echo "==> Building Python packages"
WHEEL_DIR="$BUILD_DIR/wheels"
mkdir -p "$WHEEL_DIR"

for pkg in core cli api desktop crypto; do
    pkg_dir="$REPO_ROOT/packages/$pkg"
    if [[ -d "$pkg_dir" ]]; then
        echo "    Building $pkg..."
        pip3 wheel --no-deps --wheel-dir "$WHEEL_DIR" "$pkg_dir"
    fi
done

# ---------------------------------------------------------------------------
# Create embedded Python environment
# ---------------------------------------------------------------------------
echo "==> Creating embedded Python environment"
VENV_DIR="$RESOURCES/python"
python3.12 -m venv "$VENV_DIR" --copies

"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install "$WHEEL_DIR"/*.whl
"$VENV_DIR/bin/pip" install PySide6 QScintilla

# ---------------------------------------------------------------------------
# Build Rust tools
# ---------------------------------------------------------------------------
echo "==> Building Rust tools (release)"
cd "$REPO_ROOT"
cargo build --release

RUST_TOOLS=(openforge-ct openforge-sca openforge-entropy openforge-lint openforge-wave)
for tool in "${RUST_TOOLS[@]}"; do
    src="$REPO_ROOT/target/release/$tool"
    if [[ -f "$src" ]]; then
        cp "$src" "$MACOS_DIR/$tool"
        echo "    Staged $tool"
    else
        echo "    WARNING: $tool not found, skipping"
    fi
done

# ---------------------------------------------------------------------------
# Build web frontend
# ---------------------------------------------------------------------------
echo "==> Building web frontend"
WEB_DIR="$REPO_ROOT/packages/web"
if [[ -f "$WEB_DIR/package.json" ]]; then
    cd "$WEB_DIR"
    npm ci
    npm run build
    if [[ -d "$WEB_DIR/build" ]]; then
        mkdir -p "$RESOURCES/web"
        cp -r "$WEB_DIR/build/"* "$RESOURCES/web/"
    fi
fi

# ---------------------------------------------------------------------------
# Create launcher script
# ---------------------------------------------------------------------------
echo "==> Creating launcher script"
cat > "$MACOS_DIR/openforge-launcher" << 'LAUNCHER'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
RESOURCES="$DIR/../Resources"
PYTHON="$RESOURCES/python/bin/python3"
export PATH="$DIR:$PATH"
export PYTHONPATH="$RESOURCES/python/lib/python3.12/site-packages"
export QT_QPA_PLATFORM_PLUGIN_PATH="$RESOURCES/python/lib/python3.12/site-packages/PySide6/Qt/lib/QtCore.framework/../../../plugins/platforms"
exec "$PYTHON" -m openforge_desktop.main "$@"
LAUNCHER
chmod +x "$MACOS_DIR/openforge-launcher"

# CLI wrapper
cat > "$MACOS_DIR/openforge" << 'CLI'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
RESOURCES="$DIR/../Resources"
PYTHON="$RESOURCES/python/bin/python3"
export PYTHONPATH="$RESOURCES/python/lib/python3.12/site-packages"
exec "$PYTHON" -m openforge_cli.main "$@"
CLI
chmod +x "$MACOS_DIR/openforge"

# ---------------------------------------------------------------------------
# Copy Info.plist and icons
# ---------------------------------------------------------------------------
echo "==> Installing Info.plist and resources"
sed "s/0\.1\.0/${VERSION}/g" "$SCRIPT_DIR/Info.plist" > "$CONTENTS/Info.plist"

# Copy icon if available
if [[ -f "$REPO_ROOT/assets/openforge.icns" ]]; then
    cp "$REPO_ROOT/assets/openforge.icns" "$RESOURCES/openforge.icns"
else
    echo "    WARNING: openforge.icns not found. Using placeholder."
    touch "$RESOURCES/openforge.icns"
fi

# ---------------------------------------------------------------------------
# Fix library paths
# ---------------------------------------------------------------------------
echo "==> Fixing library paths"
# Update shebang lines in venv scripts to use relative paths
find "$VENV_DIR/bin" -type f -exec grep -l "$VENV_DIR" {} \; | while read -r f; do
    sed -i '' "s|$VENV_DIR|@executable_path/../Resources/python|g" "$f" 2>/dev/null || true
done

# ---------------------------------------------------------------------------
# Code signing
# ---------------------------------------------------------------------------
if [[ -n "$SIGN_IDENTITY" ]]; then
    echo "==> Code signing with identity: $SIGN_IDENTITY"

    # Sign all binaries and frameworks
    find "$APP_DIR" -type f \( -name "*.dylib" -o -name "*.so" -o -perm +111 \) | while read -r binary; do
        codesign --force --options runtime --timestamp \
            --sign "$SIGN_IDENTITY" "$binary" 2>/dev/null || true
    done

    # Sign the app bundle
    codesign --force --deep --options runtime --timestamp \
        --sign "$SIGN_IDENTITY" \
        --entitlements "$SCRIPT_DIR/entitlements.plist" \
        "$APP_DIR"

    echo "    App bundle signed."
else
    echo "    No signing identity provided. App bundle is unsigned."
fi

# ---------------------------------------------------------------------------
# Create DMG
# ---------------------------------------------------------------------------
echo "==> Creating DMG"
DMG_PATH="$OUTPUT_DIR/$DMG_NAME"

if command -v create-dmg &> /dev/null; then
    create-dmg \
        --volname "OpenForge EDA ${VERSION}" \
        --volicon "$RESOURCES/openforge.icns" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --icon "$APP_NAME" 150 190 \
        --app-drop-link 450 190 \
        --hide-extension "$APP_NAME" \
        --no-internet-enable \
        "$DMG_PATH" \
        "$BUILD_DIR/"
else
    echo "    create-dmg not found, using hdiutil directly"
    TEMP_DMG="$BUILD_DIR/temp.dmg"
    hdiutil create -srcfolder "$BUILD_DIR" -volname "OpenForge EDA ${VERSION}" \
        -fs HFS+ -fsargs "-c c=64,a=16,e=16" -format UDRW "$TEMP_DMG"
    hdiutil convert "$TEMP_DMG" -format UDZO -imagekey zlib-level=9 -o "$DMG_PATH"
    rm -f "$TEMP_DMG"
fi

# ---------------------------------------------------------------------------
# Notarization (optional)
# ---------------------------------------------------------------------------
if [[ "$NOTARIZE" == "true" && -n "$SIGN_IDENTITY" ]]; then
    echo "==> Submitting for notarization"
    xcrun notarytool submit "$DMG_PATH" \
        --keychain-profile "openforge-notarize" \
        --wait

    echo "==> Stapling notarization ticket"
    xcrun stapler staple "$DMG_PATH"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "==> Build complete"
echo "    DMG: $DMG_PATH"
echo "    Size: $(du -h "$DMG_PATH" | cut -f1)"
echo "    Version: $VERSION"
echo "    Architecture: $ARCH"
