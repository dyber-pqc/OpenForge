"""Hierarchical place-and-route model for OpenForge.

This module defines the data model and flow controller used to run
large designs as a set of independently-synthesized-and-routed blocks
that are then integrated at the top level.

The typical bottom-up flow is:

1. Synthesize each leaf block using its own constraints and budget.
2. Place and route each block in isolation.
3. Emit a LEF abstract for each finished block (see
   :mod:`openforge.physical.lef_abstract`).
4. Synthesize and integrate the top level, consuming the abstracts as
   hard macros.

The :class:`HierDesign` model is purely declarative; the
:class:`HierarchicalFlow` class drives the actual work and produces
artifacts under ``work_dir``.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from openforge.runner.engine import RunGraph


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


class BlockBudget(BaseModel):
    """Per-block area / timing / power budget.

    ``pin_budget`` maps a top-level pin name to its arrival (input) or
    required (output) time in nanoseconds. A positive number is
    interpreted consistently with the SDC semantics the caller chose.
    """

    model_config = ConfigDict(extra="allow")

    block_name: str
    max_area_um2: float = 0.0
    target_freq_mhz: float = 0.0
    pin_budget: dict[str, float] = Field(default_factory=dict)
    power_budget_mw: float = 0.0
    utilization_target: float = 0.7

    @property
    def target_period_ns(self) -> float:
        if self.target_freq_mhz <= 0:
            return 0.0
        return 1000.0 / self.target_freq_mhz


# ---------------------------------------------------------------------------
# Block + design
# ---------------------------------------------------------------------------


BlockState = str  # "not_started" | "synth_done" | "pnr_done" | "abstract_done" | "frozen"

VALID_BLOCK_STATES = {
    "not_started",
    "synth_done",
    "pnr_done",
    "abstract_done",
    "frozen",
}


class HierBlock(BaseModel):
    """A single block in the hierarchical design."""

    model_config = ConfigDict(extra="allow")

    name: str
    rtl_files: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    budget: BlockBudget
    parent: str | None = None
    children: list[str] = Field(default_factory=list)
    state: BlockState = "not_started"

    abstract_lef: str | None = None
    netlist: str | None = None
    def_path: str | None = None

    # diagnostics updated as the flow progresses
    area_um2: float = 0.0
    achieved_freq_mhz: float = 0.0
    utilization: float = 0.0
    wns_ns: float = 0.0
    leakage_mw: float = 0.0


class HierDesign(BaseModel):
    """A declarative hierarchical design."""

    model_config = ConfigDict(extra="allow")

    top: str
    blocks: dict[str, HierBlock] = Field(default_factory=dict)
    integration_order: list[str] = Field(default_factory=list)

    # ----- graph manipulation --------------------------------------------

    def add_block(self, block: HierBlock) -> None:
        """Insert or replace a block. Keeps parent/child links consistent."""
        self.blocks[block.name] = block
        if block.parent is not None:
            parent = self.blocks.get(block.parent)
            if parent is not None and block.name not in parent.children:
                parent.children.append(block.name)
        # reset integration order; caller should recompute
        self._recompute_integration_order()

    def _recompute_integration_order(self) -> None:
        """Compute a bottom-up integration order.

        Leaves first, top last. Uses an iterative post-order walk of the
        children graph rooted at :attr:`top`.
        """
        order: list[str] = []
        visited: set[str] = set()
        stack: list[tuple[str, bool]] = [(self.top, False)]
        while stack:
            name, processed = stack.pop()
            if processed:
                if name not in visited:
                    visited.add(name)
                    order.append(name)
                continue
            if name in visited or name not in self.blocks:
                continue
            stack.append((name, True))
            for child in self.blocks[name].children:
                if child not in visited:
                    stack.append((child, False))
        # Include any orphan blocks (not reachable from top) at the end
        for name in self.blocks:
            if name not in visited:
                order.append(name)
        self.integration_order = order

    def block_dependencies(self, block_name: str) -> list[str]:
        """Return the list of child blocks that must be finished first."""
        block = self.blocks.get(block_name)
        if block is None:
            return []
        return list(block.children)

    def can_run(self, block_name: str) -> bool:
        """True if all children are at ``abstract_done`` or ``frozen``."""
        for child in self.block_dependencies(block_name):
            c = self.blocks.get(child)
            if c is None:
                return False
            if c.state not in ("abstract_done", "frozen"):
                return False
        return True

    # ----- run graph ------------------------------------------------------

    def to_run_graph(self) -> RunGraph:
        """Build a :class:`RunGraph` that walks the hierarchy bottom-up.

        Each block contributes three stages: ``synth``, ``pnr`` and
        ``abstract``. Edges encode both intra-block ordering and the
        bottom-up inter-block dependencies.
        """
        from openforge.runner.engine import RunGraph, RunStage

        graph = RunGraph()
        if not self.integration_order:
            self._recompute_integration_order()

        for block_name in self.integration_order:
            block = self.blocks.get(block_name)
            if block is None:
                continue
            dep_abstracts = [
                f"{child}.abstract"
                for child in block.children
                if child in self.blocks
            ]
            synth_id = f"{block_name}.synth"
            pnr_id = f"{block_name}.pnr"
            abs_id = f"{block_name}.abstract"
            graph.add_stage(
                RunStage(
                    id=synth_id,
                    name=f"Synthesize {block_name}",
                    tool="yosys",
                    depends_on=dep_abstracts,
                    produces=[f"{block_name}.v"],
                )
            )
            graph.add_stage(
                RunStage(
                    id=pnr_id,
                    name=f"Place & route {block_name}",
                    tool="openroad",
                    depends_on=[synth_id],
                    produces=[f"{block_name}.def"],
                )
            )
            graph.add_stage(
                RunStage(
                    id=abs_id,
                    name=f"Abstract {block_name}",
                    tool="openforge-abstract",
                    depends_on=[pnr_id],
                    produces=[f"{block_name}.abstract.lef"],
                )
            )
        return graph


# ---------------------------------------------------------------------------
# Flow controller
# ---------------------------------------------------------------------------


class HierarchicalFlow:
    """Drive a :class:`HierDesign` through the bottom-up flow.

    This class deliberately keeps the actual tool invocation pluggable:
    callers supply the engines (yosys, openroad, ...) via keyword
    arguments or subclass hooks. In absence of a real engine the flow
    still produces the necessary directory structure, stub artifacts
    and bookkeeping records so that downstream tools (the desktop
    panel, the ECO engine) can be exercised end-to-end.
    """

    def __init__(
        self,
        design: HierDesign,
        work_dir: Path,
        *,
        synth_engine: Any | None = None,
        pnr_engine: Any | None = None,
    ) -> None:
        self.design = design
        self.work_dir = Path(work_dir)
        self.synth_engine = synth_engine
        self.pnr_engine = pnr_engine
        self.work_dir.mkdir(parents=True, exist_ok=True)

    # ----- per-block directories -----------------------------------------

    def block_dir(self, name: str) -> Path:
        d = self.work_dir / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ----- stages ---------------------------------------------------------

    def synthesize_block(self, name: str) -> dict[str, Any]:
        block = self._get(name)
        bdir = self.block_dir(name)
        netlist = bdir / f"{name}.v"
        report: dict[str, Any] = {
            "block": name,
            "tool": "yosys",
            "rtl": list(block.rtl_files),
            "constraints": list(block.constraints),
            "target_period_ns": block.budget.target_period_ns,
        }
        if self.synth_engine is not None and hasattr(self.synth_engine, "synthesize"):
            result = self.synth_engine.synthesize(
                rtl=block.rtl_files,
                top=name,
                output=netlist,
                constraints=block.constraints,
            )
            report.update(result or {})
        else:
            # Stub: write a minimal placeholder netlist so downstream
            # steps have something to read.
            netlist.write_text(
                f"// placeholder synthesis result for {name}\n"
                f"module {name} (); endmodule\n"
            )
            report["status"] = "stub"
        block.netlist = str(netlist)
        block.state = "synth_done"
        return report

    def place_route_block(self, name: str) -> dict[str, Any]:
        block = self._get(name)
        if block.state not in ("synth_done", "pnr_done"):
            raise RuntimeError(
                f"cannot place/route {name}: state={block.state}"
            )
        bdir = self.block_dir(name)
        def_path = bdir / f"{name}.def"
        report: dict[str, Any] = {"block": name, "tool": "openroad"}
        if self.pnr_engine is not None and hasattr(self.pnr_engine, "run_pnr"):
            result = self.pnr_engine.run_pnr(
                netlist=block.netlist,
                top=name,
                output=def_path,
                budget=block.budget.model_dump(),
            )
            report.update(result or {})
            block.area_um2 = float(result.get("area_um2", block.area_um2))
            block.utilization = float(
                result.get("utilization", block.utilization)
            )
            block.achieved_freq_mhz = float(
                result.get("freq_mhz", block.achieved_freq_mhz)
            )
            block.wns_ns = float(result.get("wns_ns", block.wns_ns))
        else:
            # Stub DEF file
            def_path.write_text(
                "VERSION 5.8 ;\n"
                "DIVIDERCHAR \"/\" ;\n"
                "BUSBITCHARS \"[]\" ;\n"
                f"DESIGN {name} ;\n"
                "UNITS DISTANCE MICRONS 1000 ;\n"
                "DIEAREA ( 0 0 ) ( 100000 100000 ) ;\n"
                "END DESIGN\n"
            )
            block.area_um2 = 10000.0
            block.utilization = block.budget.utilization_target
            block.achieved_freq_mhz = block.budget.target_freq_mhz
            report["status"] = "stub"
        block.def_path = str(def_path)
        block.state = "pnr_done"
        return report

    def generate_abstract(self, name: str) -> Path:
        """Produce a LEF abstract for a finished block."""
        from openforge.physical.lef_abstract import generate_abstract_lef

        block = self._get(name)
        if block.state not in ("pnr_done", "abstract_done"):
            raise RuntimeError(
                f"cannot abstract {name}: state={block.state}"
            )
        if block.def_path is None:
            raise RuntimeError(f"{name} has no DEF path")
        bdir = self.block_dir(name)
        out = bdir / f"{name}.abstract.lef"
        # We pass an empty cell LEF path; the abstract generator uses
        # only the DEF and any LEFs it can find for metal layer info.
        generate_abstract_lef(Path(block.def_path), bdir / "cells.lef", out)
        block.abstract_lef = str(out)
        block.state = "abstract_done"
        return out

    def integrate_top(self) -> dict[str, Any]:
        """Integrate all block abstracts into a top-level DEF."""
        from openforge.physical.lef_abstract import (
            LefAbstract,
            merge_blocks_to_top,
            read_abstract_lef,
        )

        top = self._get(self.design.top)
        top_dir = self.block_dir(top.name)
        top_def = top_dir / f"{top.name}.top.def"

        abstracts: dict[str, LefAbstract] = {}
        for name, block in self.design.blocks.items():
            if name == top.name:
                continue
            if block.abstract_lef and Path(block.abstract_lef).exists():
                abstracts[name] = read_abstract_lef(Path(block.abstract_lef))

        merge_blocks_to_top(top_def, abstracts, top_def)
        top.def_path = str(top_def)
        top.state = "pnr_done"
        return {
            "top": top.name,
            "def": str(top_def),
            "block_count": len(abstracts),
        }

    # ----- budgets --------------------------------------------------------

    def propagate_budgets(self) -> None:
        """Top-down budget propagation.

        Children inherit the parent's clock period when they have none
        of their own, and area is split proportionally by each child's
        existing ``max_area_um2`` (or evenly when unset).
        """
        top = self._get(self.design.top)
        if not top.budget.target_freq_mhz:
            return
        stack = [top]
        while stack:
            parent = stack.pop()
            if not parent.children:
                continue
            children = [self.design.blocks[c] for c in parent.children if c in self.design.blocks]
            # clock period inheritance
            for c in children:
                if c.budget.target_freq_mhz <= 0:
                    c.budget.target_freq_mhz = parent.budget.target_freq_mhz * 1.1
                if c.budget.utilization_target <= 0:
                    c.budget.utilization_target = parent.budget.utilization_target
            # area split
            total_existing = sum(max(0.0, c.budget.max_area_um2) for c in children)
            if parent.budget.max_area_um2 > 0 and total_existing == 0 and children:
                share = parent.budget.max_area_um2 * 0.9 / len(children)
                for c in children:
                    c.budget.max_area_um2 = share
            elif parent.budget.max_area_um2 > 0 and total_existing > 0:
                for c in children:
                    ratio = max(0.0, c.budget.max_area_um2) / total_existing
                    c.budget.max_area_um2 = parent.budget.max_area_um2 * 0.9 * ratio
            # power split (evenly)
            if parent.budget.power_budget_mw > 0 and children:
                share_p = parent.budget.power_budget_mw * 0.95 / len(children)
                for c in children:
                    if c.budget.power_budget_mw <= 0:
                        c.budget.power_budget_mw = share_p
            stack.extend(children)

    # ----- collection -----------------------------------------------------

    def collect_final_artifacts(self) -> dict[str, Any]:
        out_dir = self.work_dir / "final"
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest: dict[str, Any] = {"top": self.design.top, "blocks": {}}
        for name, block in self.design.blocks.items():
            entry: dict[str, Any] = {"state": block.state}
            for field in ("netlist", "def_path", "abstract_lef"):
                p = getattr(block, field)
                if p and Path(p).exists():
                    dest = out_dir / Path(p).name
                    try:
                        shutil.copy2(p, dest)
                        entry[field] = str(dest)
                    except OSError:
                        entry[field] = p
            entry["area_um2"] = block.area_um2
            entry["achieved_freq_mhz"] = block.achieved_freq_mhz
            entry["utilization"] = block.utilization
            manifest["blocks"][name] = entry
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        return manifest

    # ----- helpers --------------------------------------------------------

    def _get(self, name: str) -> HierBlock:
        block = self.design.blocks.get(name)
        if block is None:
            raise KeyError(f"unknown block: {name}")
        return block


__all__ = [
    "BlockBudget",
    "HierBlock",
    "HierDesign",
    "HierarchicalFlow",
    "VALID_BLOCK_STATES",
]
