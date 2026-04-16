"""Yosys/ABC optimization passes and synthesis script generation."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from os import PathLike


class OptimizationPass(StrEnum):
    """Pre-defined optimization strategies for ABC technology mapping."""

    AREA = "area"
    SPEED = "speed"
    BALANCED = "balanced"
    LOW_POWER = "low_power"


# ---------------------------------------------------------------------------
# ABC recipe generation
# ---------------------------------------------------------------------------


def generate_abc_script(
    pass_type: OptimizationPass,
    target_delay: float | None = None,
    liberty_file: str | PathLike[str] | None = None,
) -> str:
    """Return an ABC optimization recipe string for the given strategy.

    Parameters
    ----------
    pass_type:
        Which optimization objective to target.
    target_delay:
        Target delay in picoseconds (used by SPEED pass for ``map -D``).
    liberty_file:
        Path to the Liberty file.  Currently unused inside the recipe
        itself (ABC receives it from the Yosys ``abc`` invocation), but
        kept for forward-compatibility with standalone ABC flows.

    Returns
    -------
    str
        A semicolon-separated ABC command sequence suitable for
        ``abc -script "<recipe>"``.
    """
    match pass_type:
        case OptimizationPass.AREA:
            return "strash; dch; map -a; topo; buffer -p; upsize -p"

        case OptimizationPass.SPEED:
            delay_flag = f" -D {int(target_delay)}" if target_delay else ""
            return (
                f"strash; dch -f; map{delay_flag}; "
                "topo; buffer -p; upsize -p; dnsize -p"
            )

        case OptimizationPass.BALANCED:
            return "strash; dch; map; topo; buffer"

        case OptimizationPass.LOW_POWER:
            return "strash; dch; map -a; topo; dnsize -p; gate_sizing"

        case _:
            return "strash; dch; map; topo; buffer"


# ---------------------------------------------------------------------------
# Full Yosys synthesis script generation
# ---------------------------------------------------------------------------


def generate_synth_script(
    sources: Sequence[str | PathLike[str]],
    top: str,
    liberty: str | PathLike[str],
    output_dir: str | PathLike[str],
    *,
    opt_pass: OptimizationPass = OptimizationPass.BALANCED,
    target_delay_ps: float | None = None,
    flatten: bool = False,
    extra_commands: Sequence[str] = (),
) -> str:
    """Generate a complete Yosys synthesis script.

    The script covers: read sources, hierarchy elaboration, generic
    optimisation, FSM extraction, technology mapping with ABC, and
    output generation (gate-level Verilog, JSON netlist, BLIF, stats).

    Parameters
    ----------
    sources:
        HDL source files (``.v``, ``.sv``, ``.vhd``).
    top:
        Top-level module name.
    liberty:
        Liberty (``.lib``) file for technology mapping.
    output_dir:
        Directory where output artefacts are written.
    opt_pass:
        ABC optimisation strategy.
    target_delay_ps:
        Target combinational delay in picoseconds (used by SPEED pass).
    flatten:
        Flatten the hierarchy before mapping.
    extra_commands:
        Additional Yosys commands inserted after FSM optimisation and
        before technology mapping.

    Returns
    -------
    str
        A multi-line Yosys command script.
    """
    out = Path(output_dir)
    lib = str(liberty)
    lines: list[str] = []

    # ---- Stage 1: Read sources -------------------------------------------
    for src in sources:
        p = Path(src)
        # Use POSIX paths for Docker compatibility
        src_posix = p.as_posix()
        match p.suffix:
            case ".sv" | ".svh":
                lines.append(f"read_verilog -sv {src_posix}")
            case ".vhd" | ".vhdl":
                lines.append(f"read_vhdl {src_posix}")
            case _:
                lines.append(f"read_verilog {src_posix}")

    # ---- Stage 2: Hierarchy elaboration ----------------------------------
    lines.append(f"hierarchy -top {top} -check")
    if flatten:
        lines.append("flatten")

    # ---- Stage 3: Generic optimisation -----------------------------------
    lines.append("proc; opt")
    lines.append("memory; opt")

    # ---- Stage 4: FSM extraction -----------------------------------------
    lines.append("fsm; opt")

    # ---- Extra user commands ---------------------------------------------
    lines.extend(extra_commands)

    # ---- Stage 5: Technology mapping -------------------------------------
    lines.append("techmap; opt")

    # ---- Stage 6 & 7: Liberty-based mapping (if Liberty file available) --
    if lib:
        lines.append(f"dfflibmap -liberty {Path(lib).as_posix()}")
        abc_recipe = generate_abc_script(opt_pass, target_delay_ps, liberty)
        delay_flag = f" -D {int(target_delay_ps)}" if target_delay_ps else ""
        lines.append(f'abc -liberty {Path(lib).as_posix()}{delay_flag} -script "+{abc_recipe}"')
    else:
        # Generic synthesis without technology library
        lines.append("abc")

    # ---- Stage 8: Cleanup ------------------------------------------------
    lines.append("opt_clean")

    # ---- Stage 9: Write outputs ------------------------------------------
    lines.append(f"write_verilog {(out / 'netlist.v').as_posix()}")
    lines.append(f"write_json {(out / 'netlist.json').as_posix()}")
    lines.append(f"write_blif {(out / 'netlist.blif').as_posix()}")

    # ---- Stage 10: Statistics --------------------------------------------
    if lib:
        lines.append(f"tee -o {(out / 'stats.txt').as_posix()} stat -liberty {Path(lib).as_posix()}")
    else:
        lines.append(f"tee -o {(out / 'stats.txt').as_posix()} stat")
    lines.append("stat")

    return "\n".join(lines) + "\n"
