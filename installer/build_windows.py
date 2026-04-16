"""Build the Windows installer for OpenForge EDA.

Usage:
    python installer/build_windows.py [--nsis | --msix | --zip]
    python installer/build_windows.py --check

Requires:
    - PyInstaller (always)
    - NSIS (for --nsis): https://nsis.sourceforge.io/
    - WiX or makeappx (for --msix)

The script:
  1. Downloads bundled EDA tools (Yosys, nextpnr-ice40, icepack, openFPGALoader)
  2. Runs PyInstaller against ``installer/openforge.spec``
  3. Generates and executes an NSIS script (or builds MSIX/ZIP)

The NSIS installer creates:
  - Start Menu shortcuts
  - Desktop shortcut
  - Uninstaller entry in Add/Remove Programs
  - File associations for .v, .sv, .yaml
  - PATH entry for the openforge CLI
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import textwrap
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DIST = ROOT / "dist"
TOOLS_DIR = DIST / "eda_tools"
APP_NAME = "OpenForge EDA"
APP_PUBLISHER = "OpenForge Contributors"

# ---------------------------------------------------------------------------
# EDA tool download URLs (YosysHQ GitHub releases, Windows x64)
# ---------------------------------------------------------------------------
EDA_TOOL_URLS = {
    "yosys": {
        "url": "https://github.com/YosysHQ/oss-cad-suite-build/releases/latest/download/oss-cad-suite-windows-x64-latest.zip",
        "extract_prefix": "oss-cad-suite",
        "description": "Yosys, nextpnr-ice40/ecp5, icepack, iceprog, and more",
    },
    "openfpgaloader": {
        "url": "https://github.com/trabucayre/openFPGALoader/releases/latest/download/openFPGALoader-win64.zip",
        "extract_prefix": "",
        "description": "openFPGALoader FPGA programmer",
    },
}


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
        raise SystemExit(f"command failed with exit code {rc}: {' '.join(cmd)}")


def _download(url: str, dest: Path) -> None:
    """Download a file with progress indication."""
    print(f"[download] {url}")
    print(f"       --> {dest}")
    if dest.exists():
        print(f"[download] already exists, skipping")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, str(dest))
    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"[download] {size_mb:.1f} MiB")


def download_eda_tools() -> Path:
    """Download and extract bundled EDA tools for Windows."""
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)

    for name, info in EDA_TOOL_URLS.items():
        url = info["url"]
        archive_name = url.rsplit("/", 1)[-1]
        archive_path = TOOLS_DIR / archive_name
        extract_dir = TOOLS_DIR / name

        if extract_dir.exists() and any(extract_dir.iterdir()):
            print(f"[eda] {name}: already extracted at {extract_dir}")
            continue

        _download(url, archive_path)

        print(f"[eda] extracting {archive_name} ...")
        extract_dir.mkdir(parents=True, exist_ok=True)

        if archive_name.endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(extract_dir)
        else:
            # tar.gz / tar.bz2
            import tarfile
            with tarfile.open(archive_path) as tf:
                tf.extractall(extract_dir)

        # Clean up archive to save space
        archive_path.unlink(missing_ok=True)
        print(f"[eda] {name}: extracted to {extract_dir}")

    return TOOLS_DIR


def run_pyinstaller() -> Path:
    spec = HERE / "openforge.spec"
    if not spec.exists():
        raise SystemExit(f"Missing PyInstaller spec: {spec}")
    if DIST.exists():
        # Preserve eda_tools if already downloaded
        eda_backup = None
        if TOOLS_DIR.exists():
            eda_backup = DIST.parent / "_eda_tools_backup"
            if eda_backup.exists():
                shutil.rmtree(eda_backup)
            shutil.move(str(TOOLS_DIR), str(eda_backup))
        shutil.rmtree(DIST, ignore_errors=True)
        if eda_backup and eda_backup.exists():
            DIST.mkdir(parents=True, exist_ok=True)
            shutil.move(str(eda_backup), str(TOOLS_DIR))
    run([sys.executable, "-m", "PyInstaller", "--clean", "-y", str(spec)], cwd=ROOT)
    out = DIST / "openforge"
    if not out.exists():
        raise SystemExit(f"PyInstaller did not produce {out}")
    return out


def bundle_eda_tools(app_dir: Path) -> None:
    """Copy downloaded EDA tools into the PyInstaller bundle."""
    if not TOOLS_DIR.exists():
        print("[bundle] no EDA tools directory found, skipping")
        return

    tools_dest = app_dir / "eda_tools"
    if tools_dest.exists():
        shutil.rmtree(tools_dest)

    print(f"[bundle] copying EDA tools into {tools_dest}")
    shutil.copytree(TOOLS_DIR, tools_dest)

    # Create a batch script that adds tools to PATH
    bat = app_dir / "setup_eda_path.bat"
    bat.write_text(textwrap.dedent(f"""\
        @echo off
        REM Add bundled EDA tools to PATH for this session
        set "OPENFORGE_HOME=%~dp0"
        set "PATH=%OPENFORGE_HOME%eda_tools\\yosys\\oss-cad-suite\\bin;%PATH%"
        set "PATH=%OPENFORGE_HOME%eda_tools\\openfpgaloader;%PATH%"
        echo OpenForge EDA tools added to PATH.
    """), encoding="utf-8")
    print(f"[bundle] wrote {bat}")


def write_nsis_script(app_dir: Path) -> Path:
    script_path = HERE / "openforge.nsi"
    icon_path = HERE / "openforge.ico"
    icon_line = f'  Icon "{icon_path}"' if icon_path.exists() else ""

    # Check if EDA tools are bundled
    has_eda_tools = (app_dir / "eda_tools").exists()
    eda_path_section = ""
    if has_eda_tools:
        eda_path_section = textwrap.dedent("""
            ; Add bundled EDA tools to system PATH
            EnVar::SetHKLM
            EnVar::AddValue "PATH" "$INSTDIR\\eda_tools\\yosys\\oss-cad-suite\\bin"
            EnVar::AddValue "PATH" "$INSTDIR\\eda_tools\\openfpgaloader"
        """).strip()

    eda_uninstall_section = ""
    if has_eda_tools:
        eda_uninstall_section = textwrap.dedent("""
            EnVar::SetHKLM
            EnVar::DeleteValue "PATH" "$INSTDIR\\eda_tools\\yosys\\oss-cad-suite\\bin"
            EnVar::DeleteValue "PATH" "$INSTDIR\\eda_tools\\openfpgaloader"
        """).strip()

    script = textwrap.dedent(
        f"""
        ; OpenForge EDA NSIS installer (auto-generated by build_windows.py)
        !include "EnvVarUpdate.nsh"

        !define APP_NAME "{APP_NAME}"
        !define APP_VERSION "{APP_VERSION}"
        !define APP_PUBLISHER "{APP_PUBLISHER}"
        !define APP_EXE "openforge.exe"
        !define APP_REGKEY "Software\\OpenForge"
        !define UNINSTALL_REGKEY "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\OpenForge"

        Name "${{APP_NAME}} ${{APP_VERSION}}"
        OutFile "OpenForge-Setup-{APP_VERSION}-win64.exe"
        InstallDir "$PROGRAMFILES64\\OpenForge EDA"
        InstallDirRegKey HKLM "${{APP_REGKEY}}" "InstallDir"
        RequestExecutionLevel admin
        SetCompressor /SOLID lzma
        {icon_line}

        ; Pages
        Page directory
        Page components
        Page instfiles
        UninstPage uninstConfirm
        UninstPage instfiles

        ; ---------------------------------------------------------------
        ; Main install section
        ; ---------------------------------------------------------------
        Section "OpenForge EDA (required)" SecMain
            SectionIn RO
            SetOutPath "$INSTDIR"
            File /r "{app_dir.as_posix()}\\*.*"

            ; --- Start Menu shortcuts ---
            CreateDirectory "$SMPROGRAMS\\OpenForge EDA"
            CreateShortcut "$SMPROGRAMS\\OpenForge EDA\\OpenForge EDA.lnk" "$INSTDIR\\${{APP_EXE}}" \
                "" "$INSTDIR\\${{APP_EXE}}" 0
            CreateShortcut "$SMPROGRAMS\\OpenForge EDA\\OpenForge CLI.lnk" "$INSTDIR\\openforge.exe" \
                "--help" "" 0 SW_SHOWMINIMIZED "" "OpenForge CLI"
            CreateShortcut "$SMPROGRAMS\\OpenForge EDA\\Uninstall.lnk" "$INSTDIR\\Uninstall.exe"

            ; --- Desktop shortcut ---
            CreateShortcut "$DESKTOP\\OpenForge EDA.lnk" "$INSTDIR\\${{APP_EXE}}"

            ; --- File associations ---
            ; Verilog files
            WriteRegStr HKCR ".v" "" "OpenForge.Verilog"
            WriteRegStr HKCR "OpenForge.Verilog" "" "Verilog Source File"
            WriteRegStr HKCR "OpenForge.Verilog\\DefaultIcon" "" "$INSTDIR\\${{APP_EXE}},0"
            WriteRegStr HKCR "OpenForge.Verilog\\shell\\open\\command" "" '"$INSTDIR\\${{APP_EXE}}" "%1"'

            ; SystemVerilog files
            WriteRegStr HKCR ".sv" "" "OpenForge.SystemVerilog"
            WriteRegStr HKCR "OpenForge.SystemVerilog" "" "SystemVerilog Source File"
            WriteRegStr HKCR "OpenForge.SystemVerilog\\DefaultIcon" "" "$INSTDIR\\${{APP_EXE}},0"
            WriteRegStr HKCR "OpenForge.SystemVerilog\\shell\\open\\command" "" '"$INSTDIR\\${{APP_EXE}}" "%1"'

            ; YAML config files (OpenForge projects)
            WriteRegStr HKCR ".ofpr" "" "OpenForge.Project"
            WriteRegStr HKCR "OpenForge.Project" "" "OpenForge Project"
            WriteRegStr HKCR "OpenForge.Project\\DefaultIcon" "" "$INSTDIR\\${{APP_EXE}},0"
            WriteRegStr HKCR "OpenForge.Project\\shell\\open\\command" "" '"$INSTDIR\\${{APP_EXE}}" "%1"'

            ; Associate openforge.yaml with Open in OpenForge context menu
            WriteRegStr HKCR "SystemFileAssociations\\.yaml\\shell\\OpenForge" "" "Open in OpenForge EDA"
            WriteRegStr HKCR "SystemFileAssociations\\.yaml\\shell\\OpenForge\\command" "" '"$INSTDIR\\${{APP_EXE}}" "%1"'

            ; --- PATH ---
            EnVar::SetHKCU
            EnVar::AddValue "PATH" "$INSTDIR"
            {eda_path_section}

            ; --- Add/Remove Programs entry ---
            WriteRegStr HKLM "${{UNINSTALL_REGKEY}}" "DisplayName" "${{APP_NAME}}"
            WriteRegStr HKLM "${{UNINSTALL_REGKEY}}" "DisplayVersion" "${{APP_VERSION}}"
            WriteRegStr HKLM "${{UNINSTALL_REGKEY}}" "Publisher" "${{APP_PUBLISHER}}"
            WriteRegStr HKLM "${{UNINSTALL_REGKEY}}" "InstallLocation" "$INSTDIR"
            WriteRegStr HKLM "${{UNINSTALL_REGKEY}}" "UninstallString" '"$INSTDIR\\Uninstall.exe"'
            WriteRegStr HKLM "${{UNINSTALL_REGKEY}}" "DisplayIcon" "$INSTDIR\\${{APP_EXE}}"
            WriteRegDWORD HKLM "${{UNINSTALL_REGKEY}}" "NoModify" 1
            WriteRegDWORD HKLM "${{UNINSTALL_REGKEY}}" "NoRepair" 1
            WriteRegStr HKLM "${{APP_REGKEY}}" "InstallDir" "$INSTDIR"
            WriteUninstaller "$INSTDIR\\Uninstall.exe"

            ; Refresh shell for file associations
            System::Call 'Shell32::SHChangeNotify(i 0x8000000, i 0, p 0, p 0)'
        SectionEnd

        ; ---------------------------------------------------------------
        ; Uninstaller
        ; ---------------------------------------------------------------
        Section "Uninstall"
            ; Remove PATH entries
            EnVar::SetHKCU
            EnVar::DeleteValue "PATH" "$INSTDIR"
            {eda_uninstall_section}

            ; Remove shortcuts
            Delete "$DESKTOP\\OpenForge EDA.lnk"
            RMDir /r "$SMPROGRAMS\\OpenForge EDA"

            ; Remove file associations
            DeleteRegKey HKCR ".v"
            DeleteRegKey HKCR "OpenForge.Verilog"
            DeleteRegKey HKCR ".sv"
            DeleteRegKey HKCR "OpenForge.SystemVerilog"
            DeleteRegKey HKCR ".ofpr"
            DeleteRegKey HKCR "OpenForge.Project"
            DeleteRegKey HKCR "SystemFileAssociations\\.yaml\\shell\\OpenForge"

            ; Remove registry
            DeleteRegKey HKLM "${{UNINSTALL_REGKEY}}"
            DeleteRegKey HKLM "${{APP_REGKEY}}"

            ; Remove install directory
            RMDir /r "$INSTDIR"

            ; Refresh shell
            System::Call 'Shell32::SHChangeNotify(i 0x8000000, i 0, p 0, p 0)'
        SectionEnd
        """
    ).strip()
    script_path.write_text(script, encoding="utf-8")
    print(f"[nsis] wrote {script_path}")
    return script_path


def build_nsis(app_dir: Path) -> None:
    script = write_nsis_script(app_dir)
    makensis = shutil.which("makensis")
    if makensis is None:
        raise SystemExit(
            "makensis not found on PATH; install NSIS from https://nsis.sourceforge.io/"
        )
    run([makensis, str(script)], cwd=HERE)


def build_portable_zip(app_dir: Path) -> Path:
    """Fallback: zip the PyInstaller bundle as a portable distribution."""
    out = DIST / f"OpenForge-{APP_VERSION}-win64.zip"
    if out.exists():
        out.unlink()
    print(f"[zip] writing {out}")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in app_dir.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(app_dir.parent))
    print(f"[zip] wrote {out} ({out.stat().st_size // (1024 * 1024)} MiB)")
    return out


def write_wsl_detect_script(app_dir: Path) -> None:
    """Drop a helper that checks for WSL2 on first run."""
    script = app_dir / "wsl_detect.ps1"
    script.write_text(
        textwrap.dedent(
            """
            # OpenForge WSL2 detection helper
            $wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
            if (-not $wsl) {
                Write-Host "WSL2 is not installed. OpenForge can install it for you."
                Write-Host "Run: wsl --install -d Ubuntu-24.04"
                exit 2
            }
            $version = & wsl.exe --status 2>&1
            if ($LASTEXITCODE -ne 0) { exit 3 }
            Write-Host "WSL2 detected:"
            Write-Host $version
            exit 0
            """
        ).strip() + "\n",
        encoding="utf-8",
    )
    print(f"[wsl] wrote {script}")


def build_msix(app_dir: Path) -> None:
    makeappx = shutil.which("makeappx")
    if makeappx is None:
        raise SystemExit(
            "makeappx not found; install the Windows 10/11 SDK to enable MSIX builds"
        )
    out = HERE / f"OpenForge-{APP_VERSION}.msix"
    run([makeappx, "pack", "/d", str(app_dir), "/p", str(out)], cwd=HERE)
    print(f"[msix] wrote {out}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the OpenForge Windows installer")
    parser.add_argument("--msix", action="store_true", help="Build an MSIX package instead of NSIS")
    parser.add_argument("--nsis", action="store_true", help="Build an NSIS installer (default)")
    parser.add_argument("--zip", action="store_true", help="Build a portable ZIP distribution")
    parser.add_argument("--check", action="store_true", help="Only validate prerequisites")
    parser.add_argument(
        "--skip-eda-tools", action="store_true",
        help="Skip downloading bundled EDA tools (Yosys, nextpnr, etc.)",
    )
    args = parser.parse_args()

    if args.check:
        print(f"OpenForge version: {APP_VERSION}")
        print(f"Python: {sys.version}")
        print(f"makensis: {shutil.which('makensis') or 'not found'}")
        print(f"makeappx: {shutil.which('makeappx') or 'not found'}")
        print(f"PyInstaller spec: {(HERE / 'openforge.spec').exists()}")
        print(f"EDA tools dir: {TOOLS_DIR.exists()}")
        for name in EDA_TOOL_URLS:
            tool_dir = TOOLS_DIR / name
            print(f"  {name}: {'present' if tool_dir.exists() else 'not downloaded'}")
        return 0

    # Step 1: Download EDA tools
    if not args.skip_eda_tools:
        print("=" * 60)
        print("Step 1: Downloading bundled EDA tools")
        print("=" * 60)
        download_eda_tools()
    else:
        print("[skip] EDA tool download skipped")

    # Step 2: Run PyInstaller
    print("=" * 60)
    print("Step 2: Running PyInstaller")
    print("=" * 60)
    app_dir = run_pyinstaller()
    write_wsl_detect_script(app_dir)

    # Step 3: Bundle EDA tools into the app directory
    print("=" * 60)
    print("Step 3: Bundling EDA tools")
    print("=" * 60)
    bundle_eda_tools(app_dir)

    # Step 4: Build installer
    print("=" * 60)
    print("Step 4: Building installer")
    print("=" * 60)
    artifact: Path | None = None
    if args.msix:
        build_msix(app_dir)
    elif args.zip or shutil.which("makensis") is None:
        if not args.zip:
            print("[warn] makensis not found; falling back to portable ZIP")
        artifact = build_portable_zip(app_dir)
    else:
        build_nsis(app_dir)
        # NSIS writes next to the .nsi script
        artifact = HERE / f"OpenForge-Setup-{APP_VERSION}-win64.exe"

    if artifact is not None and not artifact.exists():
        raise SystemExit(f"expected artifact missing: {artifact}")
    print("=" * 60)
    print(f"[done] Windows build complete -> {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
