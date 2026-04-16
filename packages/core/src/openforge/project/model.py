"""Project model v2 - unified schema for ASIC / FPGA / PCB / mixed targets.

This is the canonical project representation used by the run engine, flows,
templates, and UI. It is independent from the legacy
``openforge.project.manager.Project`` (which wraps a directory+OpenForgeConfig)
and from ``openforge.config.schema.OpenForgeConfig``.

Projects are YAML round-trippable via :meth:`Project.load` / :meth:`Project.save`.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectKind(StrEnum):
    """Top-level kind of an OpenForge project."""

    ASIC = "asic"
    FPGA = "fpga"
    PCB = "pcb"
    MIXED = "mixed"


class TargetKind(StrEnum):
    """Physical target kind."""

    ASIC = "asic"
    FPGA = "fpga"
    PCB = "pcb"


class Target(BaseModel):
    """Physical implementation target (device/package/vendor)."""

    model_config = ConfigDict(extra="allow")

    kind: TargetKind
    device: str | None = None
    family: str | None = None
    package: str | None = None
    vendor: str | None = None
    speed_grade: str | None = None
    board: str | None = None


class CornerSet(BaseModel):
    """A single PVT corner (process/voltage/temperature) with its libs."""

    model_config = ConfigDict(extra="allow")

    name: str
    process: str = Field(description="tt | ss | ff | fs | sf etc.")
    voltage: float
    temperature: float
    lib_files: list[str] = Field(default_factory=list)
    qrc_file: str | None = None
    rcx_file: str | None = None


class ConstraintKind(StrEnum):
    CLOCK = "clock"
    INPUT_DELAY = "input_delay"
    OUTPUT_DELAY = "output_delay"
    FALSE_PATH = "false_path"
    MULTICYCLE = "multicycle"
    MAX_DELAY = "max_delay"
    MIN_DELAY = "min_delay"
    SET_LOAD = "set_load"
    SET_DRIVING_CELL = "set_driving_cell"
    CASE_ANALYSIS = "case_analysis"


class Constraint(BaseModel):
    """A single timing/physical constraint."""

    model_config = ConfigDict(extra="allow")

    kind: ConstraintKind
    value: Any = None
    paths: list[str] = Field(default_factory=list)
    name: str | None = None
    comment: str | None = None


class IPInstance(BaseModel):
    """An IP instance drawn from the local or remote IP catalog."""

    model_config = ConfigDict(extra="allow")

    name: str
    ip_type: str
    params: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="local", description="local | catalog | url | git")
    version: str | None = None


class RunConfig(BaseModel):
    """User-declared run stage configuration (serialised into openforge.yaml).

    This is the *declarative* form. It gets expanded into a
    :class:`openforge.runner.engine.RunStage` at execution time.
    """

    model_config = ConfigDict(extra="allow")

    stage: str
    tool: str
    options: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    enabled: bool = True


class PDKRef(BaseModel):
    """Reference to a PDK (by name, optionally pinned to a version/path)."""

    model_config = ConfigDict(extra="allow")

    name: str
    version: str | None = None
    path: str | None = None
    std_cell_lib: str | None = None
    variant: str | None = None


class Project(BaseModel):
    """Unified project model covering ASIC, FPGA, PCB and mixed flows."""

    model_config = ConfigDict(extra="allow", validate_assignment=True)

    name: str
    version: str = "1"
    kind: ProjectKind
    top_module: str = ""

    rtl_sources: list[str] = Field(default_factory=list)
    constraint_files: list[str] = Field(default_factory=list)
    tb_sources: list[str] = Field(default_factory=list)
    include_dirs: list[str] = Field(default_factory=list)
    defines: dict[str, str] = Field(default_factory=dict)

    pdk: PDKRef | None = None
    target: Target | None = None
    corners: list[CornerSet] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)

    runs: list[RunConfig] = Field(default_factory=list)
    ips: list[IPInstance] = Field(default_factory=list)

    board_file: str | None = None
    pcb_file: str | None = None
    schematic_file: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("runs")
    @classmethod
    def _unique_stage_ids(cls, v: list[RunConfig]) -> list[RunConfig]:
        seen: set[str] = set()
        for r in v:
            if r.stage in seen:
                raise ValueError(f"duplicate run stage id: {r.stage}")
            seen.add(r.stage)
        return v

    # ----- IO ---------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> Project:
        """Load a project from a YAML file (``openforge.yaml``)."""
        p = Path(path)
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)

    def save(self, path: str | Path) -> Path:
        """Serialise this project to YAML. Returns the written path."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json", exclude_none=True)
        p.write_text(
            yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        return p

    # ----- validation -------------------------------------------------------

    def validate_consistency(self) -> list[str]:
        """Return a list of human-readable warnings/errors.

        This is *advisory* - it does not raise. Empty list means the project
        looks consistent.
        """
        issues: list[str] = []

        if not self.name:
            issues.append("project.name is empty")
        if not self.top_module and self.kind != ProjectKind.PCB:
            issues.append("top_module is required for non-PCB projects")
        if self.kind in (ProjectKind.ASIC, ProjectKind.FPGA, ProjectKind.MIXED):
            if not self.rtl_sources:
                issues.append(f"{self.kind.value} project has no rtl_sources")
        if self.kind == ProjectKind.ASIC:
            if self.pdk is None:
                issues.append("ASIC project requires a PDK")
            if not self.corners:
                issues.append("ASIC project should define at least one corner")
        if self.kind == ProjectKind.FPGA:
            if self.target is None or self.target.kind != TargetKind.FPGA:
                issues.append("FPGA project requires an FPGA target")
        if self.kind == ProjectKind.PCB and not (self.pcb_file or self.schematic_file):
            issues.append("PCB project requires a pcb_file or schematic_file")

        # run DAG consistency
        stage_ids = {r.stage for r in self.runs}
        for r in self.runs:
            for dep in r.depends_on:
                if dep not in stage_ids:
                    issues.append(f"run '{r.stage}' depends on unknown stage '{dep}'")

        # corner name uniqueness
        names: set[str] = set()
        for c in self.corners:
            if c.name in names:
                issues.append(f"duplicate corner name: {c.name}")
            names.add(c.name)

        return issues


__all__ = [
    "Project",
    "ProjectKind",
    "Target",
    "TargetKind",
    "CornerSet",
    "Constraint",
    "ConstraintKind",
    "IPInstance",
    "RunConfig",
    "PDKRef",
]
