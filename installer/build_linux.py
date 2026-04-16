"""Build Linux distributions for OpenForge EDA.

Usage:
    python installer/build_linux.py [--appimage | --flatpak | --snap | --all]

The default is --appimage. AppImage is the preferred format because it
runs without needing root or extra runtimes.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DIST = ROOT / "dist"
APP_NAME = "openforge"
APP_ID = "dev.openforge.OpenForge"


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
    out = DIST / "openforge"
    if not out.exists():
        raise SystemExit(f"PyInstaller did not produce {out}")
    return out


# ---------------------------------------------------------------------------
# AppImage
# ---------------------------------------------------------------------------


def build_appimage(app_dir: Path) -> Path:
    appdir = DIST / "OpenForge.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)
    (appdir / "usr" / "bin").mkdir(parents=True)
    (appdir / "usr" / "share" / "applications").mkdir(parents=True)
    (appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps").mkdir(parents=True)

    # Copy PyInstaller dist into the AppDir
    target = appdir / "usr" / "bin" / "openforge-bundle"
    shutil.copytree(app_dir, target)

    # AppRun
    apprun = appdir / "AppRun"
    apprun.write_text(
        textwrap.dedent(
            """
            #!/bin/bash
            HERE="$(dirname "$(readlink -f "${0}")")"
            export PATH="$HERE/usr/bin/openforge-bundle:$PATH"
            exec "$HERE/usr/bin/openforge-bundle/openforge" "$@"
            """
        ).strip()
        + "\n"
    )
    apprun.chmod(0o755)

    # .desktop file
    desktop = appdir / f"{APP_ID}.desktop"
    desktop.write_text(
        textwrap.dedent(
            f"""
            [Desktop Entry]
            Type=Application
            Name=OpenForge EDA
            Comment=Open-source silicon design from RTL to GDSII
            Exec=openforge %F
            Icon={APP_ID}
            Categories=Development;Electronics;
            MimeType=application/x-openforge-project;
            Terminal=false
            """
        ).strip()
        + "\n"
    )
    shutil.copy(desktop, appdir / "usr" / "share" / "applications" / desktop.name)

    # Icon (placeholder if missing)
    icon_src = HERE / "openforge.png"
    icon_dst = appdir / f"{APP_ID}.png"
    if icon_src.exists():
        shutil.copy(icon_src, icon_dst)
    else:
        icon_dst.write_bytes(b"")
    shutil.copy(
        icon_dst,
        appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps" / icon_dst.name,
    )

    # Run appimagetool
    appimagetool = shutil.which("appimagetool") or shutil.which("appimagetool-x86_64.AppImage")
    if appimagetool is None:
        print("[warn] appimagetool not found; falling back to .tar.gz")
        return build_tarball(app_dir)
    out = DIST / f"OpenForge-{APP_VERSION}-x86_64.AppImage"
    run([appimagetool, str(appdir), str(out)])
    print(f"[appimage] wrote {out}")
    return out


def build_tarball(app_dir: Path) -> Path:
    """Plain .tar.gz bundle for systems without appimagetool."""
    import tarfile
    out = DIST / f"OpenForge-{APP_VERSION}-linux-x64.tar.gz"
    if out.exists():
        out.unlink()
    with tarfile.open(out, "w:gz") as tf:
        tf.add(app_dir, arcname=f"OpenForge-{APP_VERSION}")
    print(f"[tar] wrote {out}")
    return out


# ---------------------------------------------------------------------------
# Flatpak
# ---------------------------------------------------------------------------


def build_flatpak() -> None:
    manifest = HERE / f"{APP_ID}.yml"
    manifest.write_text(
        textwrap.dedent(
            f"""
            app-id: {APP_ID}
            runtime: org.kde.Platform
            runtime-version: '6.6'
            sdk: org.kde.Sdk
            command: openforge
            finish-args:
              - --share=ipc
              - --socket=fallback-x11
              - --socket=wayland
              - --share=network
              - --device=dri
              - --filesystem=home
            modules:
              - name: openforge
                buildsystem: simple
                build-commands:
                  - install -Dm755 openforge /app/bin/openforge
                sources:
                  - type: dir
                    path: ../dist/openforge
            """
        ).strip()
        + "\n"
    )
    flatpak_builder = shutil.which("flatpak-builder")
    if flatpak_builder is None:
        raise SystemExit("flatpak-builder not found; install flatpak-builder")
    run([flatpak_builder, "--force-clean", str(DIST / "flatpak-build"), str(manifest)])
    print("[flatpak] build complete")


# ---------------------------------------------------------------------------
# Snap
# ---------------------------------------------------------------------------


def build_snap() -> None:
    snap_dir = HERE / "snap"
    snap_dir.mkdir(exist_ok=True)
    (snap_dir / "snapcraft.yaml").write_text(
        textwrap.dedent(
            f"""
            name: openforge
            base: core22
            version: '{APP_VERSION}'
            summary: Open-source silicon design from RTL to GDSII
            description: |
              OpenForge is an open-source EDA platform covering ASIC and FPGA flows
              with synthesis, simulation, place-and-route, DRC, LVS, and crypto IP
              verification.
            grade: stable
            confinement: classic
            apps:
              openforge:
                command: bin/openforge
                plugs: [home, network, opengl, x11, wayland]
            parts:
              openforge:
                plugin: dump
                source: ../dist/openforge
                organize:
                  '*': bin/
            """
        ).strip()
        + "\n"
    )
    snapcraft = shutil.which("snapcraft")
    if snapcraft is None:
        raise SystemExit("snapcraft not found; install via 'sudo snap install snapcraft --classic'")
    run([snapcraft], cwd=snap_dir)
    print("[snap] build complete")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Build OpenForge Linux packages")
    parser.add_argument("--appimage", action="store_true")
    parser.add_argument("--flatpak", action="store_true")
    parser.add_argument("--snap", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--tarball", action="store_true", help="Build .tar.gz fallback")
    parser.add_argument("--check", action="store_true", help="Only validate prerequisites")
    args = parser.parse_args()

    if args.check:
        print(f"OpenForge version: {APP_VERSION}")
        print(f"appimagetool: {shutil.which('appimagetool') or 'not found'}")
        print(f"flatpak-builder: {shutil.which('flatpak-builder') or 'not found'}")
        print(f"snapcraft: {shutil.which('snapcraft') or 'not found'}")
        return 0

    if not any([args.appimage, args.flatpak, args.snap, args.all, args.tarball]):
        args.appimage = True

    app_dir = run_pyinstaller()
    artifact: Path | None = None
    if args.all or args.appimage:
        artifact = build_appimage(app_dir)
    if args.tarball:
        artifact = build_tarball(app_dir)
    if args.all or args.flatpak:
        build_flatpak()
    if args.all or args.snap:
        build_snap()
    if artifact is not None and not artifact.exists():
        raise SystemExit(f"expected artifact missing: {artifact}")
    print(f"[done] Linux build complete -> {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
