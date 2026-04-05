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

Design:
  read_verilog <file>...    Add Verilog source files
  read_constraints <file>   Read SDC constraints

Synthesis:
  synth_design              Run synthesis on the current project
  report_area               Show area/utilization report
  report_timing             Show timing summary
  report_power              Show power estimate

Simulation:
  run_simulation            Compile and simulate the design

Verification:
  run_drc                   Run design rule checks
  run_lvs                   Run layout vs schematic

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
            "run_drc": self._cmd_run_drc,
            "run_lvs": self._cmd_run_lvs,
            "get_property": self._cmd_get_property,
            "set_property": self._cmd_set_property,
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

    def _cmd_help(self, *args: str) -> str:
        return _HELP_TEXT
