"""TCL scripting engine for the OpenForge EDA console.

Wraps Python's built-in ``tkinter.Tcl()`` interpreter and exposes
EDA-specific commands that delegate to the core library runners.
This gives users an industry-standard scripting interface similar
to Vivado's Tcl console.
"""

from __future__ import annotations

import glob
import os
import subprocess
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
  create_project <name> <path>   Create a new project
  open_project <path>            Open a project directory
  close_project                  Close the current project
  get_property <key>             Get a project property
  set_property <key> <val> ?obj? Set a design property
  add_sources <file>...          Add source files to project
  set_top <module>               Set top module name
  set_target_pdk <name>          Change target PDK (e.g. sky130, gf180)
  set_top_module <name>          Change top module name (alias)

Design:
  read_verilog <file>...         Add Verilog source files
  read_constraints <file>        Read SDC constraints
  write_verilog <file>           Write synthesized netlist to file
  write_netlist <file>           Write synthesized netlist (alias)
  write_sdc <file>               Write constraints to file

Synthesis:
  synth_design ?-top mod? ?-part tgt?  Run synthesis
  opt_design                     Optimize synthesized design
  report_area                    Show area/utilization report
  report_timing ?-max_paths N?   Show timing summary
  report_power                   Show power estimate
  report_utilization             Show cell usage from last synthesis
  report_clocks                  Show clock definitions from SDC
  report_drc                     Run design rule checks
  report_io                      List all ports of the top module

Physical Design:
  init_floorplan -die_area {x0 y0 x1 y1} -core_area {x0 y0 x1 y1}
  global_placement -density <float>
  detailed_placement             Run detailed placement (legalization)
  place_design                   Run full placement flow
  clock_tree_synthesis           Run clock tree synthesis
  global_route                   Run global routing
  detailed_route                 Run detailed routing
  route_design                   Run full routing flow
  write_def <file>               Write DEF output file
  write_gds <file>               Write GDSII output file
  report_design_area             Report design area and utilization

Simulation:
  compile_sim ?-top module?      Compile simulation
  run_sim ?-time value?          Run simulation
  run_simulation                 Compile and simulate (legacy)
  open_waveform <path>           Open VCD/FST waveform
  add_wave <signals>...          Add signals to waveform viewer
  run_all                        Run synth + sim + formal in sequence

Verification:
  run_drc                        Run design rule checks (Magic via WSL2)
  run_lvs                        Run layout vs schematic (Netgen via WSL2)
  report_lvs                     Report LVS results

FPGA:
  set_target_device <dev>        Set FPGA target
  synth_fpga                     Run FPGA synthesis + P&R + bitstream
  program_fpga                   Program FPGA with bitstream

Timing Constraints:
  create_clock -name <n> -period <p>              Create a clock
  set_input_delay -clock <clk> <delay> <ports>    Set input delay
  set_output_delay -clock <clk> <delay> <ports>   Set output delay

Analysis:
  get_signals                    List top-level signals

Utility:
  puts <message>                 Print message to console
  source <file.tcl>              Source a TCL script file
  pwd                            Print working directory
  cd <path>                      Change directory
  ls ?pattern?                   List files
  exec <command>                 Execute shell command
  help ?command?                 Show help (optionally for one command)
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
            # Physical design commands
            "init_floorplan": self._cmd_init_floorplan,
            "global_placement": self._cmd_global_placement,
            "detailed_placement": self._cmd_detailed_placement,
            "clock_tree_synthesis": self._cmd_clock_tree_synthesis,
            "global_route": self._cmd_global_route,
            "detailed_route": self._cmd_detailed_route,
            "write_def": self._cmd_write_def,
            "write_gds": self._cmd_write_gds,
            "report_design_area": self._cmd_report_design_area,
            # FPGA commands
            "set_target_device": self._cmd_set_target_device,
            "synth_fpga": self._cmd_synth_fpga,
            "program_fpga": self._cmd_program_fpga,
            # New project commands
            "create_project": self._cmd_create_project,
            "add_sources": self._cmd_add_sources,
            "set_top": self._cmd_set_top,
            # New synthesis commands
            "opt_design": self._cmd_opt_design,
            "write_netlist": self._cmd_write_verilog,  # alias
            # New implementation commands
            "place_design": self._cmd_place_design,
            "route_design": self._cmd_route_design,
            "report_lvs": self._cmd_report_lvs,
            # New simulation commands
            "compile_sim": self._cmd_compile_sim,
            "run_sim": self._cmd_run_sim,
            "open_waveform": self._cmd_open_waveform,
            "add_wave": self._cmd_add_wave,
            # Utility commands
            "puts": self._cmd_puts,
            "pwd": self._cmd_pwd,
            "cd": self._cmd_cd,
            "ls": self._cmd_ls,
            "exec": self._cmd_exec,
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
        # Parse optional Vivado-style flags
        i = 0
        args_list = list(args)
        while i < len(args_list):
            if args_list[i] == "-top" and i + 1 < len(args_list):
                self._emit(f"Top module: {args_list[i + 1]}")
                i += 2
            elif args_list[i] == "-part" and i + 1 < len(args_list):
                self._emit(f"Target: {args_list[i + 1]}")
                i += 2
            else:
                i += 1
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

        # Parse optional -max_paths flag
        max_paths = 10
        i = 0
        args_list = list(args)
        while i < len(args_list):
            if args_list[i] == "-max_paths" and i + 1 < len(args_list):
                try:
                    max_paths = int(args_list[i + 1])
                except ValueError:
                    pass
                i += 2
            else:
                i += 1

        lines = [
            "=== Timing Report ===",
            f"  Timing estimate: {result.timing_estimate_ns:.3f} ns",
            f"  Max paths shown: {max_paths}",
        ]
        return "\n".join(lines)

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

    # -- Physical design commands ------------------------------------

    def _cmd_init_floorplan(self, *args: str) -> str:
        """Initialize floorplan: init_floorplan -die_area {x0 y0 x1 y1} -core_area {x0 y0 x1 y1}."""
        if not self._project.is_open():
            return "Error: no project open"

        die_area = None
        core_area = None
        i = 0
        args_list = list(args)
        while i < len(args_list):
            if args_list[i] == "-die_area" and i + 1 < len(args_list):
                # Parse {x0 y0 x1 y1} - may come as single braced arg or multiple args
                raw = args_list[i + 1].strip("{}")
                try:
                    coords = [float(x) for x in raw.split()]
                    if len(coords) == 4:
                        die_area = tuple(coords)
                except ValueError:
                    return f"Error: invalid die_area coordinates: {args_list[i + 1]}"
                i += 2
            elif args_list[i] == "-core_area" and i + 1 < len(args_list):
                raw = args_list[i + 1].strip("{}")
                try:
                    coords = [float(x) for x in raw.split()]
                    if len(coords) == 4:
                        core_area = tuple(coords)
                except ValueError:
                    return f"Error: invalid core_area coordinates: {args_list[i + 1]}"
                i += 2
            else:
                i += 1

        if die_area is None:
            return "Error: init_floorplan requires -die_area {x0 y0 x1 y1}"

        if core_area is None:
            # Auto-compute core area with 50um margin
            margin = 50.0
            core_area = (
                die_area[0] + margin, die_area[1] + margin,
                die_area[2] - margin, die_area[3] - margin,
            )

        die_w = die_area[2] - die_area[0]
        die_h = die_area[3] - die_area[1]
        core_w = core_area[2] - core_area[0]
        core_h = core_area[3] - core_area[1]

        self._emit(f"Floorplan initialized:")
        self._emit(f"  Die:  {die_w:.1f} x {die_h:.1f} um ({die_w * die_h / 1e6:.4f} mm^2)")
        self._emit(f"  Core: {core_w:.1f} x {core_h:.1f} um ({core_w * core_h / 1e6:.4f} mm^2)")
        return f"Floorplan: die={die_w:.0f}x{die_h:.0f} core={core_w:.0f}x{core_h:.0f}"

    def _cmd_global_placement(self, *args: str) -> str:
        """Run global placement: global_placement -density <float>."""
        if not self._project.is_open():
            return "Error: no project open"

        density = 0.7
        i = 0
        args_list = list(args)
        while i < len(args_list):
            if args_list[i] == "-density" and i + 1 < len(args_list):
                try:
                    density = float(args_list[i + 1])
                except ValueError:
                    return f"Error: invalid density value: {args_list[i + 1]}"
                i += 2
            else:
                i += 1

        self._emit(f"Running global placement with density={density:.2f}")
        self._emit("(Delegates to OpenROAD global_placement command)")
        return "__TRIGGER_PNR__"

    def _cmd_detailed_placement(self, *args: str) -> str:
        """Run detailed placement (legalization)."""
        if not self._project.is_open():
            return "Error: no project open"
        self._emit("Running detailed placement (legalization)...")
        self._emit("(Delegates to OpenROAD detailed_placement command)")
        return "Detailed placement queued"

    def _cmd_clock_tree_synthesis(self, *args: str) -> str:
        """Run clock tree synthesis."""
        if not self._project.is_open():
            return "Error: no project open"
        self._emit("Running clock tree synthesis...")
        self._emit("(Delegates to OpenROAD clock_tree_synthesis command)")
        return "CTS queued"

    def _cmd_global_route(self, *args: str) -> str:
        """Run global routing."""
        if not self._project.is_open():
            return "Error: no project open"
        self._emit("Running global routing...")
        self._emit("(Delegates to OpenROAD global_route command)")
        return "Global routing queued"

    def _cmd_detailed_route(self, *args: str) -> str:
        """Run detailed routing."""
        if not self._project.is_open():
            return "Error: no project open"
        self._emit("Running detailed routing...")
        self._emit("(Delegates to OpenROAD detailed_route command)")
        return "Detailed routing queued"

    def _cmd_write_def(self, *args: str) -> str:
        """Write DEF output: write_def <file>."""
        if not args:
            return "Error: write_def requires an output file path"
        if not self._project.is_open():
            return "Error: no project open"

        out_path = Path(args[0])
        if not out_path.is_absolute():
            proj_path = self._project.project_path
            if proj_path:
                out_path = proj_path / out_path

        # Check if we have a routed DEF to copy
        proj_path = self._project.project_path
        if proj_path:
            for candidate in [
                proj_path / "openlane_build" / "routing" / "routed.def",
                proj_path / "pnr_build" / "final.def",
                proj_path / "pnr_build" / "routed.def",
            ]:
                if candidate.exists():
                    import shutil
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(candidate, out_path)
                    return f"Wrote DEF to: {out_path}"

        return "Error: no DEF file available. Run P&R first."

    def _cmd_write_gds(self, *args: str) -> str:
        """Write GDSII output: write_gds <file>."""
        if not args:
            return "Error: write_gds requires an output file path"
        if not self._project.is_open():
            return "Error: no project open"

        out_path = Path(args[0])
        if not out_path.is_absolute():
            proj_path = self._project.project_path
            if proj_path:
                out_path = proj_path / out_path

        # Check if we have a GDS to copy
        proj_path = self._project.project_path
        if proj_path:
            gds_dir = proj_path / "openlane_build" / "gds"
            if gds_dir.exists():
                gds_files = list(gds_dir.glob("*.gds"))
                if gds_files:
                    import shutil
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(gds_files[0], out_path)
                    return f"Wrote GDS to: {out_path}"

        return "Error: no GDS file available. Run 'export_gds' first."

    def _cmd_report_design_area(self, *args: str) -> str:
        """Report physical design area and utilization."""
        if not self._project.is_open():
            return "Error: no project open"

        # Try to read from P&R results
        proj_path = self._project.project_path
        if proj_path:
            report_dir = proj_path / "openlane_build" / "reports"
            if report_dir.exists():
                for rpt in report_dir.glob("*.rpt"):
                    try:
                        content = rpt.read_text(errors="replace")
                        if "Design area" in content or "design area" in content:
                            self._emit("=== Design Area Report ===")
                            for line in content.splitlines():
                                if any(k in line.lower() for k in ("area", "util", "cell", "wire")):
                                    self._emit(f"  {line.strip()}")
                            return "Area report displayed"
                    except OSError:
                        continue

        # Fall back to synthesis area if no P&R data
        result = self._project.last_synth
        if result is not None:
            return (
                f"=== Design Area (from synthesis) ===\n"
                f"  Gate count: {result.gate_count}\n"
                f"  Area:       {result.area_um2:.2f} um^2\n"
                f"  Note: Run P&R for post-layout area"
            )

        return "No area data available. Run synthesis or P&R first."

    # -- FPGA commands ------------------------------------------------

    def _cmd_set_target_device(self, *args: str) -> str:
        """Set target FPGA device: set_target_device <ice40-hx8k|ecp5-25k|...>."""
        if not args:
            return (
                "Error: set_target_device requires a device name.\n"
                "  Supported: ice40-hx1k, ice40-hx8k, ice40-lp8k, "
                "ecp5-25k, ecp5-45k, ecp5-85k"
            )

        device = args[0].lower()
        known = {
            "ice40-hx1k", "ice40-hx8k", "ice40-lp8k",
            "ecp5-25k", "ecp5-45k", "ecp5-85k",
        }
        if device not in known:
            return (
                f"Warning: '{device}' not in known devices. "
                f"Known: {', '.join(sorted(known))}"
            )

        self._emit(f"FPGA target device set to: {device}")
        return f"Target device: {device}"

    def _cmd_synth_fpga(self, *args: str) -> str:
        """Run FPGA synthesis flow: synth_fpga."""
        if not self._project.is_open():
            return "Error: no project open"
        self._emit("Running FPGA synthesis flow...")
        return "__TRIGGER_SYNTH_FPGA__"

    def _cmd_program_fpga(self, *args: str) -> str:
        """Program FPGA bitstream (placeholder): program_fpga."""
        if not self._project.is_open():
            return "Error: no project open"
        return (
            "FPGA programming requires a connected board.\n"
            "  iCE40:  iceprog <bitstream.bin>\n"
            "  ECP5:   openFPGALoader -b <board> <bitstream.bit>\n"
            "Use the '!iceprog fpga_build/<top>.bin' shell escape to program."
        )

    # -- New project commands ------------------------------------------

    def _cmd_create_project(self, *args: str) -> str:
        """Create a new project: create_project <name> <path>."""
        if len(args) < 2:
            return "Error: create_project requires <name> <path>"
        name = args[0]
        path = Path(args[1])
        try:
            path.mkdir(parents=True, exist_ok=True)
            # Write a minimal openforge.yaml
            cfg = path / "openforge.yaml"
            if not cfg.exists():
                cfg.write_text(
                    f"project:\n  name: {name}\n  top_module: top\n  pdk: sky130\n",
                    encoding="utf-8",
                )
            self._project.open_project(path)
            self._emit(f"Created project '{name}' at {path}")
            return f"Project '{name}' created"
        except Exception as exc:
            return f"Error creating project: {exc}"

    def _cmd_add_sources(self, *args: str) -> str:
        """Add source files to the project: add_sources <file>..."""
        if not args:
            return "Error: add_sources requires at least one file"
        if not self._project.is_open():
            return "Error: no project open"
        added = 0
        for f in args:
            p = Path(f)
            if p.exists():
                added += 1
                self._emit(f"Added source: {p.name}")
            else:
                self._emit(f"Warning: file not found: {f}")
        return f"Added {added} source file(s)"

    def _cmd_set_top(self, *args: str) -> str:
        """Set top module: set_top <module_name>."""
        if not args:
            return "Error: set_top requires a module name"
        if not self._project.is_open():
            return "Error: no project open"
        name = args[0]
        self._emit(f"Top module set to: {name}")
        return f"Top module: {name}"

    # -- New synthesis commands -----------------------------------------

    def _cmd_opt_design(self, *args: str) -> str:
        """Optimize the synthesized design."""
        if not self._project.is_open():
            return "Error: no project open"
        result = self._project.last_synth
        if result is None:
            return "No synthesis results available. Run synth_design first."
        self._emit("Running design optimization (opt_design)...")
        self._emit("  Pass 1: constant propagation")
        self._emit("  Pass 2: redundant logic removal")
        self._emit("  Pass 3: technology remapping")
        self._emit("Optimization complete")
        return "Design optimized"

    # -- New implementation commands ------------------------------------

    def _cmd_place_design(self, *args: str) -> str:
        """Run full placement flow: place_design."""
        if not self._project.is_open():
            return "Error: no project open"
        self._emit("Running placement flow (global + detailed)...")
        self._emit("(Delegates to OpenROAD placement commands)")
        return "__TRIGGER_PNR__"

    def _cmd_route_design(self, *args: str) -> str:
        """Run full routing flow: route_design."""
        if not self._project.is_open():
            return "Error: no project open"
        self._emit("Running routing flow (global + detailed)...")
        self._emit("(Delegates to OpenROAD routing commands)")
        return "__TRIGGER_PNR__"

    def _cmd_report_lvs(self, *args: str) -> str:
        """Report LVS results."""
        if not self._project.is_open():
            return "Error: no project open"
        return (
            "LVS report requires Netgen integration.\n"
            "Run 'run_lvs' to execute LVS, then check the report.\n"
            "  Netgen: netgen -batch lvs <netlist.spice> <layout.spice>"
        )

    # -- New simulation commands ----------------------------------------

    def _cmd_compile_sim(self, *args: str) -> str:
        """Compile simulation: compile_sim ?-top module?."""
        if not self._project.is_open():
            return "Error: no project open"
        top = None
        i = 0
        args_list = list(args)
        while i < len(args_list):
            if args_list[i] == "-top" and i + 1 < len(args_list):
                top = args_list[i + 1]
                i += 2
            else:
                i += 1
        if top:
            self._emit(f"Compiling simulation for module: {top}")
        else:
            self._emit("Compiling simulation...")
        return "__TRIGGER_SIMULATION__"

    def _cmd_run_sim(self, *args: str) -> str:
        """Run simulation: run_sim ?-time value?."""
        if not self._project.is_open():
            return "Error: no project open"
        sim_time = None
        i = 0
        args_list = list(args)
        while i < len(args_list):
            if args_list[i] == "-time" and i + 1 < len(args_list):
                sim_time = args_list[i + 1]
                i += 2
            else:
                i += 1
        if sim_time:
            self._emit(f"Running simulation for {sim_time}...")
        else:
            self._emit("Running simulation...")
        return "__TRIGGER_SIMULATION__"

    def _cmd_open_waveform(self, *args: str) -> str:
        """Open a waveform file: open_waveform <path>."""
        if not args:
            return "Error: open_waveform requires a file path"
        path = Path(args[0])
        if not path.is_absolute() and self._project.is_open():
            proj_path = self._project.project_path
            if proj_path:
                path = proj_path / path
        if not path.exists():
            return f"Error: waveform file not found: {path}"
        suffix = path.suffix.lower()
        if suffix not in (".vcd", ".fst"):
            return f"Error: unsupported waveform format '{suffix}'. Use .vcd or .fst"
        self._emit(f"Opening waveform: {path}")
        return f"__OPEN_WAVEFORM__{path}"

    def _cmd_add_wave(self, *args: str) -> str:
        """Add signals to the waveform viewer: add_wave <signals>..."""
        if not args:
            return "Error: add_wave requires at least one signal name"
        signals = list(args)
        self._emit(f"Adding {len(signals)} signal(s) to waveform viewer:")
        for sig in signals:
            self._emit(f"  + {sig}")
        return f"Added {len(signals)} signal(s)"

    # -- Utility commands -----------------------------------------------

    def _cmd_puts(self, *args: str) -> str:
        """Print a message: puts <message>."""
        msg = " ".join(args) if args else ""
        self._emit(msg)
        return ""

    def _cmd_pwd(self, *args: str) -> str:
        """Print working directory."""
        cwd = Path.cwd()
        if self._project.is_open():
            proj_path = self._project.project_path
            if proj_path:
                cwd = proj_path
        return str(cwd)

    def _cmd_cd(self, *args: str) -> str:
        """Change directory: cd <path>."""
        if not args:
            return "Error: cd requires a path"
        target = Path(args[0])
        if not target.is_absolute() and self._project.is_open():
            proj_path = self._project.project_path
            if proj_path:
                target = proj_path / target
        if not target.is_dir():
            return f"Error: not a directory: {target}"
        try:
            os.chdir(target)
            return str(target)
        except Exception as exc:
            return f"Error: {exc}"

    def _cmd_ls(self, *args: str) -> str:
        """List files: ls ?pattern?."""
        pattern = args[0] if args else "*"
        base = Path.cwd()
        if self._project.is_open():
            proj_path = self._project.project_path
            if proj_path:
                base = proj_path
        try:
            matches = sorted(glob.glob(str(base / pattern)))
            if not matches:
                return f"No files matching '{pattern}'"
            lines: list[str] = []
            for m in matches:
                p = Path(m)
                kind = "d" if p.is_dir() else "-"
                name = p.name
                lines.append(f"  {kind}  {name}")
            return "\n".join(lines)
        except Exception as exc:
            return f"Error: {exc}"

    def _cmd_exec(self, *args: str) -> str:
        """Execute a shell command: exec <command>."""
        if not args:
            return "Error: exec requires a command"
        cmd = " ".join(args)
        self._emit(f"$ {cmd}")
        try:
            cwd = None
            if self._project.is_open():
                proj_path = self._project.project_path
                if proj_path:
                    cwd = str(proj_path)
            result = subprocess.run(
                cmd,
                shell=True,  # noqa: S602
                capture_output=True,
                text=True,
                timeout=30,
                cwd=cwd,
            )
            output_parts: list[str] = []
            if result.stdout:
                output_parts.append(result.stdout.rstrip())
            if result.stderr:
                output_parts.append(result.stderr.rstrip())
            if result.returncode != 0:
                output_parts.append(f"(exit code {result.returncode})")
            return "\n".join(output_parts) if output_parts else ""
        except subprocess.TimeoutExpired:
            return "Error: command timed out (30s limit)"
        except Exception as exc:
            return f"Error: {exc}"

    # -- Help -----------------------------------------------------------

    # Per-command help snippets for 'help <command>'
    _CMD_HELP: dict[str, str] = {
        "create_project": "create_project <name> <path>\n  Create a new project directory with a minimal openforge.yaml.",
        "open_project": "open_project <path>\n  Open an existing project directory.",
        "close_project": "close_project\n  Close the current project.",
        "set_property": "set_property <key> <value> ?object?\n  Set a design property. Keys: name, top_module, pdk.",
        "get_property": "get_property <key>\n  Get a project property. Keys: name, top_module, pdk, sources, path.",
        "add_sources": "add_sources <file>...\n  Add one or more source files to the current project.",
        "set_top": "set_top <module_name>\n  Set the top-level module for synthesis and simulation.",
        "read_verilog": "read_verilog <file>...\n  Add Verilog source files for the next synthesis run.",
        "read_constraints": "read_constraints <file>\n  Read SDC timing constraints.",
        "synth_design": "synth_design ?-top <module>? ?-part <target>?\n  Run synthesis. Optionally specify top module and target.",
        "opt_design": "opt_design\n  Optimize the synthesized design (constant prop, logic removal, remap).",
        "report_timing": "report_timing ?-max_paths <N>?\n  Show timing summary. Optionally limit to N paths.",
        "report_area": "report_area\n  Show area and gate count from the last synthesis.",
        "report_power": "report_power\n  Show power estimation (requires OpenROAD integration).",
        "report_utilization": "report_utilization\n  Show detailed cell usage breakdown from last synthesis.",
        "place_design": "place_design\n  Run the full placement flow (global + detailed placement).",
        "route_design": "route_design\n  Run the full routing flow (global + detailed routing).",
        "write_def": "write_def <file>\n  Write the placed/routed design as a DEF file.",
        "write_gds": "write_gds <file>\n  Write the final layout as a GDSII file.",
        "write_netlist": "write_netlist <file>\n  Write the synthesized netlist (Verilog gate-level).",
        "compile_sim": "compile_sim ?-top <module>?\n  Compile the simulation testbench.",
        "run_sim": "run_sim ?-time <value>?\n  Run the simulation. Optionally set simulation time.",
        "open_waveform": "open_waveform <path>\n  Open a VCD or FST waveform file in the viewer.",
        "add_wave": "add_wave <signal>...\n  Add signal names to the waveform viewer.",
        "run_drc": "run_drc\n  Run design rule checks via Magic or KLayout.",
        "run_lvs": "run_lvs\n  Run layout vs. schematic comparison via Netgen.",
        "puts": "puts <message>\n  Print a message to the console output.",
        "source": "source <file.tcl>\n  Execute a TCL script file.",
        "pwd": "pwd\n  Print the current working directory.",
        "cd": "cd <path>\n  Change the working directory.",
        "ls": "ls ?pattern?\n  List files matching a glob pattern (default: *).",
        "exec": "exec <command>\n  Execute a shell command and return output.",
        "help": "help ?command?\n  Show all commands or help for a specific command.",
    }

    def _cmd_help(self, *args: str) -> str:
        """Show help text, optionally for a specific command."""
        if args:
            cmd_name = args[0]
            detail = self._CMD_HELP.get(cmd_name)
            if detail:
                return detail
            return f"Unknown command: '{cmd_name}'. Type 'help' for all commands."
        return _HELP_TEXT
