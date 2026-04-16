# -*- mode: python ; coding: utf-8 -*-
# OpenForge EDA Desktop - PyInstaller spec file
#
# Build with:
#     pyinstaller installer/openforge.spec
#
# This produces a one-folder distribution under dist/openforge/ that bundles
# the desktop GUI, the openforge_core library, the SkyWater 130 PDK files
# we ship out of the box, the open-source IP catalogue, and the example
# projects.

import os
import sys
from pathlib import Path

block_cipher = None

# Resolve project root from the spec file location.
SPEC_DIR = Path(os.path.abspath(SPECPATH))  # noqa: F821
PROJECT_ROOT = SPEC_DIR.parent

# Read version from root pyproject.toml so installer metadata stays in sync.
try:
    import tomllib
    _pyproj = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    OPENFORGE_VERSION = str(_pyproj.get("project", {}).get("version", "0.0.0"))
except Exception:
    OPENFORGE_VERSION = "0.0.0"

DESKTOP_SRC = PROJECT_ROOT / "packages" / "desktop" / "src"
CORE_SRC = PROJECT_ROOT / "packages" / "core" / "src"
CRYPTO_SRC = PROJECT_ROOT / "packages" / "crypto" / "src"

# Optional shared resources — we ship them if they exist on disk.
def _include(source: Path, target: str):
    return (str(source), target) if source.exists() else None


candidate_datas = [
    _include(PROJECT_ROOT / "share" / "pdk" / "sky130" / "lef", "share/pdk/sky130/lef"),
    _include(PROJECT_ROOT / "share" / "pdk" / "sky130" / "lib", "share/pdk/sky130/lib"),
    _include(PROJECT_ROOT / "share" / "pdk" / "sky130" / "tech", "share/pdk/sky130/tech"),
    _include(PROJECT_ROOT / "share" / "ip", "share/ip"),
    _include(PROJECT_ROOT / "share" / "themes", "share/themes"),
    _include(PROJECT_ROOT / "examples", "examples"),
    _include(PROJECT_ROOT / "packages" / "desktop" / "resources", "resources"),
]
datas = [d for d in candidate_datas if d is not None]

hiddenimports = [
    # Qt modules used dynamically
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtSvg",
    "PySide6.QtSvgWidgets",
    "PySide6.QtNetwork",
    # Desktop submodules loaded by name
    "openforge_desktop.panels.gds_viewer",
    "openforge_desktop.panels.welcome",
    "openforge_desktop.panels.netlist",
    "openforge_desktop.panels.waveform",
    "openforge_desktop.panels.editor",
    "openforge_desktop.panels.tcl_console",
    "openforge_desktop.panels.block_designer",
    "openforge_desktop.dialogs.command_palette",
    "openforge_desktop.dialogs.tutorial",
    "openforge_desktop.dialogs.wsl_setup",
    "openforge_desktop.dialogs.pdk_installer",
    "openforge_desktop.dialogs.auto_update",
    "openforge_desktop.notifications",
    # Core engines
    "openforge.engine.yosys",
    "openforge.engine.openroad",
    "openforge.engine.iverilog",
    "openforge.engine.verilator",
    "openforge.engine.magic",
    "openforge.engine.netgen",
    "openforge.engine.klayout",
    "openforge.engine.opensta",
    "openforge.engine.nextpnr",
    # Pydantic v2 models pulled by name
    "pydantic",
    "pydantic_core",
]

a = Analysis(
    [str(DESKTOP_SRC / "openforge_desktop" / "main.py")],
    pathex=[
        str(DESKTOP_SRC),
        str(CORE_SRC),
        str(CRYPTO_SRC),
    ],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib.tests",
        "numpy.tests",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="openforge",
    icon=str(SPEC_DIR / "openforge.ico") if (SPEC_DIR / "openforge.ico").exists() else None,
    console=False,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="openforge",
)

# macOS .app bundle (only used on darwin)
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="OpenForge.app",
        icon=str(SPEC_DIR / "openforge.icns") if (SPEC_DIR / "openforge.icns").exists() else None,
        bundle_identifier="dev.openforge.desktop",
        info_plist={
            "CFBundleName": "OpenForge",
            "CFBundleDisplayName": "OpenForge EDA",
            "CFBundleShortVersionString": OPENFORGE_VERSION,
            "CFBundleVersion": OPENFORGE_VERSION,
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.developer-tools",
        },
    )
