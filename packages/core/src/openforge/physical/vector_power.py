"""Vector-based (VCD-driven) power analysis.

Reads switching activity from a VCD file, combines it with cell coordinates
from a DEF, and uses Liberty power numbers (when available) to compute
per-cell switching / internal / leakage power, an instantaneous power
time series and a power density grid.

This is *not* a sign-off-grade power engine - it is a deterministic,
fast vector-based estimator in the spirit of PrimePower / XPower that
runs entirely in-process with no external tools.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from pydantic import BaseModel, Field

from openforge.format.def_parser import DefDesign, parse_def
from openforge.format.waveform import Waveform

try:  # liberty parser is optional
    from openforge.pdk.liberty_parser import LibertyLibrary, parse_liberty
except Exception:  # pragma: no cover - liberty is best-effort
    LibertyLibrary = None  # type: ignore[assignment,misc]
    parse_liberty = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# Defaults for cells when no Liberty is available
# ---------------------------------------------------------------------------

# Default leakage power (uW) for generic cell kinds at nominal VDD.
_DEFAULT_LEAKAGE_UW = {
    "FILL": 0.0001,
    "TAP": 0.0002,
    "BUF": 0.02,
    "INV": 0.015,
    "AND": 0.03,
    "OR": 0.03,
    "NAND": 0.025,
    "NOR": 0.025,
    "XOR": 0.05,
    "DFF": 0.15,
    "DFFR": 0.16,
    "LATCH": 0.08,
    "MUX": 0.04,
    "OAI": 0.03,
    "AOI": 0.03,
    "MACRO": 2.5,
    "DEFAULT": 0.03,
}
# Default internal-power factor in fJ per toggle (very rough).
_DEFAULT_INTERNAL_FJ = {
    "BUF": 0.8,
    "INV": 0.6,
    "AND": 1.1,
    "OR": 1.1,
    "NAND": 1.0,
    "NOR": 1.0,
    "XOR": 1.5,
    "DFF": 4.0,
    "DFFR": 4.2,
    "LATCH": 2.5,
    "MUX": 1.8,
    "MACRO": 50.0,
    "DEFAULT": 1.0,
}
# Default pin capacitance (fF) for output pin when unknown
_DEFAULT_OUTPUT_CAP_FF = 1.5
_DEFAULT_VDD = 0.9


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class CellPowerSample(BaseModel):
    instance: str
    cell_type: str
    switching_power_uw: float = 0.0
    internal_power_uw: float = 0.0
    leakage_power_uw: float = 0.0
    total_power_uw: float = 0.0
    x_um: float = 0.0
    y_um: float = 0.0


class VectorPowerResult(BaseModel):
    vcd_path: str
    duration_ns: float
    total_dynamic_power_mw: float
    total_leakage_power_mw: float
    total_power_mw: float
    cell_breakdown: list[CellPowerSample] = Field(default_factory=list)
    instantaneous: list[tuple[float, float]] = Field(default_factory=list)
    peak_power_mw: float = 0.0
    peak_time_ns: float = 0.0
    num_nets: int = 0
    num_cells: int = 0


# ---------------------------------------------------------------------------
# Cell-type classifier
# ---------------------------------------------------------------------------


def _classify_cell(cell_type: str) -> str:
    n = cell_type.upper()
    if "FILL" in n:
        return "FILL"
    if "TAP" in n:
        return "TAP"
    if n.startswith("DFFR") or "DFFR" in n:
        return "DFFR"
    if n.startswith("DFF") or "FLOP" in n or "FF_" in n:
        return "DFF"
    if "LATCH" in n:
        return "LATCH"
    if "MUX" in n:
        return "MUX"
    if "XOR" in n or "XNOR" in n:
        return "XOR"
    if "NAND" in n:
        return "NAND"
    if "NOR" in n:
        return "NOR"
    if n.startswith("AND") or "_AND" in n:
        return "AND"
    if n.startswith("OR") or "_OR" in n:
        return "OR"
    if "BUF" in n:
        return "BUF"
    if n.startswith("INV") or "_INV" in n or "NOT" in n:
        return "INV"
    if "OAI" in n:
        return "OAI"
    if "AOI" in n:
        return "AOI"
    return "DEFAULT"


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class VectorPowerAnalyzer:
    """Compute power from VCD activity + cell coordinates + optional Liberty.

    Parameters
    ----------
    vcd_path : Path
        Switching activity source.
    def_path : Path
        Placed DEF for cell locations and cell types.
    lef_path : Path
        LEF is accepted for API symmetry but not strictly required for the
        estimator (cell areas come from DEF/LEF abstracts if available).
    lib_path : Path | None
        Optional Liberty file for more accurate leakage / internal numbers.
    vdd : float
        Supply voltage used for 0.5 * C * V^2 switching.
    """

    def __init__(
        self,
        vcd_path: Path,
        def_path: Path,
        lef_path: Path,
        lib_path: Path | None = None,
        vdd: float = _DEFAULT_VDD,
    ) -> None:
        self.vcd_path = Path(vcd_path)
        self.def_path = Path(def_path)
        self.lef_path = Path(lef_path)
        self.lib_path = Path(lib_path) if lib_path else None
        self.vdd = float(vdd)

        self._waveform: Optional[Waveform] = None
        self._design: Optional[DefDesign] = None
        self._liberty: Optional["LibertyLibrary"] = None

    # ------------------------------------------------------------------
    # Lazy loaders
    # ------------------------------------------------------------------

    def _load_waveform(self) -> Waveform:
        if self._waveform is None:
            self._waveform = Waveform.parse_vcd(self.vcd_path)
        return self._waveform

    def _load_def(self) -> DefDesign:
        if self._design is None:
            self._design = parse_def(self.def_path)
        return self._design

    def _load_liberty(self) -> Optional["LibertyLibrary"]:
        if self._liberty is None and self.lib_path and parse_liberty is not None:
            try:
                self._liberty = parse_liberty(self.lib_path)
            except Exception:
                self._liberty = None
        return self._liberty

    # ------------------------------------------------------------------
    # Activity analysis
    # ------------------------------------------------------------------

    def parse_activity(self) -> dict[str, float]:
        """Per-signal switching activity in toggles per ns.

        Returns a dict keyed by the canonical ``full_path`` of each signal.
        """
        wf = self._load_waveform()
        duration_ps = max(1, wf.end_time) * wf.timescale_ps
        duration_ns = duration_ps / 1000.0
        if duration_ns <= 0:
            duration_ns = 1.0

        activity: dict[str, float] = {}
        for name, signal in wf.signals.items():
            transitions = wf.data.get(signal.vcd_id) or wf.data.get(name) or []
            toggles = 0
            last: int | str | None = None
            for tr in transitions:
                v = tr.value
                if last is not None and v != last:
                    toggles += 1
                last = v
            activity[signal.full_path] = toggles / duration_ns
        return activity

    # ------------------------------------------------------------------
    # Per-cell breakdown
    # ------------------------------------------------------------------

    def _leakage_for(self, cell_type: str) -> float:
        lib = self._load_liberty()
        if lib is not None:
            cell = lib.cells.get(cell_type)
            if cell is not None and cell.leakage_power:
                # Liberty leakage is typically nW -> convert to uW
                return float(cell.leakage_power) / 1000.0
        return _DEFAULT_LEAKAGE_UW.get(_classify_cell(cell_type), _DEFAULT_LEAKAGE_UW["DEFAULT"])

    def _internal_fj_for(self, cell_type: str) -> float:
        return _DEFAULT_INTERNAL_FJ.get(
            _classify_cell(cell_type), _DEFAULT_INTERNAL_FJ["DEFAULT"]
        )

    def _output_cap_ff_for(self, cell_type: str) -> float:
        lib = self._load_liberty()
        if lib is not None:
            cell = lib.cells.get(cell_type)
            if cell is not None:
                for pin in cell.pins.values():
                    if pin.direction == "output" and pin.max_capacitance > 0:
                        return float(pin.max_capacitance) * 1000.0  # pF -> fF
        return _DEFAULT_OUTPUT_CAP_FF

    def compute_per_cell(self) -> list[CellPowerSample]:
        """Return per-instance power samples sorted high-to-low."""
        design = self._load_def()
        activity = self.parse_activity()

        # Build a lookup from short instance name -> average activity.
        # VCD full_path usually begins with the top-level module; we match
        # by suffix so "top.counter_inst.q" maps to "counter_inst".
        short_to_activity: dict[str, float] = {}
        for full_path, toggle_per_ns in activity.items():
            parts = full_path.split(".")
            for depth in range(1, len(parts) + 1):
                key = ".".join(parts[-depth:])
                # Accumulate max across matching suffixes
                if toggle_per_ns > short_to_activity.get(key, 0.0):
                    short_to_activity[key] = toggle_per_ns

        def _activity_for_instance(inst: str) -> float:
            # Try progressively shorter suffixes
            if inst in short_to_activity:
                return short_to_activity[inst]
            parts = inst.split("/")
            for depth in range(1, len(parts) + 1):
                key = ".".join(parts[-depth:])
                if key in short_to_activity:
                    return short_to_activity[key]
            # fallback: nominal low activity (0.05 tog/ns) so leakage dominates
            return 0.05

        samples: list[CellPowerSample] = []
        v2 = self.vdd * self.vdd

        for comp in design.components.values() if isinstance(design.components, dict) else design.components:
            # DefDesign.components may be dict or list depending on parser
            if isinstance(comp, str):  # shouldn't happen, defensive
                continue
            cell_type = getattr(comp, "macro", "") or getattr(comp, "cell", "") or ""
            inst = getattr(comp, "name", "") or ""
            if not cell_type:
                continue
            kind = _classify_cell(cell_type)

            act = _activity_for_instance(inst)  # toggles per ns

            cap_ff = self._output_cap_ff_for(cell_type)
            # switching: 0.5 * C * V^2 * f  -> energy per toggle * toggles/s
            # cap_ff * 1e-15 F, V^2, toggles/s = act * 1e9
            switching_uw = 0.5 * cap_ff * 1e-15 * v2 * (act * 1e9) * 1e6
            internal_uw = self._internal_fj_for(cell_type) * 1e-15 * (act * 1e9) * 1e6
            leakage_uw = self._leakage_for(cell_type)
            if kind in ("FILL", "TAP"):
                switching_uw = 0.0
                internal_uw = 0.0
            total_uw = switching_uw + internal_uw + leakage_uw

            # Location (best-effort, DEF uses DB units; convert to um)
            x_db = getattr(comp, "x", 0) or 0
            y_db = getattr(comp, "y", 0) or 0
            try:
                x_um = float(design.to_um(x_db))
                y_um = float(design.to_um(y_db))
            except Exception:
                x_um = float(x_db)
                y_um = float(y_db)

            samples.append(
                CellPowerSample(
                    instance=inst,
                    cell_type=cell_type,
                    switching_power_uw=switching_uw,
                    internal_power_uw=internal_uw,
                    leakage_power_uw=leakage_uw,
                    total_power_uw=total_uw,
                    x_um=x_um,
                    y_um=y_um,
                )
            )

        samples.sort(key=lambda s: s.total_power_uw, reverse=True)
        return samples

    # ------------------------------------------------------------------
    # Time-domain
    # ------------------------------------------------------------------

    def compute_instantaneous(
        self, timestep_ns: float = 0.1
    ) -> list[tuple[float, float]]:
        """Compute instantaneous power in mW at each ``timestep_ns`` bucket.

        Algorithm: build a histogram of all VCD transitions, weight each
        transition by the average energy-per-toggle for the design, add
        the constant leakage floor, and convert to mW.
        """
        wf = self._load_waveform()
        duration_ps = max(1, wf.end_time) * wf.timescale_ps
        duration_ns = duration_ps / 1000.0
        if duration_ns <= 0.0:
            return []

        samples = self.compute_per_cell()
        total_dyn_mw = sum(
            (s.switching_power_uw + s.internal_power_uw) for s in samples
        ) / 1000.0
        total_leak_mw = sum(s.leakage_power_uw for s in samples) / 1000.0
        total_toggles = 0
        # Average energy per toggle (mJ per toggle) derived from aggregate
        # dynamic power and total toggles observed in the VCD.
        all_transitions: list[float] = []
        for signal in wf.signals.values():
            tr = wf.data.get(signal.vcd_id) or wf.data.get(signal.full_path) or []
            last: int | str | None = None
            for t in tr:
                if last is not None and t.value != last:
                    time_ns = (t.time * wf.timescale_ps) / 1000.0
                    all_transitions.append(time_ns)
                last = t.value
            total_toggles += max(0, len(tr) - 1)

        if not all_transitions or total_toggles == 0:
            # No activity; return flat leakage trace
            n = max(1, int(duration_ns / max(timestep_ns, 1e-6)))
            return [
                (i * timestep_ns, total_leak_mw) for i in range(n)
            ]

        # mJ / toggle (average)
        # dynamic power (mW) = energy_per_toggle(mJ) * toggles/sec
        # => energy_per_toggle = dyn_mw / (toggles / duration_sec)
        duration_s = duration_ns * 1e-9
        toggles_per_s = total_toggles / max(duration_s, 1e-18)
        if toggles_per_s <= 0:
            energy_per_toggle_mj = 0.0
        else:
            energy_per_toggle_mj = total_dyn_mw / toggles_per_s  # mJ per toggle

        bins = max(1, int(round(duration_ns / max(timestep_ns, 1e-6))))
        hist, edges = np.histogram(
            all_transitions, bins=bins, range=(0.0, duration_ns)
        )
        # Per-bin dynamic power: toggles_in_bin * energy_per_toggle_mj / bin_seconds
        bin_s = timestep_ns * 1e-9
        dyn_trace_mw = (hist * energy_per_toggle_mj) / max(bin_s, 1e-18)
        total_trace = dyn_trace_mw + total_leak_mw

        out: list[tuple[float, float]] = []
        for i, pwr in enumerate(total_trace):
            t = float(edges[i])
            out.append((t, float(pwr)))
        return out

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def hot_cells(self, top_n: int = 50) -> list[CellPowerSample]:
        return self.compute_per_cell()[: max(0, int(top_n))]

    def power_density_grid(self, grid_size_um: float = 10.0) -> dict:
        """Return a 2-D power density grid (uW/um^2).

        Structure::

            {
              "extent": (xmin, xmax, ymin, ymax),  # in um
              "grid_um": grid_size_um,
              "nx": int,
              "ny": int,
              "grid": list[list[float]],  # row-major, uW/um^2
              "max_uw_per_um2": float,
            }
        """
        samples = self.compute_per_cell()
        design = self._load_def()
        try:
            xmin = 0.0
            ymin = 0.0
            xmax = float(design.width_um)
            ymax = float(design.height_um)
        except Exception:
            xs = [s.x_um for s in samples] or [0.0, 1.0]
            ys = [s.y_um for s in samples] or [0.0, 1.0]
            xmin, xmax = min(xs), max(xs)
            ymin, ymax = min(ys), max(ys)
        if xmax <= xmin:
            xmax = xmin + 1.0
        if ymax <= ymin:
            ymax = ymin + 1.0

        nx = max(1, int(np.ceil((xmax - xmin) / grid_size_um)))
        ny = max(1, int(np.ceil((ymax - ymin) / grid_size_um)))
        grid = np.zeros((ny, nx), dtype=float)

        cell_area_um2 = grid_size_um * grid_size_um
        for s in samples:
            col = int((s.x_um - xmin) / grid_size_um)
            row = int((s.y_um - ymin) / grid_size_um)
            if 0 <= col < nx and 0 <= row < ny:
                grid[row, col] += s.total_power_uw
        grid_density = grid / max(cell_area_um2, 1e-9)

        return {
            "extent": (xmin, xmax, ymin, ymax),
            "grid_um": grid_size_um,
            "nx": nx,
            "ny": ny,
            "grid": grid_density.tolist(),
            "max_uw_per_um2": float(grid_density.max() if grid_density.size else 0.0),
        }

    # ------------------------------------------------------------------
    # End-to-end
    # ------------------------------------------------------------------

    def run(self, timestep_ns: float = 0.1) -> VectorPowerResult:
        samples = self.compute_per_cell()
        inst = self.compute_instantaneous(timestep_ns=timestep_ns)
        wf = self._load_waveform()
        duration_ns = (max(1, wf.end_time) * wf.timescale_ps) / 1000.0

        dyn_mw = sum(s.switching_power_uw + s.internal_power_uw for s in samples) / 1000.0
        leak_mw = sum(s.leakage_power_uw for s in samples) / 1000.0
        total_mw = dyn_mw + leak_mw

        peak_mw = 0.0
        peak_t = 0.0
        for t, p in inst:
            if p > peak_mw:
                peak_mw = p
                peak_t = t

        return VectorPowerResult(
            vcd_path=str(self.vcd_path),
            duration_ns=duration_ns,
            total_dynamic_power_mw=dyn_mw,
            total_leakage_power_mw=leak_mw,
            total_power_mw=total_mw,
            cell_breakdown=samples,
            instantaneous=inst,
            peak_power_mw=peak_mw,
            peak_time_ns=peak_t,
            num_nets=len(wf.signals),
            num_cells=len(samples),
        )


__all__ = [
    "CellPowerSample",
    "VectorPowerResult",
    "VectorPowerAnalyzer",
]
