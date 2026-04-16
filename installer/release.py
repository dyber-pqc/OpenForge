"""Automate a release: bump version, build all packages, create GitHub release.

Usage:
    python installer/release.py                    # patch bump + full release
    python installer/release.py --part minor       # minor bump
    python installer/release.py --part major       # major bump
    python installer/release.py --skip-docker      # skip docker build
    python installer/release.py --dry-run          # print what would happen
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# All pyproject.toml files that contain a version to bump
VERSION_FILES = [
    ROOT / "pyproject.toml",
    ROOT / "packages" / "core" / "pyproject.toml",
    ROOT / "packages" / "cli" / "pyproject.toml",
    ROOT / "packages" / "api" / "pyproject.toml",
    ROOT / "packages" / "desktop" / "pyproject.toml",
    ROOT / "packages" / "crypto" / "pyproject.toml",
]

VERSION_PATTERN = re.compile(r'^(version\s*=\s*")(\d+\.\d+\.\d+)(")', re.MULTILINE)


def _read_current_version() -> str:
    """Read version from the root pyproject.toml."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    return str(data["project"]["version"])


def _run(cmd: list[str], dry_run: bool = False, **kwargs) -> subprocess.CompletedProcess[str]:
    """Run a command, or print it if dry_run."""
    print(f"  $ {' '.join(cmd)}")
    if dry_run:
        return subprocess.CompletedProcess(cmd, 0, "", "")
    return subprocess.run(cmd, check=True, text=True, **kwargs)


def bump_version(part: str = "patch", dry_run: bool = False) -> str:
    """Bump version across all pyproject.toml files. Returns the new version."""
    current = _read_current_version()
    major, minor, patch = (int(x) for x in current.split("."))

    if part == "major":
        major += 1
        minor = 0
        patch = 0
    elif part == "minor":
        minor += 1
        patch = 0
    elif part == "patch":
        patch += 1
    else:
        raise ValueError(f"Invalid version part: {part!r}. Use major, minor, or patch.")

    new_version = f"{major}.{minor}.{patch}"
    print(f"[version] {current} -> {new_version} ({part} bump)")

    if dry_run:
        return new_version

    for vf in VERSION_FILES:
        if not vf.exists():
            print(f"  [skip] {vf.relative_to(ROOT)} (not found)")
            continue
        text = vf.read_text(encoding="utf-8")
        new_text, count = VERSION_PATTERN.subn(rf"\g<1>{new_version}\3", text)
        if count > 0:
            vf.write_text(new_text, encoding="utf-8")
            print(f"  [bump] {vf.relative_to(ROOT)}")
        else:
            print(f"  [skip] {vf.relative_to(ROOT)} (no version field matched)")

    return new_version


def build_pypi(dry_run: bool = False) -> None:
    """Build Python wheel and sdist via `python -m build`."""
    print("\n[pypi] Building Python packages ...")
    _run([sys.executable, "-m", "build", "--wheel", "--sdist"], dry_run=dry_run)


def build_docker(version: str, dry_run: bool = False) -> None:
    """Build and tag the Docker image."""
    print("\n[docker] Building Docker image ...")
    tag_latest = "openforge-eda:latest"
    tag_version = f"openforge-eda:{version}"
    _run(
        ["docker", "build", "-f", "installer/Dockerfile", "-t", tag_latest, "-t", tag_version, "."],
        dry_run=dry_run,
    )


def build_windows(dry_run: bool = False) -> None:
    """Build the Windows installer via build_windows.py."""
    print("\n[windows] Building Windows installer ...")
    _run([sys.executable, str(HERE / "build_windows.py")], dry_run=dry_run)


def create_github_release(tag: str, dry_run: bool = False) -> None:
    """Create a GitHub release using the gh CLI."""
    print(f"\n[github] Creating release {tag} ...")

    # Collect release assets
    dist = ROOT / "dist"
    assets: list[str] = []
    if dist.exists():
        for f in dist.iterdir():
            if f.suffix in (".whl", ".tar.gz", ".zip", ".exe", ".msi"):
                assets.append(str(f))

    cmd = [
        "gh", "release", "create", tag,
        "--title", f"OpenForge EDA {tag}",
        "--generate-notes",
    ]
    cmd.extend(assets)

    _run(cmd, dry_run=dry_run)


def release(
    part: str = "patch",
    skip_docker: bool = False,
    skip_windows: bool = False,
    dry_run: bool = False,
) -> None:
    """Orchestrate a full release."""
    print("=" * 60)
    print("OpenForge EDA Release")
    print("=" * 60)

    # 1. Bump version
    new_version = bump_version(part, dry_run=dry_run)
    tag = f"v{new_version}"

    # 2. Build PyPI packages
    build_pypi(dry_run=dry_run)

    # 3. Build Docker image
    if not skip_docker:
        build_docker(new_version, dry_run=dry_run)
    else:
        print("\n[docker] Skipped (--skip-docker)")

    # 4. Build Windows installer
    if not skip_windows and sys.platform == "win32":
        build_windows(dry_run=dry_run)
    elif skip_windows:
        print("\n[windows] Skipped (--skip-windows)")
    else:
        print("\n[windows] Skipped (not on Windows)")

    # 5. Git commit + tag
    print(f"\n[git] Committing version bump and tagging {tag} ...")
    _run(["git", "add", "-A"], dry_run=dry_run)
    _run(["git", "commit", "-m", f"release: {tag}"], dry_run=dry_run)
    _run(["git", "tag", "-a", tag, "-m", f"Release {tag}"], dry_run=dry_run)

    # 6. Push
    print(f"\n[git] Pushing {tag} ...")
    _run(["git", "push", "origin", "main", "--tags"], dry_run=dry_run)

    # 7. Create GitHub release
    create_github_release(tag, dry_run=dry_run)

    print("\n" + "=" * 60)
    print(f"[done] Released {tag}")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenForge EDA release automation")
    parser.add_argument(
        "--part", choices=["major", "minor", "patch"], default="patch",
        help="Version part to bump (default: patch)",
    )
    parser.add_argument("--skip-docker", action="store_true", help="Skip Docker build")
    parser.add_argument("--skip-windows", action="store_true", help="Skip Windows installer build")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")
    parser.add_argument(
        "--bump-only", action="store_true",
        help="Only bump version, don't build or release",
    )
    args = parser.parse_args()

    if args.bump_only:
        bump_version(args.part, dry_run=args.dry_run)
        return 0

    release(
        part=args.part,
        skip_docker=args.skip_docker,
        skip_windows=args.skip_windows,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
