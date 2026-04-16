"""Project template factories.

Each factory returns a fully-populated :class:`Project` suitable for
``project.save('openforge.yaml')``.
"""

from __future__ import annotations

from .model import (
    Constraint,
    ConstraintKind,
    CornerSet,
    PDKRef,
    Project,
    ProjectKind,
    RunConfig,
    Target,
    TargetKind,
)


def _default_clock(period_ns: float = 10.0, port: str = "clk") -> Constraint:
    return Constraint(
        kind=ConstraintKind.CLOCK,
        name="clk",
        value={"period": period_ns, "port": port},
        paths=[port],
    )


def sky130_asic_template(name: str) -> Project:
    """Sky130 ASIC project with TT/SS/FF corners."""
    return Project(
        name=name,
        kind=ProjectKind.ASIC,
        top_module=name,
        rtl_sources=[f"rtl/{name}.v"],
        constraint_files=[f"constraints/{name}.sdc"],
        pdk=PDKRef(name="sky130A", variant="sky130_fd_sc_hd"),
        target=Target(kind=TargetKind.ASIC, vendor="skywater", family="sky130"),
        corners=[
            CornerSet(
                name="tt_025C_1v80",
                process="tt",
                voltage=1.80,
                temperature=25.0,
                lib_files=["sky130_fd_sc_hd__tt_025C_1v80.lib"],
            ),
            CornerSet(
                name="ss_n40C_1v60",
                process="ss",
                voltage=1.60,
                temperature=-40.0,
                lib_files=["sky130_fd_sc_hd__ss_n40C_1v60.lib"],
            ),
            CornerSet(
                name="ff_125C_1v95",
                process="ff",
                voltage=1.95,
                temperature=125.0,
                lib_files=["sky130_fd_sc_hd__ff_125C_1v95.lib"],
            ),
        ],
        constraints=[_default_clock(10.0)],
        runs=[
            RunConfig(stage="lint", tool="verible"),
            RunConfig(stage="sim", tool="verilator", depends_on=["lint"]),
            RunConfig(
                stage="synth",
                tool="yosys",
                options={"target": "sky130"},
                depends_on=["lint"],
            ),
            RunConfig(stage="floorplan", tool="openroad", depends_on=["synth"]),
            RunConfig(stage="placement", tool="openroad", depends_on=["floorplan"]),
            RunConfig(stage="cts", tool="openroad", depends_on=["placement"]),
            RunConfig(stage="routing", tool="openroad", depends_on=["cts"]),
            RunConfig(stage="sta", tool="opensta", depends_on=["routing"]),
            RunConfig(stage="drc", tool="magic", depends_on=["routing"]),
            RunConfig(stage="lvs", tool="netgen", depends_on=["routing"]),
            RunConfig(stage="gds", tool="magic", depends_on=["routing"]),
        ],
    )


def _fpga_template(
    name: str,
    *,
    vendor: str,
    family: str,
    device: str,
    package: str,
    board: str,
    constraint_ext: str,
    pack_tool: str,
    programmer: str,
) -> Project:
    return Project(
        name=name,
        kind=ProjectKind.FPGA,
        top_module=name,
        rtl_sources=[f"rtl/{name}.v"],
        constraint_files=[f"constraints/{board}.{constraint_ext}"],
        target=Target(
            kind=TargetKind.FPGA,
            vendor=vendor,
            family=family,
            device=device,
            package=package,
            board=board,
        ),
        constraints=[_default_clock(period_ns=83.3)],
        runs=[
            RunConfig(stage="lint", tool="verible"),
            RunConfig(stage="sim", tool="verilator", depends_on=["lint"]),
            RunConfig(
                stage="synth",
                tool="yosys",
                options={"target": family},
                depends_on=["lint"],
            ),
            RunConfig(
                stage="pnr",
                tool="nextpnr",
                options={"target": family, "device": device, "package": package},
                depends_on=["synth"],
            ),
            RunConfig(stage="bitstream", tool=pack_tool, depends_on=["pnr"]),
            RunConfig(
                stage="program",
                tool="openFPGALoader",
                options={"programmer": programmer},
                depends_on=["bitstream"],
            ),
        ],
    )


def ice40_fpga_template(name: str, board: str = "icebreaker") -> Project:
    """Lattice iCE40 FPGA project (default: iCEBreaker UP5K SG48)."""
    return _fpga_template(
        name,
        vendor="lattice",
        family="ice40",
        device="up5k",
        package="sg48",
        board=board,
        constraint_ext="pcf",
        pack_tool="icepack",
        programmer="icebreaker",
    )


def ecp5_fpga_template(name: str, board: str = "ulx3s") -> Project:
    """Lattice ECP5 FPGA project (default: ULX3S 25F CABGA381)."""
    return _fpga_template(
        name,
        vendor="lattice",
        family="ecp5",
        device="25k",
        package="CABGA381",
        board=board,
        constraint_ext="lpf",
        pack_tool="ecppack",
        programmer="ulx3s",
    )


def gowin_fpga_template(name: str, board: str = "tang_nano_9k") -> Project:
    """Gowin FPGA project (default: Tang Nano 9K - GW1NR-9 QFN88)."""
    return _fpga_template(
        name,
        vendor="gowin",
        family="gowin",
        device="GW1NR-LV9QN88PC6/I5",
        package="QFN88",
        board=board,
        constraint_ext="cst",
        pack_tool="gowin_pack",
        programmer="tangnano9k",
    )


def caravel_template(name: str) -> Project:
    """Sky130 MPW Caravel user_project wrapper."""
    proj = sky130_asic_template(name)
    proj.top_module = "user_project_wrapper"
    proj.rtl_sources = [
        f"rtl/{name}.v",
        "rtl/user_project_wrapper.v",
    ]
    proj.metadata["caravel"] = True
    proj.metadata["mpw"] = True
    return proj


def pcb_template(name: str) -> Project:
    """KiCad-style PCB project."""
    return Project(
        name=name,
        kind=ProjectKind.PCB,
        top_module="",
        schematic_file=f"{name}.kicad_sch",
        pcb_file=f"{name}.kicad_pcb",
        runs=[
            RunConfig(stage="erc", tool="kicad-cli"),
            RunConfig(stage="drc", tool="kicad-cli", depends_on=["erc"]),
            RunConfig(stage="gerber", tool="kicad-cli", depends_on=["drc"]),
            RunConfig(stage="drill", tool="kicad-cli", depends_on=["drc"]),
            RunConfig(stage="pick_place", tool="kicad-cli", depends_on=["drc"]),
        ],
    )


def mixed_template(name: str) -> Project:
    """Mixed FPGA + PCB project."""
    fpga = ice40_fpga_template(name)
    fpga.kind = ProjectKind.MIXED
    fpga.schematic_file = f"{name}.kicad_sch"
    fpga.pcb_file = f"{name}.kicad_pcb"
    fpga.runs.extend(
        [
            RunConfig(stage="pcb_erc", tool="kicad-cli"),
            RunConfig(stage="pcb_drc", tool="kicad-cli", depends_on=["pcb_erc"]),
            RunConfig(stage="gerber", tool="kicad-cli", depends_on=["pcb_drc"]),
        ]
    )
    return fpga


__all__ = [
    "sky130_asic_template",
    "ice40_fpga_template",
    "ecp5_fpga_template",
    "gowin_fpga_template",
    "caravel_template",
    "pcb_template",
    "mixed_template",
]
