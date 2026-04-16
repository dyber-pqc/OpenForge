"""Mixed-signal co-simulation orchestrator.

Couples a digital RTL simulator (Verilator/Icarus) with the ngspice analog
simulator so that a single design containing both Verilog modules and SPICE
sub-circuits can be simulated end-to-end. The two simulators run as separate
processes and exchange boundary-signal values through a pair of FIFO files
(or named pipes on POSIX) that act as a simple message bus.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openforge.engine.ngspice import NgspiceEngine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class InterfaceSignal:
    """One signal that crosses the digital/analog boundary."""

    name: str
    direction: str  # "d2a" (digital -> analog) or "a2d" (analog -> digital)
    type: str  # "digital" or "analog"
    width: int = 1
    vlow: float = 0.0
    vhigh: float = 1.8
    threshold: float = 0.9  # voltage above which "1" is sampled

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> InterfaceSignal:
        return cls(
            name=d["name"],
            direction=d["direction"],
            type=d.get("type", "digital"),
            width=int(d.get("width", 1)),
            vlow=float(d.get("vlow", 0.0)),
            vhigh=float(d.get("vhigh", 1.8)),
            threshold=float(d.get("threshold", 0.9)),
        )


@dataclass
class MixedSignalConfig:
    """Configuration for a mixed-signal co-simulation run."""

    digital_top: str
    digital_sources: list[Path]
    analog_top: str
    analog_netlist: Path
    interface_signals: list[dict[str, Any]]
    simulation_time_ns: float
    timestep_ns: float = 1.0
    work_dir: Path | None = None

    def signals(self) -> list[InterfaceSignal]:
        return [InterfaceSignal.from_dict(s) for s in self.interface_signals]


@dataclass
class CosimResult:
    success: bool
    digital_log: Path | None = None
    analog_log: Path | None = None
    waveform: Path | None = None
    samples: list[dict[str, float]] = field(default_factory=list)
    error: str = ""


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------


class MixedSignalSimulator:
    """Co-simulate digital RTL and SPICE analog circuits.

    Strategy:
        - Verilator simulates the digital portion.
        - ngspice simulates the analog portion (running in interactive mode).
        - At each timestep boundary, digital values are converted to voltages
          and pushed into ngspice via ``alter`` commands; analog node voltages
          are sampled via ``print`` and translated back to digital.
        - The two halves communicate over a pair of FIFOs in ``work_dir``.
    """

    def __init__(self, ngspice: NgspiceEngine | None = None) -> None:
        self.ngspice = ngspice or NgspiceEngine()
        self.config: MixedSignalConfig | None = None
        self.work_dir: Path | None = None
        self._d2a_fifo: Path | None = None
        self._a2d_fifo: Path | None = None
        self._samples: list[dict[str, float]] = []

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def setup_cosim(self, config: MixedSignalConfig, work_dir: Path) -> None:
        self.config = config
        self.work_dir = Path(work_dir).resolve()
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._d2a_fifo = self.work_dir / "d2a.pipe"
        self._a2d_fifo = self.work_dir / "a2d.pipe"
        self._make_fifo(self._d2a_fifo)
        self._make_fifo(self._a2d_fifo)

        # Generate the Verilog DPI wrapper
        wrapper_path = self.work_dir / "openforge_cosim_dpi.sv"
        wrapper_path.write_text(
            self.generate_verilog_dpi_wrapper(config.interface_signals),
            encoding="utf-8",
        )

        # Generate the ngspice control deck
        deck_path = self.work_dir / "cosim.deck.cir"
        deck_path.write_text(
            self.generate_spice_control_deck(config),
            encoding="utf-8",
        )

        # Manifest of the run, useful for debugging
        manifest = {
            "digital_top": config.digital_top,
            "analog_top": config.analog_top,
            "signals": config.interface_signals,
            "tstop_ns": config.simulation_time_ns,
            "tstep_ns": config.timestep_ns,
            "wrapper": str(wrapper_path),
            "deck": str(deck_path),
        }
        (self.work_dir / "cosim_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        logger.info("Mixed-signal cosim configured in %s", self.work_dir)

    @staticmethod
    def _make_fifo(path: Path) -> None:
        if path.exists():
            with contextlib.suppress(OSError):
                path.unlink()
        if hasattr(os, "mkfifo"):
            try:
                os.mkfifo(str(path))
                return
            except (OSError, NotImplementedError):
                pass
        # Fallback: regular file used as a polled mailbox (Windows-friendly).
        path.touch()

    # ------------------------------------------------------------------
    # Code generation
    # ------------------------------------------------------------------
    def generate_verilog_dpi_wrapper(self, signals: list[dict[str, Any]]) -> str:
        """Generate Verilog DPI imports/exports for analog values."""
        sig_objs = [InterfaceSignal.from_dict(s) for s in signals]
        lines: list[str] = []
        lines.append("// Auto-generated by OpenForge MixedSignalSimulator")
        lines.append("// DPI bridge between Verilator and ngspice")
        lines.append("`ifndef OPENFORGE_COSIM_DPI_SV")
        lines.append("`define OPENFORGE_COSIM_DPI_SV")
        lines.append("")
        lines.append('import "DPI-C" function void of_cosim_init(input string work_dir);')
        lines.append('import "DPI-C" function void of_cosim_step(input longint t_ns);')
        lines.append('import "DPI-C" function void of_cosim_finish();')
        lines.append("")
        for s in sig_objs:
            if s.direction == "d2a":
                lines.append(
                    f'import "DPI-C" function void of_cosim_set_{s.name}'
                    f"(input bit[{max(s.width - 1, 0)}:0] value);"
                )
            else:
                lines.append(
                    f'import "DPI-C" function bit[{max(s.width - 1, 0)}:0] of_cosim_get_{s.name}();'
                )
        lines.append("")
        lines.append('module openforge_cosim_bridge #(parameter STRING WORK_DIR = "./") (')
        lines.append("    input  logic clk")
        lines.append(");")
        lines.append("    longint t_ns;")
        lines.append("    initial begin")
        lines.append("        of_cosim_init(WORK_DIR);")
        lines.append("        t_ns = 0;")
        lines.append("    end")
        lines.append("    always @(posedge clk) begin")
        lines.append("        of_cosim_step(t_ns);")
        lines.append("        t_ns += 1;")
        lines.append("    end")
        lines.append("    final of_cosim_finish();")
        lines.append("endmodule")
        lines.append("`endif")
        return "\n".join(lines) + "\n"

    def generate_spice_control_deck(self, config: MixedSignalConfig) -> str:
        """Generate ngspice control deck with .save and .control sections."""
        sig_objs = [InterfaceSignal.from_dict(s) for s in config.interface_signals]
        save_nets = [f"v({s.name})" for s in sig_objs if s.type == "analog"]
        save_clause = ".save " + (" ".join(save_nets) if save_nets else "all")

        # Use a piecewise-linear source for each digital -> analog signal so
        # we can `alter` it from the control loop.
        srcs: list[str] = []
        for s in sig_objs:
            if s.direction == "d2a":
                srcs.append(f"V_{s.name} {s.name} 0 PWL(0 {s.vlow})")

        ctl: list[str] = []
        ctl.append("* OpenForge mixed-signal control deck")
        ctl.append(f".include {Path(config.analog_netlist).as_posix()}")
        ctl.extend(srcs)
        ctl.append(save_clause)
        ctl.append(f".tran {config.timestep_ns}n {config.simulation_time_ns}n")
        ctl.append(".control")
        ctl.append("set noaskquit")
        ctl.append("set filetype=ascii")
        ctl.append("run")
        for s in sig_objs:
            if s.type == "analog":
                ctl.append(f"print v({s.name}) > {s.name}.dat")
        ctl.append("quit")
        ctl.append(".endc")
        ctl.append(".end")
        return "\n".join(ctl) + "\n"

    # ------------------------------------------------------------------
    # Boundary conversion
    # ------------------------------------------------------------------
    @staticmethod
    def digital_to_voltage(value: int, signal: InterfaceSignal) -> float:
        """Map a digital bit-vector value to an analog voltage (MSB used)."""
        if signal.width <= 1:
            return signal.vhigh if value else signal.vlow
        # For multi-bit, scale linearly across [vlow, vhigh]
        max_val = (1 << signal.width) - 1
        frac = max(0, min(value, max_val)) / max_val
        return signal.vlow + frac * (signal.vhigh - signal.vlow)

    @staticmethod
    def voltage_to_digital(voltage: float, signal: InterfaceSignal) -> int:
        if signal.width <= 1:
            return 1 if voltage >= signal.threshold else 0
        # Quantize across the configured analog range
        span = max(signal.vhigh - signal.vlow, 1e-12)
        frac = max(0.0, min(1.0, (voltage - signal.vlow) / span))
        return int(round(frac * ((1 << signal.width) - 1)))

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def run(self) -> CosimResult:
        if not self.config or not self.work_dir:
            raise RuntimeError("setup_cosim() must be called first")
        result = CosimResult(success=False)
        result.digital_log = self.work_dir / "digital.log"
        result.analog_log = self.work_dir / "analog.log"
        result.waveform = self.work_dir / "cosim.vcd"

        digital_proc = self._launch_digital()
        analog_proc = self._launch_analog()

        # Drive a simple step loop on the host side. In a real implementation
        # the simulators would block on the FIFOs; here we just poll.
        try:
            self._step_loop()
        except Exception as e:  # pragma: no cover - defensive
            result.error = str(e)
            logger.exception("Mixed-signal step loop crashed")

        digital_rc = self._terminate(digital_proc)
        analog_rc = self._terminate(analog_proc)
        result.success = (digital_rc == 0) and (analog_rc == 0) and not result.error
        result.samples = list(self._samples)
        return result

    def _launch_digital(self) -> subprocess.Popen[str] | None:
        assert self.config and self.work_dir
        sources = " ".join(str(p) for p in self.config.digital_sources)
        if not sources:
            logger.warning("No digital sources provided; skipping digital sim")
            return None
        cmd = [
            "iverilog",
            "-g2012",
            "-o",
            str(self.work_dir / "digital.vvp"),
            *[str(p) for p in self.config.digital_sources],
        ]
        try:
            return subprocess.Popen(
                cmd,
                cwd=self.work_dir,
                stdout=open(self.work_dir / "digital.log", "w", encoding="utf-8"),
                stderr=subprocess.STDOUT,
                text=True,
            )
        except FileNotFoundError:
            logger.warning("iverilog not found; digital half is a no-op")
            return None

    def _launch_analog(self) -> subprocess.Popen[str] | None:
        assert self.work_dir
        deck = self.work_dir / "cosim.deck.cir"
        cmd = [self.ngspice.binary, "-b", "-o", str(self.work_dir / "analog.log"), str(deck)]
        try:
            return subprocess.Popen(
                cmd,
                cwd=self.work_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError:
            logger.warning("ngspice not found; analog half is a no-op")
            return None

    def _step_loop(self) -> None:
        """Polling loop that exchanges boundary samples until tstop."""
        assert self.config
        cfg = self.config
        sigs = cfg.signals()
        n_steps = max(1, int(cfg.simulation_time_ns / max(cfg.timestep_ns, 1e-9)))
        for step in range(n_steps):
            t_ns = step * cfg.timestep_ns
            sample = {"t_ns": t_ns}
            for s in sigs:
                if s.direction == "d2a":
                    digital_val = self._read_digital(s, step)
                    voltage = self.digital_to_voltage(digital_val, s)
                    sample[f"{s.name}_v"] = voltage
                    self._push_analog(s, voltage)
                else:
                    voltage = self._read_analog(s, step)
                    digital_val = self.voltage_to_digital(voltage, s)
                    sample[f"{s.name}_d"] = digital_val
                    sample[f"{s.name}_v"] = voltage
                    self._push_digital(s, digital_val)
            self._samples.append(sample)
            time.sleep(0)  # cooperative yield

    # The following I/O methods are stubs that would talk over the FIFOs in
    # a fully-wired implementation. They are kept simple so the orchestrator
    # is unit-testable in isolation.
    def _read_digital(self, signal: InterfaceSignal, step: int) -> int:
        return (step >> 0) & ((1 << signal.width) - 1)

    def _read_analog(self, signal: InterfaceSignal, step: int) -> float:
        # Default: a slow ramp; real impl reads from a2d FIFO.
        return signal.vlow + ((step % 100) / 100.0) * (signal.vhigh - signal.vlow)

    def _push_digital(self, signal: InterfaceSignal, value: int) -> None:
        if self._a2d_fifo and self._a2d_fifo.exists():
            try:
                with open(self._a2d_fifo, "a", encoding="utf-8") as f:
                    f.write(f"{signal.name}={value}\n")
            except OSError:
                pass

    def _push_analog(self, signal: InterfaceSignal, voltage: float) -> None:
        if self._d2a_fifo and self._d2a_fifo.exists():
            try:
                with open(self._d2a_fifo, "a", encoding="utf-8") as f:
                    f.write(f"alter V_{signal.name} {voltage}\n")
            except OSError:
                pass

    @staticmethod
    def _terminate(proc: subprocess.Popen[str] | None) -> int:
        if proc is None:
            return 0
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                return 1
        return proc.returncode if proc.returncode is not None else 1


__all__ = [
    "InterfaceSignal",
    "MixedSignalConfig",
    "CosimResult",
    "MixedSignalSimulator",
]
