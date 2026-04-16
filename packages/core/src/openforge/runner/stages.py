"""Factory functions for standard OpenForge run stages.

Each returns a :class:`RunStage` with sensible defaults and proper
``depends_on`` wiring. Commands are placeholders wired to the canonical tool
CLIs (yosys, openroad, opensta, magic, netgen, verilator, verible, nextpnr,
icepack/ecppack/gowin_pack, openFPGALoader); callers are free to override
``command`` / ``options`` for custom invocations.
"""

from __future__ import annotations

from .engine import RunStage


# ----- RTL-level ----------------------------------------------------------


def lint_stage(rtl: list[str], *, stage_id: str = "lint") -> RunStage:
    """Verible RTL lint."""
    return RunStage(
        id=stage_id,
        name="Lint",
        tool="verible",
        command=["verible-verilog-lint", *rtl],
        produces=["*.rpt", "*.log"],
    )


def sim_stage(
    rtl: list[str],
    tb: list[str],
    *,
    sim: str = "verilator",
    top: str = "tb",
    stage_id: str = "sim",
    depends_on: list[str] | None = None,
) -> RunStage:
    """RTL simulation (default: Verilator)."""
    if sim == "verilator":
        cmd = [
            "verilator",
            "--binary",
            "-j",
            "0",
            "--trace",
            "--top-module",
            top,
            *rtl,
            *tb,
        ]
    elif sim == "icarus":
        cmd = ["iverilog", "-o", "sim.vvp", "-s", top, *rtl, *tb]
    else:
        cmd = [sim, *rtl, *tb]
    return RunStage(
        id=stage_id,
        name="Simulation",
        tool=sim,
        command=cmd,
        depends_on=depends_on or [],
        produces=["*.vcd", "*.fst", "sim.vvp"],
    )


# ----- Synthesis ----------------------------------------------------------


def synth_stage_yosys(
    rtl: list[str],
    top: str,
    *,
    target: str = "generic",
    stage_id: str = "synth",
    depends_on: list[str] | None = None,
) -> RunStage:
    """Yosys synthesis. ``target`` ∈ generic|sky130|ice40|ecp5|gowin."""
    script = []
    for f in rtl:
        script.append(f"read_verilog {f}")
    if target == "sky130":
        script.append(
            f"synth -top {top}; dfflibmap -liberty $LIB; abc -liberty $LIB; write_verilog -noattr netlist.v; write_json netlist.json"
        )
    elif target == "ice40":
        script.append(f"synth_ice40 -top {top} -json netlist.json")
    elif target == "ecp5":
        script.append(f"synth_ecp5 -top {top} -json netlist.json")
    elif target == "gowin":
        script.append(f"synth_gowin -top {top} -json netlist.json")
    else:
        script.append(f"synth -top {top}; write_verilog netlist.v; write_json netlist.json")
    yosys_cmd = "; ".join(script)
    return RunStage(
        id=stage_id,
        name=f"Synthesis ({target})",
        tool="yosys",
        command=["yosys", "-p", yosys_cmd],
        depends_on=depends_on or [],
        produces=["netlist.v", "netlist.json", "*.rpt"],
    )


# ----- ASIC physical (OpenROAD) ------------------------------------------


def _openroad_stage(
    sid: str, name: str, script: str, depends_on: list[str], produces: list[str]
) -> RunStage:
    return RunStage(
        id=sid,
        name=name,
        tool="openroad",
        command=["openroad", "-no_init", "-exit", script],
        depends_on=depends_on,
        produces=produces,
    )


def floorplan_stage(
    netlist: str,
    sdc: str,
    lef: list[str],
    lib: list[str],
    *,
    stage_id: str = "floorplan",
    depends_on: list[str] | None = None,
) -> RunStage:
    s = _openroad_stage(
        stage_id,
        "Floorplan",
        "floorplan.tcl",
        depends_on or [],
        ["*.def", "*.rpt", "*.log"],
    )
    s.env = {
        "NETLIST": netlist,
        "SDC": sdc,
        "LEF": ":".join(lef),
        "LIB": ":".join(lib),
    }
    return s


def placement_stage(
    *, stage_id: str = "placement", depends_on: list[str] | None = None
) -> RunStage:
    return _openroad_stage(
        stage_id,
        "Placement",
        "placement.tcl",
        depends_on or [],
        ["*.def", "*.rpt"],
    )


def cts_stage(
    *, stage_id: str = "cts", depends_on: list[str] | None = None
) -> RunStage:
    return _openroad_stage(
        stage_id, "CTS", "cts.tcl", depends_on or [], ["*.def", "*.rpt"]
    )


def routing_stage(
    *, stage_id: str = "routing", depends_on: list[str] | None = None
) -> RunStage:
    return _openroad_stage(
        stage_id,
        "Routing",
        "route.tcl",
        depends_on or [],
        ["*.def", "*.spef", "*.rpt"],
    )


def sta_stage(
    verilog: str,
    sdc: str,
    lib: list[str],
    *,
    spef: str | None = None,
    stage_id: str = "sta",
    depends_on: list[str] | None = None,
) -> RunStage:
    env = {"VERILOG": verilog, "SDC": sdc, "LIB": ":".join(lib)}
    if spef:
        env["SPEF"] = spef
    s = RunStage(
        id=stage_id,
        name="STA",
        tool="opensta",
        command=["sta", "-no_splash", "-exit", "sta.tcl"],
        depends_on=depends_on or [],
        produces=["*.rpt", "sta.log"],
    )
    s.env = env
    return s


def drc_stage_magic(
    gds: str,
    tech: str,
    *,
    stage_id: str = "drc",
    depends_on: list[str] | None = None,
) -> RunStage:
    return RunStage(
        id=stage_id,
        name="DRC (Magic)",
        tool="magic",
        command=[
            "magic",
            "-dnull",
            "-noconsole",
            "-T",
            tech,
            "-rcfile",
            "/dev/null",
            gds,
        ],
        depends_on=depends_on or [],
        produces=["*.rpt", "drc.log"],
    )


def lvs_stage_netgen(
    gds: str,
    netlist: str,
    *,
    stage_id: str = "lvs",
    depends_on: list[str] | None = None,
) -> RunStage:
    return RunStage(
        id=stage_id,
        name="LVS (Netgen)",
        tool="netgen",
        command=["netgen", "-batch", "lvs", gds, netlist],
        depends_on=depends_on or [],
        produces=["*.rpt", "comp.out"],
    )


def gds_export_stage(
    def_file: str,
    lef: list[str],
    mag: str,
    *,
    stage_id: str = "gds_export",
    depends_on: list[str] | None = None,
) -> RunStage:
    return RunStage(
        id=stage_id,
        name="GDS Export",
        tool="magic",
        command=["magic", "-dnull", "-noconsole", "-rcfile", mag, def_file],
        depends_on=depends_on or [],
        produces=["*.gds", "*.gds.gz"],
    )


# ----- FPGA ---------------------------------------------------------------


def nextpnr_stage(
    json_netlist: str,
    *,
    target: str,
    device: str,
    package: str,
    stage_id: str = "pnr",
    depends_on: list[str] | None = None,
) -> RunStage:
    if target == "ice40":
        cmd = [
            "nextpnr-ice40",
            f"--{device}",
            "--package",
            package,
            "--json",
            json_netlist,
            "--asc",
            "out.asc",
        ]
    elif target == "ecp5":
        cmd = [
            "nextpnr-ecp5",
            f"--{device}",
            "--package",
            package,
            "--json",
            json_netlist,
            "--textcfg",
            "out.config",
        ]
    else:
        cmd = ["nextpnr-generic", "--json", json_netlist]
    return RunStage(
        id=stage_id,
        name=f"nextpnr ({target})",
        tool="nextpnr",
        command=cmd,
        depends_on=depends_on or [],
        produces=["out.asc", "out.config", "*.rpt"],
    )


def bitstream_stage(
    asc: str,
    *,
    target: str,
    stage_id: str = "bitstream",
    depends_on: list[str] | None = None,
) -> RunStage:
    if target == "ice40":
        cmd = ["icepack", asc, "out.bin"]
        tool = "icepack"
        out = ["out.bin"]
    elif target == "ecp5":
        cmd = ["ecppack", asc, "out.bit"]
        tool = "ecppack"
        out = ["out.bit"]
    elif target == "gowin":
        cmd = ["gowin_pack", "-d", "GW1N-9", "-o", "out.fs", asc]
        tool = "gowin_pack"
        out = ["out.fs"]
    else:
        cmd = ["true"]
        tool = "none"
        out = []
    return RunStage(
        id=stage_id,
        name=f"Bitstream ({target})",
        tool=tool,
        command=cmd,
        depends_on=depends_on or [],
        produces=out,
    )


def program_stage(
    bit: str,
    *,
    programmer: str,
    stage_id: str = "program",
    depends_on: list[str] | None = None,
) -> RunStage:
    return RunStage(
        id=stage_id,
        name="Program",
        tool="openFPGALoader",
        command=["openFPGALoader", "-b", programmer, bit],
        depends_on=depends_on or [],
        cacheable=False,
    )


__all__ = [
    "lint_stage",
    "sim_stage",
    "synth_stage_yosys",
    "floorplan_stage",
    "placement_stage",
    "cts_stage",
    "routing_stage",
    "sta_stage",
    "drc_stage_magic",
    "lvs_stage_netgen",
    "gds_export_stage",
    "nextpnr_stage",
    "bitstream_stage",
    "program_stage",
]
