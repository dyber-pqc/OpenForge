"""Tests for the v2 project model and templates."""

from __future__ import annotations

from pathlib import Path

import pytest

from openforge.project.model import (
    Constraint,
    ConstraintKind,
    Project,
    ProjectKind,
)
from openforge.project.templates import (
    caravel_template,
    ecp5_fpga_template,
    gowin_fpga_template,
    ice40_fpga_template,
    mixed_template,
    pcb_template,
    sky130_asic_template,
)


def test_sky130_template_has_three_corners() -> None:
    p = sky130_asic_template("foo")
    assert p.kind == ProjectKind.ASIC
    assert len(p.corners) == 3
    names = {c.name for c in p.corners}
    assert names == {"tt_025C_1v80", "ss_n40C_1v60", "ff_125C_1v95"}
    assert p.validate_consistency() == []


@pytest.mark.parametrize(
    "factory",
    [ice40_fpga_template, ecp5_fpga_template, gowin_fpga_template],
)
def test_fpga_templates(factory) -> None:  # type: ignore[no-untyped-def]
    p = factory("myfpga")
    assert p.kind == ProjectKind.FPGA
    assert p.target is not None
    assert p.validate_consistency() == []
    # run graph has synth -> pnr -> bitstream -> program
    stages = {r.stage for r in p.runs}
    assert {"synth", "pnr", "bitstream", "program"} <= stages


def test_caravel_and_pcb_and_mixed() -> None:
    c = caravel_template("usr")
    assert c.metadata.get("caravel") is True
    assert c.top_module == "user_project_wrapper"

    pcb = pcb_template("board")
    assert pcb.kind == ProjectKind.PCB
    assert pcb.validate_consistency() == []

    m = mixed_template("combo")
    assert m.kind == ProjectKind.MIXED
    assert m.pcb_file is not None


def test_yaml_round_trip(tmp_path: Path) -> None:
    p = sky130_asic_template("bar")
    p.constraints.append(
        Constraint(kind=ConstraintKind.FALSE_PATH, paths=["a", "b"])
    )
    out = tmp_path / "openforge.yaml"
    p.save(out)
    loaded = Project.load(out)
    assert loaded.name == "bar"
    assert loaded.kind == ProjectKind.ASIC
    assert len(loaded.corners) == 3
    assert any(c.kind == ConstraintKind.FALSE_PATH for c in loaded.constraints)
    assert loaded.model_dump() == p.model_dump()


def test_validate_consistency_catches_bad_dep() -> None:
    from openforge.project.model import RunConfig

    p = sky130_asic_template("x")
    p.runs.append(RunConfig(stage="zzz", tool="nop", depends_on=["nope"]))
    issues = p.validate_consistency()
    assert any("nope" in i for i in issues)


def test_duplicate_stage_rejected() -> None:
    from openforge.project.model import RunConfig

    with pytest.raises(Exception):
        Project(
            name="x",
            kind=ProjectKind.ASIC,
            top_module="x",
            runs=[
                RunConfig(stage="a", tool="t1"),
                RunConfig(stage="a", tool="t2"),
            ],
        )
