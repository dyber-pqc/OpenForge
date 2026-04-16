"""Hold-time fix engine.

Given an STA report parsed by :mod:`openforge.physical.sta_parser`, this
module enumerates hold violations, proposes buffer-chain fixes on the
data path, and can also suggest useful-skew clock shifts as an alternate
remediation.  The output is an :class:`openforge.physical.eco.EcoScript`
that the existing ECO engine applies through OpenROAD / Innovus.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from openforge.format.def_parser import DefDesign, parse_def
from openforge.format.lef_parser import LefLibrary, parse_lef

if TYPE_CHECKING:  # pragma: no cover
    from openforge.physical.eco import EcoScript
    from openforge.physical.sta_parser import StaReport, TimingPath


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class HoldFixSuggestion(BaseModel):
    """A single proposed hold-fix on one violating path."""

    model_config = ConfigDict(extra="ignore")

    path: str  # "startpoint -> endpoint"
    src_flop: str
    dst_flop: str
    slack_ns: float
    delay_needed_ns: float
    buffers_needed: int
    buffer_cell: str = "sky130_fd_sc_hd__buf_1"
    insertion_points: list[tuple[str, str]] = Field(default_factory=list)
    # list of (net_name, near_pin)
    estimated_area_overhead_um2: float = 0.0
    notes: str = ""


class UsefulSkewSuggestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    endpoint: str
    clock: str
    delta_ns: float
    notes: str = ""


# ---------------------------------------------------------------------------
# Fixer
# ---------------------------------------------------------------------------


class HoldFixer:
    """Suggest buffer-chain hold fixes from an STA report."""

    def __init__(
        self,
        sta_report: StaReport,
        def_path: str | Path | None = None,
        lef_path: str | Path | None = None,
        buffer_cell: str = "sky130_fd_sc_hd__buf_1",
        buffer_area_um2: float = 1.38 * 2.72,
    ) -> None:
        self.report = sta_report
        self.def_path = Path(def_path) if def_path else None
        self.lef_path = Path(lef_path) if lef_path else None
        self.buffer_cell = buffer_cell
        self.buffer_area_um2 = buffer_area_um2
        self._design: DefDesign | None = None
        self._lib: LefLibrary | None = None
        self._suggestions: list[HoldFixSuggestion] = []

    # ---------------------------------------------------------------- load

    def _load_physical(self) -> tuple[DefDesign | None, LefLibrary | None]:
        if self.def_path and self._design is None:
            self._design = parse_def(self.def_path)
        if self.lef_path and self._lib is None:
            self._lib = parse_lef(self.lef_path)
        return self._design, self._lib

    # ---------------------------------------------------------------- api

    def find_violations(self) -> list[dict]:
        out: list[dict] = []
        for path in self.report.hold_paths():
            if path.slack_ns >= 0:
                continue
            out.append(
                {
                    "startpoint": path.startpoint,
                    "endpoint": path.endpoint,
                    "slack_ns": path.slack_ns,
                    "clock": path.endpoint_clock or path.startpoint_clock,
                    "levels": path.num_levels,
                }
            )
        # Fall-back: any path with check_type hold
        if not out:
            for path in self.report.paths:
                if path.check_type == "hold" and path.slack_ns < 0:
                    out.append(
                        {
                            "startpoint": path.startpoint,
                            "endpoint": path.endpoint,
                            "slack_ns": path.slack_ns,
                            "clock": path.endpoint_clock or path.startpoint_clock,
                            "levels": path.num_levels,
                        }
                    )
        return out

    def suggest_fixes(self, target_buffer_delay_ps: float = 50.0) -> list[HoldFixSuggestion]:
        """Propose a buffer-chain fix for every violating hold path.

        The number of buffers required is ``ceil(|slack_ns| / buffer_delay)``.
        We place them one-per-stage on the data path nets, starting at the
        source flop and walking toward the sink until enough delay has been
        added.
        """
        self._suggestions = []
        buf_delay_ns = max(0.001, target_buffer_delay_ps / 1000.0)
        paths: list[TimingPath] = [
            p
            for p in self.report.paths
            if p.slack_ns < 0 and (p.path_type == "min" or p.check_type == "hold")
        ]
        for path in paths:
            delay_needed = -path.slack_ns  # positive ns
            n_buffers = max(1, int(delay_needed / buf_delay_ns) + 1)
            insertion: list[tuple[str, str]] = []
            # Walk data path stages to discover candidate nets.
            for stage in path.data_path:
                pin = getattr(stage, "pin", "") or getattr(stage, "cell_instance", "")
                net_name = getattr(stage, "net", "") or pin
                if net_name:
                    insertion.append((str(net_name), str(pin)))
                if len(insertion) >= n_buffers:
                    break
            if not insertion:
                # fall back: insert at endpoint net
                insertion = [(path.endpoint, path.endpoint)]
                while len(insertion) < n_buffers:
                    insertion.append(insertion[-1])
            self._suggestions.append(
                HoldFixSuggestion(
                    path=f"{path.startpoint} -> {path.endpoint}",
                    src_flop=path.startpoint,
                    dst_flop=path.endpoint,
                    slack_ns=path.slack_ns,
                    delay_needed_ns=delay_needed,
                    buffers_needed=n_buffers,
                    buffer_cell=self.buffer_cell,
                    insertion_points=insertion[:n_buffers],
                    estimated_area_overhead_um2=n_buffers * self.buffer_area_um2,
                    notes=(
                        f"Add {n_buffers} × {self.buffer_cell} (≈{buf_delay_ns * n_buffers:.2f} ns)"
                    ),
                )
            )
        return list(self._suggestions)

    def useful_skew_for_hold(self) -> list[UsefulSkewSuggestion]:
        """Identify clock-skew adjustments that fix hold without buffers."""
        out: list[UsefulSkewSuggestion] = []
        for path in self.report.paths:
            if path.slack_ns >= 0:
                continue
            if path.path_type != "min" and path.check_type != "hold":
                continue
            # Advance the capture clock by |slack| + margin to move the
            # required time earlier (relative to the data arrival).
            delta = -path.slack_ns + 0.02
            out.append(
                UsefulSkewSuggestion(
                    endpoint=path.endpoint,
                    clock=path.endpoint_clock or "clk",
                    delta_ns=-delta,  # negative: advance capture
                    notes=(
                        f"Advance capture clock of {path.endpoint} by {delta:.3f} ns to clear hold"
                    ),
                )
            )
        return out

    def suggestions(self) -> list[HoldFixSuggestion]:
        return list(self._suggestions)

    def to_eco_script(self) -> EcoScript:
        from openforge.physical.eco import EcoCommand, EcoCommandKind, EcoScript

        script = EcoScript(metadata={"source": "hold_fixer"})
        if not self._suggestions:
            self.suggest_fixes()
        for sug in self._suggestions:
            for idx, (net, pin) in enumerate(sug.insertion_points[: sug.buffers_needed]):
                script.commands.append(
                    EcoCommand(
                        kind=EcoCommandKind.ADD_BUFFER,
                        net=net,
                        buffer_cell=sug.buffer_cell,
                        slack_before_ns=sug.slack_ns,
                        slack_after_ns=sug.slack_ns + sug.delay_needed_ns,
                        notes=(f"hold fix {idx + 1}/{sug.buffers_needed} on {sug.path} near {pin}"),
                    )
                )
        return script


__all__ = [
    "HoldFixSuggestion",
    "UsefulSkewSuggestion",
    "HoldFixer",
]
