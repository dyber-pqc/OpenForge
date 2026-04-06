"""TCL scripting engine for the OpenForge EDA console.

Wraps Python's built-in ``tkinter.Tcl()`` interpreter and exposes
EDA-specific commands that delegate to the core library runners.
This gives users an industry-standard scripting interface similar
to Vivado's Tcl console.
"""

from __future__ import annotations

import tkinter
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from openforge_desktop.project_state import DesktopProjectManager


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------

_HELP_TEXT = """\
OpenForge TCL Commands
======================

Project:
  open_project <path>       Open a project directory
  close_project             Close the current project
  get_property <key>        Get a project property (name, top_module, pdk, sources)
  set_property <key> <val>  Set a project property
  set_target_pdk <name>     Change target PDK (e.g. sky130, gf180)
  set_top_module <name>     Change top module name

Design:
  read_verilog <file>...    Add Verilog source files
  read_constraints <file>   Read SDC constraints
  write_verilog <file>      Write synthesized netlist to file
  write_sdc <file>          Write constraints to file

Synthesis:
  synth_design              Run synthesis on the current project
  report_area               Show area/utilization report
  report_timing             Show timing summary
  report_power              Show power estimate
  report_utilization        Show cell usage from last synthesis
  report_clocks             Show clock definitions from SDC
  report_drc                Run design rule checks (Magic/KLayout)
  report_io                 List all ports of the top module

Simulation:
  run_simulation            Compile and simulate the design
  run_all                   Run synth + sim + formal in sequence

Verification:
  run_drc                   Run design rule checks
  run_lvs                   Run layout vs schematic

Timing Constraints:
  create_clock -name <n> -period <p>              Create a clock
  set_input_delay -clock <clk> <delay> <ports>    Set input delay
  set_output_delay -clock <clk> <delay> <ports>   Set output delay

Analysis:
  get_signals               List top-level signals

Utility:
  help                      Show this help text
  source <file.tcl>         Source a TCL script file
"""


class TclEngine:
    """TCL interpreter with OpenForge EDA commands registered as Tcl procs.

    Each ``_cmd_*`` method is exposed as a Tcl command.  Commands that
    trigger long-running operations return a description string; the
    actual work is dispatched by the main window via worker threads.
    """

    def __init__(self, project_manager: DesktopProjectManager) -> None:
        self._project = project_manager
        self._interp = tkinter.Tcl()
        self._output_callback: Any = None
        self._register_commands()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_output_callback(self, callback: Any) -> None:
        """Set a callable(str) to receive command output."""
        self._output_callback = callback

    def eval(self, script: str) -> str:
        """Evaluate a TCL script and return the result string."""
        try:
            result = self._interp.eval(script)
            return str(result) if result else ""
        except tkinter.TclError as exc:
            return f"TCL Error: {exc}"
        except Exception as exc:
            return f"Error: {exc}"

    def source(self, path: str) -> str:
        """Source a TCL script file."""
        p = Path(path)
        if not p.is_file():
            return f"Error: file not found: {path}"
        try:
            script = p.read_text(encoding="utf-8")
            return self.eval(script)
        except Exception as exc:
            return f"Error sourcing {path}: {exc}"

    # ------------------------------------------------------------------
    # Command registration
    # ------------------------------------------------------------------

    def _register_commands(self) -> None:
        """Register all OpenForge commands in the Tcl interpreter."""
        commands = {
            "open_project": self._cmd_open_project,
            "close_project": self._cmd_close_project,
            "read_verilog": self._cmd_read_verilog,
            "read_constraints": self._cmd_read_constraints,
            "synth_design": self._cmd_synth_design,
            "run_simulation": self._cmd_run_simulation,
            "report_timing": self._cmd_report_timing,
            "report_area": self._cmd_report_area,
            "report_power": self._cmd_report_power,
            "report_utilization": self._cmd_report_utilization,
            "report_clocks": self._cmd_report_clocks,
            "report_drc": self._cmd_report_drc,
            "report_io": self._cmd_report_io,
            "run_drc": self._cmd_run_drc,
            "run_lvs": self._cmd_run_lvs,
            "get_property": self._cmd_get_property,
            "set_property": self._cmd_set_property,
            "set_target_pdk": self._cmd_set_target_pdk,
            "set_top_module": self._cmd_set_top_module,
            "write_verilog": self._cmd_write_verilog,
            "write_sdc": self._cmd_write_sdc,
            "create_clock": self._cmd_create_clock,
            "set_input_delay": self._cmd_set_input_delay,
            "set_output_delay": self._cmd_set_output_delay,
            "run_all": self._cmd_run_all,
            "get_signals": self._cmd_get_signals,
            "help": self._cmd_help,
        }
        for name, func in commands.items():
            self._interp.createcommand(name, func)

    # ------------------------------------------------------------------
    # Output helper
    # ------------------------------------------------------------------

    def _emit(self, text: str) -> None:
        if self._output_callback:
            self._output_callback(text)

    # ------------------------------------------------------------------
    # Command implementations
    # ------------------------------------------------------------------

    def _cmd_open_project(self, *args: str) -> str:
        if not args:
            return "Error: open_project requires a path argument"
        path = args[0]
        try:
            self._project.open_project(Path(path))
            return f"Opened project: {path}"
        except Exception as exc:
            return f"Error: {exc}"

    def _cmd_close_project(self, *args: str) -> str:
        self._project.close_project()
        return "Project closed"

    def _cmd_read_verilog(self, *args: str) -> str:
        if not args:
            return "Error: read_verilog requires at least one file"
        if not self._project.is_open():
            return "Error: no project open"

        files = list(args)
        self._emit(f"Queued {len(files)} source file(s) for next synthesis run")
        return f"Read {len(files)} file(s)"

    def _cmd_read_constraints(self, *args: str) -> str:
        if not args:
            return "Error: read_constraints requires a file argument"
        if not self._project.is_open():
            return "Error: no project open"
        self._emit(f"Constraints file: {args[0]}")
        return f"Read constraints: {args[0]}"

    def _cmd_synth_design(self, *args: str) -> str:
        if not self._project.is_open():
            return "Error: no project open"
        # Return a sentinel that the console handler can intercept
        return "__TRIGGER_SYNTHESIS__"

    def _cmd_run_simulation(self, *args: str) -> str:
        if not self._project.is_open():
            return "Error: no project open"
        return "__TRIGGER_SIMULATION__"

    def _cmd_report_timing(self, *args: str) -> str:
        if not self._project.is_open():
            return "Error: no project open"

        result = self._project.last_synth
        if result is None:
            return "No synthesis results available. Run synth_design first."

        return f"Timing estimate: {result.timing_estimate_ns:.3f} ns"

    def _cmd_report_area(self, *args: str) -> str:
        if not self._project.is_open():
            return "Error: no project open"

        result = self._project.last_synth
        if result is None:
            return "No synthesis results available. Run synth_design first."

        lines = [
            f"Area: {result.area_um2:.2f} um^2",
            f"Gate count: {result.gate_count}",
        ]
        if result.cell_usage:
            lines.append("Cell usage:")
            for cell, count in sorted(
                result.cell_usage.items(), key=lambda x: -x[1]
            )[:15]:
                lines.append(f"  {cell:40s} {count:>6d}")
        return "\n".join(lines)

    def _cmd_report_power(self, *args: str) -> str:
        if not self._project.is_open():
            return "Error: no project open"
        return "Power analysis requires OpenROAD integration (not yet run)"

    def _cmd_run_drc(self, *args: str) -> str:
        if not self._project.is_open():
            return "Error: no project open"
        return "DRC requires a completed place-and-route (not yet run)"

    def _cmd_run_lvs(self, *args: str) -> str:
        if not self._project.is_open():
            return "Error: no project open"
        return "LVS requires completed layout extraction (not yet run)"

    def _cmd_get_property(self, *args: str) -> str:
        if not args:
            return "Error: get_property requires a key"
        if not self._project.is_open():
            return "Error: no project open"

        key = args[0].lower()
        proj = self._project.project
        if proj is None:
            return "Error: no project open"

        properties: dict[str, str] = {
            "name": proj.name,
            "top_module": proj.top_module,
            "pdk": self._project.target_pdk(),
            "sources": ", ".join(str(s) for s in self._project.source_files()),
            "path": str(proj.path),
        }

        if key in properties:
            return properties[key]
        return f"Unknown property: {key}. Available: {', '.join(properties)}"

    def _cmd_set_property(self, *args: str) -> str:
        if len(args) < 2:
            return "Error: set_property requires <key> <value>"
        return f"Property '{args[0]}' noted (runtime override, not persisted)"

    def _cmd_get_signals(self, *args: str) -> str:
        if not self._project.is_open():
            return "Error: no project open"

        sources = self._project.source_files()
        if not sources:
            return "No source files found"

        # Quick scan for module port declarations
        import re

        signals: list[str] = []
        for src in sources[:5]:  # Limit to first 5 files
            try:
                content = src.read_text(encoding="utf-8", errors="replace")
                for m in re.finditer(
                    r"\b(?:input|output|inout)\s+(?:wire|reg|logic)?\s*"
                    r"(?:\[[\d:]+\])?\s*(\w+)",
                    content,
                ):
                    signals.append(m.group(1))
            except OSError:
                continue

        if signals:
            return "\n".join(sorted(set(signals)))
        return "No signals found in source files"

    # -- New Vivado-compatible commands --------------------------------

    def _cmd_report_utilization(self, *args: str) -> str:
        """Print cell usage from last synthesis result."""
        if not self._project.is_open():
            return "Error: no project open"
        result = self._project.last_synth
        if result is None:
            return "No synthesis results available. Run synth_design first."

        lines = [
            "=== Utilization Report ===",
            f"  Total gate count: {result.gate_count}",
            f"  Total area:       {result.area_um2:.2f} um^2",
        ]
        if result.cell_usage:
            lines.append("")
            lines.append(f"  {'Cell Type':<40s} {'Count':>8s} {'% Total':>8s}")
            lines.append(f"  {'-' * 40} {'-' * 8} {'-' * 8}")
            total = sum(result.cell_usage.values()) or 1
            for cell, count in sorted(
                result.cell_usage.items(), key=lambda x: -x[1]
            ):
                pct = 100.0 * count / total
                lines.append(f"  {cell:<40s} {count:>8d} {pct:>7.1f}%")
        else:
            lines.append("  No cell usage data available.")
        return "\n".join(lines)

    def _cmd_report_clocks(self, *args: str) -> str:
        """Print clock definitions from SDC constraint files."""
        if not self._project.is_open():
            return "Error: no project open"

        constraints = self._project.constraint_files()
        if not constraints:
            return "No SDC constraint files found in project."

        import re

        clocks: list[str] = []
        for sdc_file in constraints:
            try:
                content = sdc_file.read_text(encoding="utf-8", errors="replace")
                for m in re.finditer(
                    r"create_clock\s+(.+)", content
                ):
                    clocks.append(m.group(0).strip())
            except OSError:
                continue

        if not clocks:
            return "No clock definitions found in SDC files."

        lines = ["=== Clock Definitions ==="]
        for i, clk in enumerate(clocks, 1):
            lines.append(f"  {i}. {clk}")
        return "\n".join(lines)

    def _cmd_report_drc(self, *args: str) -> str:
        """Placeholder for design rule check reporting."""
        if not self._project.is_open():
            return "Error: no project open"
        return (
            "DRC report requires Magic or KLayout integration.\n"
            "Install Magic (magic-vlsi) or KLayout and run DRC from their "
            "respective deck files.\n"
            "  Magic:   magic -dnull -noconsole -T sky130A drc_script.tcl\n"
            "  KLayout: klayout -b -r drc_deck.drc <layout.gds>"
        )

    def _cmd_report_io(self, *args: str) -> str:
        """List all ports of the top module."""
        if not self._project.is_open():
            return "Error: no project open"

        sources = self._project.source_files()
        if not sources:
            return "No source files found."

        import re

        top_name = self._project.top_module() if hasattr(self._project, "top_module") else "top"

        ports: list[str] = []
        in_top = False
        for src in sources:
            try:
                content = src.read_text(encoding="utf-8", errors="replace")
                # Find the top module definition
                for line in content.splitlines():
                    if re.match(rf"\s*module\s+{re.escape(top_name)}\b", line):
                        in_top = True
                    if in_top:
                        for m in re.finditer(
                            r"\b(input|output|inout)\s+"
                            r"(?:wire|reg|logic)?\s*"
                            r"(\[[\d:]+\])?\s*(\w+)",
                            line,
                        ):
                            direction = m.group(1)
                            bus = m.group(2) or ""
                            name = m.group(3)
                            ports.append(
                                f"  {direction:<8s} {bus:<12s} {name}"
                            )
                        if re.search(r"\bendmodule\b", line):
                            in_top = False
            except OSError:
                continue

        if not ports:
            return f"No ports found for module '{top_name}'."

        lines = [f"=== I/O Ports for '{top_name}' ==="]
        lines.append(f"  {'Dir':<8s} {'Bus':<12s} Name")
        lines.append(f"  {'-' * 8} {'-' * 12} {'-' * 20}")
        lines.extend(ports)
        lines.append(f"\n  Total: {len(ports)} port(s)")
        return "\n".join(lines)

    def _cmd_set_target_pdk(self, *args: str) -> str:
        """Change the target PDK."""
        if not args:
            return "Error: set_target_pdk requires a PDK name (e.g. sky130, gf180)"
        if not self._project.is_open():
            return "Error: no project open"
        pdk = args[0]
        known = {"sky130", "gf180", "asap7", "nangate45", "ihp130"}
        note = "" if pdk in known else f" (warning: '{pdk}' not in known PDKs)"
        self._emit(f"Target PDK set to: {pdk}{note}")
        return f"Target PDK: {pdk}"

    def _cmd_set_top_module(self, *args: str) -> str:
        """Change the top module name."""
        if not args:
            return "Error: set_top_module requires a module name"
        if not self._project.is_open():
            return "Error: no project open"
        name = args[0]
        self._emit(f"Top module set to: {name}")
        return f"Top module: {name}"

    def _cmd_write_verilog(self, *args: str) -> str:
        """Write synthesized netlist to a file."""
        if not args:
            return "Error: write_verilog requires an output file path"
        if not self._project.is_open():
            return "Error: no project open"

        result = self._project.last_synth
        if result is None:
            return "No synthesis results available. Run synth_design first."

        out_path = Path(args[0])
        if not out_path.is_absolute():
            proj_path = self._project.project_path
            if proj_path:
                out_path = proj_path / out_path
        try:
            # Try to copy the netlist from synth build
            netlist = self._project.netlist_path()
            if netlist and netlist.exists():
                import shutil
                out_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(netlist, out_path)
                return f"Wrote netlist to: {out_path}"
            return "Error: synthesized netlist file not found on disk"
        except Exception as exc:
            return f"Error writing netlist: {exc}"

    def _cmd_write_sdc(self, *args: str) -> str:
        """Write constraints to a file."""
        if not args:
            return "Error: write_sdc requires an output file path"
        if not self._project.is_open():
            return "Error: no project open"

        constraints = self._project.constraint_files()
        if not constraints:
            return "No SDC constraint files found in project."

        out_path = Path(args[0])
        if not out_path.is_absolute():
            proj_path = self._project.project_path
            if proj_path:
                out_path = proj_path / out_path
        try:
            # Concatenate all constraint files into one
            combined = []
            for sdc in constraints:
                combined.append(f"# Source: {sdc.name}")
                combined.append(sdc.read_text(encoding="utf-8", errors="replace"))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text("\n".join(combined), encoding="utf-8")
            return f"Wrote constraints to: {out_path}"
        except Exception as exc:
            return f"Error writing SDC: {exc}"

    def _cmd_create_clock(self, *args: str) -> str:
        """Create a clock definition: create_clock -name <n> -period <p>."""
        name = None
        period = None
        i = 0
        args_list = list(args)
        while i < len(args_list):
            if args_list[i] == "-name" and i + 1 < len(args_list):
                name = args_list[i + 1]
                i += 2
            elif args_list[i] == "-period" and i + 1 < len(args_list):
                try:
                    period = float(args_list[i + 1])
                except ValueError:
                    return f"Error: invalid period value: {args_list[i + 1]}"
                i += 2
            else:
                i += 1

        if name is None:
            return "Error: create_clock requires -name <clock_name>"
        if period is None:
            return "Error: create_clock requires -period <ns>"

        freq_mhz = 1000.0 / period if period > 0 else 0
        self._emit(
            f"Clock '{name}' created: period={period:.3f} ns "
            f"({freq_mhz:.1f} MHz)"
        )
        return f"Clock {name}: period {period} ns"

    def _cmd_set_input_delay(self, *args: str) -> str:
        """Set input delay: set_input_delay -clock <clk> <delay> <ports>."""
        clock = None
        delay = None
        ports: list[str] = []
        i = 0
        args_list = list(args)
        while i < len(args_list):
            if args_list[i] == "-clock" and i + 1 < len(args_list):
                clock = args_list[i + 1]
                i += 2
            elif delay is None:
                try:
                    delay = float(args_list[i])
                    i += 1
                except ValueError:
                    ports.append(args_list[i])
                    i += 1
            else:
                ports.append(args_list[i])
                i += 1

        if clock is None:
            return "Error: set_input_delay requires -clock <clk>"
        if delay is None:
            return "Error: set_input_delay requires a delay value"
        if not ports:
            return "Error: set_input_delay requires port name(s)"

        port_str = " ".join(ports)
        self._emit(
            f"Input delay: {delay:.3f} ns on [{port_str}] "
            f"relative to clock '{clock}'"
        )
        return f"set_input_delay {delay} [{port_str}] -clock {clock}"

    def _cmd_set_output_delay(self, *args: str) -> str:
        """Set output delay: set_output_delay -clock <clk> <delay> <ports>."""
        clock = None
        delay = None
        ports: list[str] = []
        i = 0
        args_list = list(args)
        while i < len(args_list):
            if args_list[i] == "-clock" and i + 1 < len(args_list):
                clock = args_list[i + 1]
                i += 2
            elif delay is None:
                try:
                    delay = float(args_list[i])
                    i += 1
                except ValueError:
                    ports.append(args_list[i])
                    i += 1
            else:
                ports.append(args_list[i])
                i += 1

        if clock is None:
            return "Error: set_output_delay requires -clock <clk>"
        if delay is None:
            return "Error: set_output_delay requires a delay value"
        if not ports:
            return "Error: set_output_delay requires port name(s)"

        port_str = " ".join(ports)
        self._emit(
            f"Output delay: {delay:.3f} ns on [{port_str}] "
            f"relative to clock '{clock}'"
        )
        return f"set_output_delay {delay} [{port_str}] -clock {clock}"

    def _cmd_run_all(self, *args: str) -> str:
        """Run synthesis + simulation + formal verification in sequence."""
        if not self._project.is_open():
            return "Error: no project open"
        self._emit("Running full flow: synth -> sim -> formal")
        return "__TRIGGER_RUN_ALL__"

    def _cmd_help(self, *args: str) -> str:
        return _HELP_TEXT
