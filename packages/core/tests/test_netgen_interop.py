"""Tests for the Netgen <-> OpenForge interop adapter."""

from __future__ import annotations

import json
from pathlib import Path

from openforge.integrations.netgen import (
    NetgenReport,
    netgen_to_lvs_options,
    parse_netgen_report,
    parse_netgen_setup,
    report_to_openforge_json,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "netgen_minimal"
SETUP = FIXTURE_DIR / "setup.tcl"
REPORT = FIXTURE_DIR / "lvs.report"


def test_parse_netgen_setup_extracts_directives() -> None:
    setup = parse_netgen_setup(SETUP)
    # 2 permute rules
    assert len(setup.permute) == 2
    nfet = next(p for p in setup.permute if "nfet" in p.cell)
    assert nfet.ports == ["1", "3"]
    # 2 equate-elements rules
    assert len(setup.equate_elements) == 2
    pairs = {(e.layout, e.schematic) for e in setup.equate_elements}
    assert ("sky130_fd_pr__nfet_01v8", "nfet_01v8") in pairs
    # 1 equate-classes rule
    assert len(setup.equate_classes) == 1
    # 1 ignore class
    assert len(setup.ignore_classes) == 1
    assert setup.ignore_classes[0].cell == "sky130_fd_pr__cap_var_lvt"
    # 2 property rules
    assert len(setup.properties) == 2
    tol = next(p for p in setup.properties if p.action == "tolerance")
    assert tol.value == 0.001
    ign = next(p for p in setup.properties if p.action == "ignore")
    assert ign.prop == "as"


def test_netgen_to_lvs_options_maps_correctly() -> None:
    setup = parse_netgen_setup(SETUP)
    opts = netgen_to_lvs_options(setup)
    assert len(opts["permute_ports"]) == 2
    # equate elements + equate classes both end up as device aliases
    assert len(opts["device_aliases"]) == 3
    assert opts["ignore_devices"] == ["sky130_fd_pr__cap_var_lvt"]
    assert len(opts["property_tolerances"]) == 1
    assert opts["property_tolerances"][0]["tolerance"] == 0.001
    assert len(opts["ignore_properties"]) == 1
    assert opts["ignore_properties"][0]["prop"] == "as"


def test_parse_netgen_report_match_verdict() -> None:
    report = parse_netgen_report(REPORT)
    assert isinstance(report, NetgenReport)
    assert report.overall_match is True
    assert "match uniquely" in report.verdict.lower()
    assert report.top_cell == "spm"
    # Two cell comparison blocks
    assert len(report.cells) == 2
    spm = next(c for c in report.cells if c.cell == "spm")
    assert spm.layout_devices == 1234
    assert spm.schematic_devices == 1234
    assert spm.layout_nets == 567
    inv = next(c for c in report.cells if "inv_2" in c.cell)
    assert inv.layout_devices == 2
    assert inv.schematic_devices == 2


def test_report_to_openforge_json_round_trip() -> None:
    report = parse_netgen_report(REPORT)
    payload = json.loads(report_to_openforge_json(report))
    assert payload["tool"] == "netgen"
    assert payload["match"] is True
    assert payload["top_cell"] == "spm"
    assert len(payload["cells"]) == 2
    assert payload["cells"][0]["layout_devices"] == 1234


def test_parse_netgen_report_mismatch_verdict(tmp_path: Path) -> None:
    """A report with a mismatch should flip overall_match=False."""
    bad = tmp_path / "lvs_bad.report"
    bad.write_text(
        "Top level cell: counter\n"
        "Subcircuit: counter\n"
        "Subcircuit summary:\n"
        "Number of devices: 10                |Number of devices: 12\n"
        "Number of nets: 20                   |Number of nets: 22\n"
        "Netlists do not match.\n",
        encoding="utf-8",
    )
    report = parse_netgen_report(bad)
    assert report.overall_match is False
    assert "do not match" in report.verdict.lower()
    assert report.cells[0].layout_devices == 10
    assert report.cells[0].schematic_devices == 12
