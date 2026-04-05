"""Tests for the PDK manager."""

from __future__ import annotations

import tempfile
from pathlib import Path

from openforge.pdk.manager import KNOWN_PDKS, PDKManager, PDKStatus


def test_known_pdks_exist() -> None:
    assert "sky130" in KNOWN_PDKS
    assert "gf180mcu" in KNOWN_PDKS
    assert "asap7" in KNOWN_PDKS


def test_pdk_info_fields() -> None:
    sky130 = KNOWN_PDKS["sky130"]
    assert sky130.display_name == "SkyWater SKY130"
    assert sky130.node == "130nm"
    assert sky130.metal_layers == 5
    assert "Digital" in sky130.features


def test_manager_lists_pdks() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = PDKManager(pdk_root=Path(tmpdir))
        pdks = mgr.list_pdks()
        names = {p.name for p in pdks}
        assert "sky130" in names
        assert "gf180mcu" in names


def test_manager_none_installed_by_default() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = PDKManager(pdk_root=Path(tmpdir))
        assert not mgr.is_installed("sky130")


def test_manager_detects_installed_pdk() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        pdk_root = Path(tmpdir)
        (pdk_root / "sky130").mkdir()

        mgr = PDKManager(pdk_root=pdk_root)
        assert mgr.is_installed("sky130")


def test_get_nonexistent_pdk() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = PDKManager(pdk_root=Path(tmpdir))
        assert mgr.get_pdk("nonexistent") is None
