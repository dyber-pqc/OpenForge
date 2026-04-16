"""Cross-platform build dispatcher for OpenForge EDA.

Detects the host OS and runs the matching platform-specific builder script.

Usage:
    python installer/build_all.py [--check] [extra args forwarded to platform builder]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    plat = sys.platform
    if plat.startswith("win"):
        script = HERE / "build_windows.py"
    elif plat == "darwin":
        script = HERE / "build_macos.py"
    elif plat.startswith("linux"):
        script = HERE / "build_linux.py"
    else:
        print(f"[error] unsupported platform: {plat}")
        return 1

    print(f"[build_all] host={plat} -> {script.name}")
    forwarded = sys.argv[1:]
    rc = subprocess.call([sys.executable, str(script), *forwarded])
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
