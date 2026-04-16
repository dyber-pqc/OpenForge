"""Build the macOS .dmg installer for OpenForge EDA.

Usage:
    python installer/build_macos.py [--codesign IDENTITY] [--notarize KEYCHAIN_PROFILE]

Steps:
    1. Run PyInstaller to produce dist/OpenForge.app
    2. Optionally codesign the app bundle
    3. Build a .dmg with create-dmg (preferred) or hdiutil
    4. Optionally notarize and staple the .dmg
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DIST = ROOT / "dist"
APP_NAME = "OpenForge"


def _read_version() -> str:
    try:
        import tomllib
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        return str(data.get("project", {}).get("version", "0.0.0"))
    except Exception:
        return "0.0.0"


APP_VERSION = _read_version()


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("$", " ".join(cmd))
    rc = subprocess.call(cmd, cwd=str(cwd) if cwd else None)
    if rc != 0:
        raise SystemExit(f"command failed: {' '.join(cmd)}")


def run_pyinstaller() -> Path:
    spec = HERE / "openforge.spec"
    if DIST.exists():
        shutil.rmtree(DIST, ignore_errors=True)
    run([sys.executable, "-m", "PyInstaller", "--clean", "-y", str(spec)], cwd=ROOT)
    app = DIST / f"{APP_NAME}.app"
    if not app.exists():
        raise SystemExit(f"PyInstaller did not produce {app}")
    return app


def codesign(app: Path, identity: str) -> None:
    print(f"[sign] {app} with {identity}")
    run([
        "codesign", "--force", "--deep", "--options", "runtime",
        "--sign", identity, str(app),
    ])
    run(["codesign", "--verify", "--deep", "--strict", str(app)])


def build_zip_fallback(app: Path) -> Path:
    """Zip the .app for non-darwin builds where hdiutil is unavailable."""
    import zipfile
    out = DIST / f"OpenForge-{APP_VERSION}-mac.zip"
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in app.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(app.parent))
    print(f"[zip] wrote {out}")
    return out


def build_dmg(app: Path) -> Path:
    dmg_path = DIST / f"OpenForge-{APP_VERSION}.dmg"
    if dmg_path.exists():
        dmg_path.unlink()
    if shutil.which("create-dmg") is not None:
        run([
            "create-dmg",
            "--volname", f"OpenForge {APP_VERSION}",
            "--window-size", "640", "400",
            "--icon-size", "100",
            "--app-drop-link", "480", "200",
            "--icon", f"{APP_NAME}.app", "160", "200",
            str(dmg_path), str(app),
        ])
    else:
        # Fallback to hdiutil
        staging = DIST / "dmg-staging"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir()
        shutil.copytree(app, staging / app.name)
        # /Applications symlink so users can drag-drop install
        os.symlink("/Applications", staging / "Applications")
        run([
            "hdiutil", "create", "-volname", f"OpenForge {APP_VERSION}",
            "-srcfolder", str(staging), "-ov", "-format", "UDZO",
            str(dmg_path),
        ])
    print(f"[dmg] wrote {dmg_path}")
    return dmg_path


def notarize(dmg: Path, profile: str) -> None:
    print(f"[notarize] {dmg} via keychain profile {profile}")
    run([
        "xcrun", "notarytool", "submit", str(dmg),
        "--keychain-profile", profile, "--wait",
    ])
    run(["xcrun", "stapler", "staple", str(dmg)])


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the OpenForge macOS .dmg")
    parser.add_argument("--codesign", help="Developer ID Application identity")
    parser.add_argument("--notarize", help="Keychain profile for notarytool")
    parser.add_argument("--check", action="store_true", help="Only validate prerequisites")
    args = parser.parse_args()

    if args.check:
        print(f"OpenForge version: {APP_VERSION}")
        print(f"Python: {sys.version}")
        print(f"platform: {sys.platform}")
        print(f"hdiutil: {shutil.which('hdiutil') or 'not found'}")
        print(f"create-dmg: {shutil.which('create-dmg') or 'not found'}")
        return 0

    app = run_pyinstaller()
    if args.codesign:
        codesign(app, args.codesign)
    if sys.platform == "darwin":
        dmg = build_dmg(app)
        if args.notarize:
            notarize(dmg, args.notarize)
        artifact = dmg
    else:
        print("[warn] not on darwin; producing portable .zip instead of .dmg")
        artifact = build_zip_fallback(app)

    if not artifact.exists():
        raise SystemExit(f"expected artifact missing: {artifact}")
    print(f"[done] macOS build complete -> {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
