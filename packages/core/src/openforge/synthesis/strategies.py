"""Pre-defined synthesis strategies (presets) for OpenForge.

Modeled after Vivado synthesis strategies, these provide opinionated
combinations of Yosys flags, optimization passes, and resource hints
for common synthesis goals.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OptimizationGoal(Enum):
    """High-level optimization target for a synthesis run."""

    AREA = "area"
    SPEED = "speed"
    POWER = "power"
    BALANCED = "balanced"
    DEFAULT = "default"


@dataclass
class SynthesisStrategy:
    """A named synthesis strategy with all relevant tunables.

    A strategy bundles Yosys flags, optimization pass selection, and
    resource usage hints. Strategies are converted to a Yosys script via
    :func:`generate_yosys_script`.
    """

    name: str
    display_name: str
    description: str
    goal: OptimizationGoal

    # Yosys flags
    yosys_flatten: bool = False
    yosys_keep_hierarchy: bool = False
    yosys_no_share: bool = False
    yosys_retime: bool = False
    yosys_abc_script: str = ""  # custom ABC script

    # Optimization passes
    opt_full: bool = True
    opt_clean: bool = True
    opt_share: bool = True
    opt_demorgan: bool = False

    # Resource usage
    use_dsp: bool = True
    use_bram: bool = True
    max_fanout: int = 0  # 0 = unlimited

    # Reports
    generate_reports: bool = True

    # Tradeoff hints (for UI display): -1 worse, 0 neutral, +1 better
    area_impact: int = 0
    speed_impact: int = 0
    power_impact: int = 0
    runtime_impact: int = 0  # +1 = faster compile, -1 = slower compile

    # Extra free-form notes
    notes: str = ""

    def to_dict(self) -> dict:
        """Serialize the strategy to a plain dict (for caching/config)."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "goal": self.goal.value,
            "yosys_flatten": self.yosys_flatten,
            "yosys_keep_hierarchy": self.yosys_keep_hierarchy,
            "yosys_no_share": self.yosys_no_share,
            "yosys_retime": self.yosys_retime,
            "yosys_abc_script": self.yosys_abc_script,
            "opt_full": self.opt_full,
            "opt_clean": self.opt_clean,
            "opt_share": self.opt_share,
            "opt_demorgan": self.opt_demorgan,
            "use_dsp": self.use_dsp,
            "use_bram": self.use_bram,
            "max_fanout": self.max_fanout,
            "generate_reports": self.generate_reports,
            "area_impact": self.area_impact,
            "speed_impact": self.speed_impact,
            "power_impact": self.power_impact,
            "runtime_impact": self.runtime_impact,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SynthesisStrategy:
        """Reconstruct from a dict produced by :meth:`to_dict`."""
        goal_val = data.get("goal", "default")
        try:
            goal = OptimizationGoal(goal_val)
        except ValueError:
            goal = OptimizationGoal.DEFAULT
        return cls(
            name=data["name"],
            display_name=data.get("display_name", data["name"]),
            description=data.get("description", ""),
            goal=goal,
            yosys_flatten=data.get("yosys_flatten", False),
            yosys_keep_hierarchy=data.get("yosys_keep_hierarchy", False),
            yosys_no_share=data.get("yosys_no_share", False),
            yosys_retime=data.get("yosys_retime", False),
            yosys_abc_script=data.get("yosys_abc_script", ""),
            opt_full=data.get("opt_full", True),
            opt_clean=data.get("opt_clean", True),
            opt_share=data.get("opt_share", True),
            opt_demorgan=data.get("opt_demorgan", False),
            use_dsp=data.get("use_dsp", True),
            use_bram=data.get("use_bram", True),
            max_fanout=data.get("max_fanout", 0),
            generate_reports=data.get("generate_reports", True),
            area_impact=data.get("area_impact", 0),
            speed_impact=data.get("speed_impact", 0),
            power_impact=data.get("power_impact", 0),
            runtime_impact=data.get("runtime_impact", 0),
            notes=data.get("notes", ""),
        )

    def tradeoff_summary(self) -> str:
        """Return a short human-readable tradeoff summary."""

        def arrow(v: int) -> str:
            if v > 0:
                return "up"
            if v < 0:
                return "down"
            return "neutral"

        return (
            f"Area: {arrow(self.area_impact)}, "
            f"Speed: {arrow(self.speed_impact)}, "
            f"Power: {arrow(self.power_impact)}, "
            f"Runtime: {arrow(self.runtime_impact)}"
        )

    def yosys_flag_summary(self) -> list[str]:
        """Return a list of Yosys flags this strategy will enable."""
        flags: list[str] = []
        if self.yosys_flatten:
            flags.append("flatten hierarchy")
        if self.yosys_keep_hierarchy:
            flags.append("keep hierarchy")
        if self.yosys_no_share:
            flags.append("disable resource sharing")
        if self.yosys_retime:
            flags.append("retiming")
        if self.opt_full:
            flags.append("opt -full")
        if self.opt_share:
            flags.append("opt share")
        if self.opt_demorgan:
            flags.append("opt demorgan")
        if self.use_dsp:
            flags.append("infer DSP")
        if self.use_bram:
            flags.append("infer BRAM")
        if self.max_fanout > 0:
            flags.append(f"max_fanout={self.max_fanout}")
        if self.yosys_abc_script:
            flags.append("custom ABC script")
        return flags


BUILTIN_STRATEGIES: dict[str, SynthesisStrategy] = {
    "default": SynthesisStrategy(
        name="default",
        display_name="Default",
        description="Balanced synthesis with default Yosys flow.",
        goal=OptimizationGoal.DEFAULT,
        notes="Good starting point for most designs.",
    ),
    "area_optimized": SynthesisStrategy(
        name="area_optimized",
        display_name="Area Optimized",
        description="Minimize total cell area, may impact timing.",
        goal=OptimizationGoal.AREA,
        yosys_flatten=True,
        opt_share=True,
        opt_demorgan=True,
        yosys_abc_script=("strash; ifraig; scorr; dc2; dretime; strash; dch -f; map -m -B 0.2"),
        area_impact=1,
        speed_impact=-1,
        power_impact=0,
        runtime_impact=-1,
        notes="Aggressive sharing and DeMorgan rewrites shrink the netlist.",
    ),
    "speed_optimized": SynthesisStrategy(
        name="speed_optimized",
        display_name="Speed Optimized",
        description="Maximize clock frequency, accepts larger area.",
        goal=OptimizationGoal.SPEED,
        yosys_retime=True,
        yosys_abc_script=(
            "strash; dch; map -B 0.9; topo; stime -p; buffer; upsize; dnsize; stime -p"
        ),
        area_impact=-1,
        speed_impact=1,
        power_impact=-1,
        runtime_impact=-1,
        notes="Retiming and aggressive buffer sizing for max Fmax.",
    ),
    "power_optimized": SynthesisStrategy(
        name="power_optimized",
        display_name="Power Optimized",
        description="Minimize switching power.",
        goal=OptimizationGoal.POWER,
        opt_full=True,
        max_fanout=8,
        area_impact=0,
        speed_impact=-1,
        power_impact=1,
        runtime_impact=0,
        notes="Caps fanout to reduce dynamic switching power.",
    ),
    "preserve_hierarchy": SynthesisStrategy(
        name="preserve_hierarchy",
        display_name="Preserve Hierarchy",
        description="Keep all module boundaries (debug-friendly).",
        goal=OptimizationGoal.DEFAULT,
        yosys_keep_hierarchy=True,
        opt_share=False,
        area_impact=-1,
        speed_impact=0,
        power_impact=0,
        runtime_impact=1,
        notes="Useful for debugging, formal verification, and reports.",
    ),
    "high_effort": SynthesisStrategy(
        name="high_effort",
        display_name="High Effort",
        description="Maximum optimization, slower compile time.",
        goal=OptimizationGoal.BALANCED,
        yosys_flatten=True,
        yosys_retime=True,
        opt_full=True,
        opt_share=True,
        area_impact=1,
        speed_impact=1,
        power_impact=0,
        runtime_impact=-1,
        notes="Throws everything at the design. Use for final builds.",
    ),
}


def get_strategy(name: str) -> SynthesisStrategy:
    """Look up a built-in strategy by name, or return ``default``."""
    return BUILTIN_STRATEGIES.get(name, BUILTIN_STRATEGIES["default"])


def list_strategies() -> list[SynthesisStrategy]:
    """Return all registered built-in strategies."""
    return list(BUILTIN_STRATEGIES.values())


def list_strategy_names() -> list[str]:
    """Return the canonical names of all built-in strategies."""
    return list(BUILTIN_STRATEGIES.keys())


def make_custom_strategy(
    *,
    name: str = "custom",
    display_name: str = "Custom",
    description: str = "User-defined synthesis strategy.",
    goal: OptimizationGoal = OptimizationGoal.BALANCED,
    yosys_flatten: bool = False,
    yosys_keep_hierarchy: bool = False,
    yosys_retime: bool = False,
    use_dsp: bool = True,
    use_bram: bool = True,
    max_fanout: int = 0,
    yosys_abc_script: str = "",
) -> SynthesisStrategy:
    """Build a fresh ``SynthesisStrategy`` from individual settings.

    Used by the GUI Custom strategy editor.
    """
    return SynthesisStrategy(
        name=name,
        display_name=display_name,
        description=description,
        goal=goal,
        yosys_flatten=yosys_flatten,
        yosys_keep_hierarchy=yosys_keep_hierarchy,
        yosys_retime=yosys_retime,
        use_dsp=use_dsp,
        use_bram=use_bram,
        max_fanout=max_fanout,
        yosys_abc_script=yosys_abc_script,
    )


def generate_yosys_script(
    strategy: SynthesisStrategy,
    top_module: str,
    sources: list[str],
    liberty: str,
    output: str,
    *,
    include_stat: bool = True,
    extra_commands: list[str] | None = None,
) -> str:
    """Generate a complete Yosys synthesis script.

    Parameters
    ----------
    strategy:
        Strategy whose flags drive script generation.
    top_module:
        Top-level module name.
    sources:
        List of Verilog/SystemVerilog source paths.
    liberty:
        Path to a Liberty (.lib) file for ABC tech mapping.
    output:
        Path for the synthesized Verilog netlist.
    include_stat:
        Whether to emit a final ``stat`` command.
    extra_commands:
        Optional commands inserted before ``write_verilog``.
    """
    lines: list[str] = []
    lines.append("# Synthesis script generated by OpenForge")
    lines.append(f"# Strategy: {strategy.display_name} ({strategy.name})")
    lines.append(f"# Goal:     {strategy.goal.value}")
    lines.append("")

    for src in sources:
        lines.append(f"read_verilog -sv {src}")
    lines.append(f"hierarchy -check -top {top_module}")

    if strategy.yosys_keep_hierarchy:
        lines.append("# Preserve hierarchy")
        lines.append("hierarchy -keep_positionals")
    else:
        lines.append("flatten")

    lines.append("proc")

    if strategy.opt_full:
        lines.append("opt -full")
    else:
        lines.append("opt")

    if strategy.use_dsp:
        lines.append("synth -run coarse")

    if strategy.opt_share and not strategy.yosys_no_share:
        lines.append("share")

    if strategy.opt_demorgan:
        lines.append("opt_expr -mux_undef")

    lines.append("memory")
    lines.append("opt -fast")
    lines.append("techmap")

    if strategy.yosys_retime:
        lines.append("# Retiming")
        lines.append("abc -fast")

    if strategy.yosys_abc_script:
        lines.append(f"abc -liberty {liberty} -script {{{strategy.yosys_abc_script}}}")
    else:
        lines.append(f"abc -liberty {liberty}")

    if strategy.max_fanout > 0:
        lines.append(f"# Limit fanout to {strategy.max_fanout}")
        lines.append("opt -fast -fine")

    if strategy.opt_clean:
        lines.append("clean")

    if include_stat:
        lines.append("stat")

    if extra_commands:
        lines.extend(extra_commands)

    lines.append(f"write_verilog {output}")
    return "\n".join(lines)


def estimate_runtime_seconds(strategy: SynthesisStrategy, num_cells: int) -> float:
    """Rough heuristic estimate of synthesis runtime in seconds."""
    base = 1.0 + (num_cells / 1000.0) * 2.0
    if strategy.yosys_retime:
        base *= 1.6
    if strategy.opt_full:
        base *= 1.2
    if strategy.yosys_abc_script:
        base *= 1.3
    if strategy.runtime_impact < 0:
        base *= 1.5
    return base
