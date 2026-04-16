"""Pydantic v2 models for openforge.yaml project configuration."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SimulationTool(StrEnum):
    VERILATOR = "verilator"
    ICARUS = "icarus"
    GHDL = "ghdl"


class FormalTool(StrEnum):
    SYMBIYOSYS = "symbiyosys"


class FormalEngine(StrEnum):
    SMTBMC = "smtbmc"
    BTOR = "btor"
    AIGER = "aiger"
    ABC = "abc"


class TimingTool(StrEnum):
    OPENSTA = "opensta"


class PowerTool(StrEnum):
    OPENROAD = "openroad"


class FIPSLevel(StrEnum):
    LEVEL_1 = "1"
    LEVEL_2 = "2"
    LEVEL_3 = "3"
    LEVEL_4 = "4"


class NTTStandard(StrEnum):
    KYBER = "kyber"
    DILITHIUM = "dilithium"
    CUSTOM = "custom"


class PowerModel(StrEnum):
    HAMMING_WEIGHT = "hamming_weight"
    HAMMING_DISTANCE = "hamming_distance"
    TOGGLE_COUNT = "toggle_count"


# ---------------------------------------------------------------------------
# Sub-config models
# ---------------------------------------------------------------------------

class SourceFile(BaseModel):
    """A single HDL source file with per-file metadata."""

    path: Path
    library: str = "work"
    language: Literal["verilog", "systemverilog", "vhdl", "auto"] = "auto"
    is_testbench: bool = False


class ProjectConfig(BaseModel):
    """Top-level project metadata."""

    name: str = "untitled"
    top_module: str = "top"
    target_pdk: str | None = None
    include_dirs: list[Path] = Field(default_factory=list)
    defines: dict[str, str] = Field(default_factory=dict)
    language_version: Literal[
        "v2005", "sv2012", "sv2017", "vhdl93", "vhdl2008"
    ] = "sv2017"


class ElaborationConfig(BaseModel):
    """RTL elaboration step configuration."""

    enabled: bool = True
    check_hierarchy: bool = True
    optimize_constants: bool = True
    keep_comments: bool = False
    defines_extra: dict[str, str] = Field(default_factory=dict)


class DesignConfig(BaseModel):
    """Design source files and constraints."""

    sources: list[str] = Field(default_factory=list, description="Glob patterns for RTL source files")
    includes: list[str] = Field(default_factory=list, description="Include search directories")
    constraints: list[str] = Field(default_factory=list, description="SDC / constraint files")


class CoverageOptions(BaseModel):
    """Code coverage configuration for simulation."""

    line: bool = True
    toggle: bool = True
    branch: bool = False
    fsm: bool = False


class SimulationConfig(BaseModel):
    """Simulation runner configuration."""

    tool: SimulationTool = SimulationTool.VERILATOR
    testbenches: list[str] = Field(default_factory=list, description="Glob patterns for testbench files")
    coverage: CoverageOptions = Field(default_factory=CoverageOptions)
    plusargs: dict[str, str] = Field(default_factory=dict, description="Extra +arg values passed to simulator")
    timeout_seconds: Annotated[int, Field(ge=1)] = 300


class FormalConfig(BaseModel):
    """Formal verification configuration."""

    tool: FormalTool = FormalTool.SYMBIYOSYS
    properties: list[str] = Field(default_factory=list, description="SVA / PSL property files")
    engines: list[FormalEngine] = Field(default_factory=lambda: [FormalEngine.SMTBMC])
    depth: Annotated[int, Field(ge=1)] = 20


class ConstantTimeConfig(BaseModel):
    """Constant-time verification for crypto implementations."""

    secrets: list[str] = Field(default_factory=list, description="Signal names treated as secret")
    public: list[str] = Field(default_factory=list, description="Signal names treated as public")


class SideChannelConfig(BaseModel):
    """Side-channel leakage analysis settings."""

    power_model: PowerModel = PowerModel.HAMMING_WEIGHT
    tvla_threshold: float = Field(default=4.5, description="TVLA t-test threshold")
    num_traces: Annotated[int, Field(ge=1)] = 10_000


class EntropyAnalysisConfig(BaseModel):
    """Entropy flow tracking configuration."""

    sources: list[str] = Field(default_factory=list, description="Signals acting as entropy sources")
    sinks: list[str] = Field(default_factory=list, description="Signals acting as entropy sinks")


class FIPSComplianceConfig(BaseModel):
    """FIPS 140-3 compliance checking."""

    level: FIPSLevel = FIPSLevel.LEVEL_1
    checks: list[str] = Field(
        default_factory=lambda: ["kat", "integrity", "zeroize"],
        description="FIPS checks to run (e.g. kat, integrity, zeroize, pairwise)",
    )


class NTTValidationConfig(BaseModel):
    """Number Theoretic Transform validation for lattice crypto."""

    standard: NTTStandard = NTTStandard.KYBER
    exhaustive: bool = False


class CryptoVerificationConfig(BaseModel):
    """Cryptographic-specific verification settings."""

    constant_time: ConstantTimeConfig = Field(default_factory=ConstantTimeConfig)
    side_channel: SideChannelConfig = Field(default_factory=SideChannelConfig)
    entropy_analysis: EntropyAnalysisConfig = Field(default_factory=EntropyAnalysisConfig)
    fips_compliance: FIPSComplianceConfig = Field(default_factory=FIPSComplianceConfig)
    ntt_validation: NTTValidationConfig = Field(default_factory=NTTValidationConfig)


class TimingConfig(BaseModel):
    """Static timing analysis configuration."""

    tool: TimingTool = TimingTool.OPENSTA
    clock_period: float = Field(default=10.0, description="Target clock period in nanoseconds")
    sdc_files: list[str] = Field(default_factory=list, description="Additional SDC constraint files")


class PowerConfig(BaseModel):
    """Power analysis configuration."""

    tool: PowerTool = PowerTool.OPENROAD
    activity_file: str | None = Field(default=None, description="SAIF / VCD activity file path")
    corner: str = "typical"


class CIConfig(BaseModel):
    """Continuous integration settings."""

    github_actions: bool = True
    on_push: bool = True
    on_pr: bool = True
    nightly: bool = False
    extra_steps: list[str] = Field(default_factory=list, description="Additional CI step references")


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------

class VerificationConfig(BaseModel):
    """Verification settings grouped under the ``verification:`` key."""

    simulation: SimulationConfig | None = None
    formal: FormalConfig | None = None
    crypto_verification: CryptoVerificationConfig | None = None


class AnalysisConfig(BaseModel):
    """Analysis settings grouped under the ``analysis:`` key."""

    timing: TimingConfig | None = None
    power: PowerConfig | None = None


class OpenForgeConfig(BaseModel):
    """Root configuration model parsed from ``openforge.yaml``."""

    model_config = {"extra": "allow"}

    project: ProjectConfig = Field(default_factory=ProjectConfig)
    design: DesignConfig = Field(default_factory=DesignConfig)

    # Grouped keys (from openforge.yaml structure)
    verification: VerificationConfig | None = None
    analysis: AnalysisConfig | None = None
    ci_integration: CIConfig | None = None

    # Also accept flat keys for convenience
    simulation: SimulationConfig | None = None
    formal: FormalConfig | None = None
    crypto: CryptoVerificationConfig | None = None
    timing: TimingConfig | None = None
    power: PowerConfig | None = None
    ci: CIConfig | None = None
