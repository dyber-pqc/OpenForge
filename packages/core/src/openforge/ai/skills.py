"""Hardware-design AI skills and project-context gathering.

A *skill* is a small Pydantic model wrapping a system prompt and a hint
list of tools the assistant may use. The :class:`AiContext` helper
gathers project files and recent run logs into a single text blob that
can be prepended to the model's system prompt.
"""

from __future__ import annotations

import glob as _glob
from pathlib import Path

from pydantic import BaseModel, Field


class AiSkill(BaseModel):
    name: str
    description: str
    system_prompt: str
    tools: list[str] = Field(default_factory=list)


SKILLS: dict[str, AiSkill] = {
    "rtl_explain": AiSkill(
        name="rtl_explain",
        description="Explain a Verilog/SystemVerilog/VHDL module in plain English.",
        system_prompt=(
            "You are an expert digital design engineer. Given an RTL module, "
            "explain its function, ports, internal state, clock/reset behaviour, "
            "and any non-obvious tricks. Be precise and technical. Use bullet "
            "points and short code references."
        ),
        tools=["read_file"],
    ),
    "rtl_review": AiSkill(
        name="rtl_review",
        description="Review RTL for bugs, lint issues, and synthesis problems.",
        system_prompt=(
            "You are a senior RTL reviewer. Find functional bugs, race "
            "conditions, latches, blocking-vs-nonblocking misuse, reset "
            "issues, CDC hazards, and synthesis pitfalls. For each finding "
            "give: severity, line reference, why it's wrong, and a fix."
        ),
        tools=["read_file"],
    ),
    "sdc_generator": AiSkill(
        name="sdc_generator",
        description="Generate SDC timing constraints from a natural-language spec.",
        system_prompt=(
            "You write SDC (Synopsys Design Constraints) for ASIC and FPGA "
            "designs. Given a clock spec and IO description, output a clean "
            "SDC file using create_clock, set_input_delay, set_output_delay, "
            "set_clock_uncertainty, set_false_path, and set_multicycle_path. "
            "Wrap output in ```sdc fences."
        ),
        tools=[],
    ),
    "constraint_debug": AiSkill(
        name="constraint_debug",
        description="Diagnose failing timing paths and suggest constraint fixes.",
        system_prompt=(
            "You are a static-timing analysis expert. Given a failing path "
            "report (startpoint, endpoint, slack, clock skew), identify the "
            "root cause (missing constraint, false path, multicycle, real "
            "logic) and propose either an SDC change or an RTL change."
        ),
        tools=["read_file"],
    ),
    "drc_fix": AiSkill(
        name="drc_fix",
        description="Suggest fixes for physical-design DRC violations.",
        system_prompt=(
            "You are a sky130/gf180 physical verification expert. Given a "
            "DRC violation (rule name, geometry, layer), explain what the "
            "rule means and propose a layout-level fix."
        ),
        tools=[],
    ),
    "testbench_writer": AiSkill(
        name="testbench_writer",
        description="Write a self-checking testbench for a given module.",
        system_prompt=(
            "You write self-checking SystemVerilog testbenches. Given a "
            "module, infer its interface and produce a testbench with: "
            "clock generation, reset, stimulus, golden reference, and an "
            "$error-on-mismatch checker. Use ```systemverilog fences."
        ),
        tools=["read_file"],
    ),
    "spice_assistant": AiSkill(
        name="spice_assistant",
        description="Help debug analog circuits and ngspice netlists.",
        system_prompt=(
            "You are an analog IC design expert fluent in ngspice and "
            "sky130 PDK device models. Help the user write subcircuits, "
            "set up DC/AC/TRAN/noise analyses, and interpret simulation "
            "results. Always show the resulting .cir snippet in a fence."
        ),
        tools=[],
    ),
    "pcb_routing_helper": AiSkill(
        name="pcb_routing_helper",
        description="PCB layout and routing best practices.",
        system_prompt=(
            "You are a PCB layout engineer. Help with stackup, impedance "
            "control, return paths, decoupling, length matching, and EMI "
            "mitigation. Be specific to the technology (FR4, Rogers, "
            "flex). Provide concrete trace widths and via stitching "
            "recommendations."
        ),
        tools=[],
    ),
    "yaml_config_writer": AiSkill(
        name="yaml_config_writer",
        description="Generate an openforge.yaml from a project description.",
        system_prompt=(
            "You generate OpenForge project configuration files. Output a "
            "valid openforge.yaml with project, sources, synthesis, "
            "physical, and constraints sections matching the user's "
            "described design. Wrap in ```yaml fences."
        ),
        tools=[],
    ),
}


class AiContext:
    """Project-aware context gatherer for AI prompts."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)

    def gather_files(self, globs: list[str], max_bytes: int = 100_000) -> str:
        """Concatenate files matching ``globs`` (relative to project_root)."""
        chunks: list[str] = []
        used = 0
        for pat in globs:
            for raw in _glob.glob(str(self.project_root / pat), recursive=True):
                p = Path(raw)
                if not p.is_file():
                    continue
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                rel = p.relative_to(self.project_root) if p.is_absolute() else p
                header = f"\n----- {rel} -----\n"
                budget = max_bytes - used - len(header)
                if budget <= 0:
                    chunks.append("\n[context truncated]\n")
                    return "".join(chunks)
                if len(text) > budget:
                    text = text[:budget] + "\n[file truncated]\n"
                chunks.append(header + text)
                used += len(header) + len(text)
        return "".join(chunks)

    def gather_run_logs(self, stage: str) -> str:
        """Find recent log files for a flow stage and concatenate them."""
        candidates = [
            f"**/{stage}*.log",
            f"**/{stage}*.rpt",
            f"**/{stage}_build/*.log",
            f"build/{stage}/*.log",
        ]
        return self.gather_files(candidates, max_bytes=50_000)

    def system_prompt(self, skill_name: str) -> str:
        """Compose a final system prompt: skill prompt + project info."""
        skill = SKILLS.get(skill_name)
        base = skill.system_prompt if skill else ""
        meta = f"\n\nProject root: {self.project_root}\n"
        return base + meta


__all__ = ["AiSkill", "AiContext", "SKILLS"]
