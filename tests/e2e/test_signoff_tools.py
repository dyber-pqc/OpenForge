"""End-to-end test for the OpenForge native sign-off tools (Rust).

Runs all three (DRC, LVS, xRC) against the bundled examples/asic-counter-sky130
artifacts. Skips gracefully if a tool binary is missing or the artifact is
absent (e.g. counter hasn't been built locally yet). The point is to catch
regressions that break the tools on real-world data, not to require every dev
to have OpenROAD + WSL set up before they can run pytest.

Run with:  pytest tests/e2e/test_signoff_tools.py -v
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
COUNTER = REPO / "examples" / "asic-counter-sky130"
BUILD = COUNTER / "build"


def _find_bin(name: str) -> Path | None:
    """Locate a Rust binary in target/release, target/debug, or PATH."""
    on_path = shutil.which(name)
    if on_path:
        return Path(on_path)
    for sub in ("target/release", "target/debug"):
        for ext in ("", ".exe"):
            cand = REPO / sub / f"{name}{ext}"
            if cand.exists():
                return cand
    return None


@pytest.fixture(scope="module")
def drc_bin() -> Path:
    b = _find_bin("openforge-drc")
    if b is None:
        pytest.skip("openforge-drc binary not built")
    return b


@pytest.fixture(scope="module")
def lvs_bin() -> Path:
    b = _find_bin("openforge-lvs")
    if b is None:
        pytest.skip("openforge-lvs binary not built")
    return b


@pytest.fixture(scope="module")
def xrc_bin() -> Path:
    b = _find_bin("openforge-xrc")
    if b is None:
        pytest.skip("openforge-xrc binary not built")
    return b


# -----------------------------------------------------------------------------
# DRC
# -----------------------------------------------------------------------------


def test_drc_help(drc_bin: Path) -> None:
    """DRC binary responds to --help with exit 0."""
    r = subprocess.run([str(drc_bin), "--help"], capture_output=True, timeout=10)
    assert r.returncode == 0


def test_drc_on_counter_gds(drc_bin: Path, tmp_path: Path) -> None:
    """DRC runs cleanly on the bundled counter GDS (or skips if not built)."""
    gds = BUILD / "gds_export" / "counter.gds"
    if not gds.exists():
        pytest.skip(f"counter GDS not yet built at {gds}")
    rules = REPO / "tools" / "openforge-drc" / "tests" / "fixtures" / "simple.drc"
    out = tmp_path / "counter.rdb"

    r = subprocess.run(
        [
            str(drc_bin), "check", str(gds),
            "--rules", str(rules), "--tech", "sky130A",
            "--output", str(out), "--format", "text",
        ],
        capture_output=True, text=True, timeout=120,
    )
    # Exit code 0 = no violations, 2 = violations found, both are valid runs
    assert r.returncode in (0, 2), (
        f"DRC binary failed unexpectedly (exit {r.returncode}):\n{r.stderr}"
    )
    assert out.exists(), "DRC report not written"
    assert out.stat().st_size > 0, "DRC report is empty"
    assert "violation" in r.stdout.lower() or "violations" in r.stdout.lower()


# -----------------------------------------------------------------------------
# LVS
# -----------------------------------------------------------------------------


def test_lvs_help(lvs_bin: Path) -> None:
    r = subprocess.run([str(lvs_bin), "--help"], capture_output=True, timeout=10)
    assert r.returncode == 0


def test_lvs_inverter_match(lvs_bin: Path, tmp_path: Path) -> None:
    """Bundled inverter test fixtures must MATCH."""
    fix = REPO / "tools" / "openforge-lvs" / "tests" / "fixtures"
    if not (fix / "inv_lay.spice").exists():
        pytest.skip("LVS fixtures missing")
    r = subprocess.run(
        [
            str(lvs_bin), "check",
            "--layout", str(fix / "inv_lay.spice"),
            "--schematic", str(fix / "inv_sch.spice"),
            "--top", "inverter",
        ],
        capture_output=True, text=True, timeout=30, cwd=tmp_path,
    )
    assert r.returncode == 0, f"Expected MATCH (exit 0), got {r.returncode}:\n{r.stdout}\n{r.stderr}"
    assert "MATCH" in r.stdout


def test_lvs_inverter_mismatch(lvs_bin: Path, tmp_path: Path) -> None:
    """The 'bad' inverter must be detected as a MISMATCH."""
    fix = REPO / "tools" / "openforge-lvs" / "tests" / "fixtures"
    if not (fix / "inv_bad.spice").exists():
        pytest.skip("LVS fixtures missing")
    r = subprocess.run(
        [
            str(lvs_bin), "check",
            "--layout", str(fix / "inv_bad.spice"),
            "--schematic", str(fix / "inv_sch.spice"),
            "--top", "inverter",
        ],
        capture_output=True, text=True, timeout=30, cwd=tmp_path,
    )
    assert r.returncode == 1, f"Expected MISMATCH (exit 1), got {r.returncode}:\n{r.stdout}\n{r.stderr}"
    assert "MISMATCH" in r.stdout


# -----------------------------------------------------------------------------
# xRC
# -----------------------------------------------------------------------------


def test_xrc_help(xrc_bin: Path) -> None:
    r = subprocess.run([str(xrc_bin), "--help"], capture_output=True, timeout=10)
    assert r.returncode == 0


def test_xrc_on_routed_def(xrc_bin: Path, tmp_path: Path) -> None:
    """xRC runs on the bundled counter routed.def and produces a SPEF."""
    routed = BUILD / "routing" / "routed.def"
    if not routed.exists():
        pytest.skip(f"routed.def not yet built at {routed}")
    lef = REPO / "tools" / "openforge-xrc" / "tests" / "fixtures" / "tiny.lef"
    out = tmp_path / "counter.spef"

    r = subprocess.run(
        [
            str(xrc_bin), "extract",
            "--def", str(routed),
            "--lef", str(lef),
            "--tech", "sky130A",
            "--output", str(out),
        ],
        capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, f"xRC failed:\n{r.stderr}\n{r.stdout}"
    assert out.exists(), "SPEF not written"
    text = out.read_text()
    assert "*SPEF" in text, "Output is not a valid SPEF file"
    assert "*D_NET" in text, "SPEF has no nets"


# -----------------------------------------------------------------------------
# Cross-tool sanity
# -----------------------------------------------------------------------------


def test_all_three_binaries_present() -> None:
    """Sanity check: at least one of the three binaries must be findable.
    If none are, the user hasn't run cargo build yet."""
    found = [b for b in ("openforge-drc", "openforge-lvs", "openforge-xrc") if _find_bin(b)]
    if not found:
        pytest.skip(
            "No Rust sign-off binaries found. Build with:\n"
            "  cargo build --release -p openforge-drc -p openforge-lvs -p openforge-xrc"
        )
    print(f"\nFound {len(found)}/3 sign-off binaries: {', '.join(found)}")
