"""ngspice analog circuit simulator wrapper.

This engine wraps the open-source ``ngspice`` SPICE simulator and exposes a
high-level API for the analyses most commonly needed by analog/mixed-signal
verification flows: DC sweep, AC sweep, transient, operating point,
noise, and Monte Carlo.

The wrapper produces a temporary control file (``.cir``) that ``.include``s
the user's netlist and issues the proper ``.dc`` / ``.ac`` / ``.tran`` /
``.op`` / ``.noise`` analysis cards. Output is written to a ``raw`` file
which can be parsed by :mod:`openforge.spice.parser` (or any
``ngspice``-compatible reader).
"""

from __future__ import annotations

import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class SpiceAnalysisConfig:
    """Common configuration shared by SPICE analyses."""

    output_raw: Path | None = None
    output_log: Path | None = None
    extra_commands: tuple[str, ...] = ()
    save_signals: tuple[str, ...] = ()


class NgspiceEngine(ToolEngine):
    """ngspice analog circuit simulator wrapper.

    The engine writes a control deck on the fly that includes the user's
    netlist and runs the requested analysis. Use one engine instance per
    project; the wrapper is otherwise stateless.
    """

    BINARY = "ngspice"
    DOCKER_IMAGE = ""

    # Recognised analysis types (used by Monte Carlo and reporting).
    KNOWN_ANALYSES = ("dc", "ac", "tran", "op", "noise")

    def __init__(self, backend: ExecutionBackend = ExecutionBackend.NATIVE) -> None:
        super().__init__(backend=backend)

    # ------------------------------------------------------------------
    # Required ToolEngine interface
    # ------------------------------------------------------------------
    def check_installed(self) -> bool:
        """Return True if ngspice is on PATH."""
        if self.backend == ExecutionBackend.DOCKER:
            return bool(self.docker_image)
        return shutil.which(self.binary) is not None

    def version(self) -> str:
        """Return ngspice's version banner (or 'unknown')."""
        if not self.check_installed():
            return "not installed"
        result = self.run(["--version"], timeout=10.0)
        if result.ok and result.stdout:
            for line in result.stdout.splitlines():
                if "ngspice" in line.lower() and any(c.isdigit() for c in line):
                    return line.strip()
            return result.stdout.splitlines()[0].strip()
        if result.stderr:
            return result.stderr.splitlines()[0].strip()
        return "unknown"

    # ------------------------------------------------------------------
    # Public analysis API
    # ------------------------------------------------------------------
    def run_dc(
        self,
        netlist: Path,
        source: str,
        start: float,
        stop: float,
        step: float,
        config: SpiceAnalysisConfig | None = None,
    ) -> ToolResult:
        """Run a DC sweep simulation.

        Sweeps ``source`` from ``start`` to ``stop`` in ``step`` increments
        and stores the result in a raw file (path returned via the result's
        command list - the last argument is the raw file).
        """
        netlist = Path(netlist)
        if not netlist.exists():
            return self._missing_netlist(netlist)
        analysis = f".dc {source} {start} {stop} {step}"
        return self._run_with_control(
            netlist,
            analysis_card=analysis,
            analysis_kind="dc",
            config=config,
        )

    def run_ac(
        self,
        netlist: Path,
        fstart: float,
        fstop: float,
        points_per_decade: int = 10,
        config: SpiceAnalysisConfig | None = None,
    ) -> ToolResult:
        """Run an AC frequency sweep (decade sweep)."""
        netlist = Path(netlist)
        if not netlist.exists():
            return self._missing_netlist(netlist)
        analysis = f".ac dec {points_per_decade} {fstart} {fstop}"
        return self._run_with_control(
            netlist,
            analysis_card=analysis,
            analysis_kind="ac",
            config=config,
        )

    def run_tran(
        self,
        netlist: Path,
        tstep: float,
        tstop: float,
        tstart: float = 0.0,
        config: SpiceAnalysisConfig | None = None,
    ) -> ToolResult:
        """Run a transient simulation from ``tstart`` to ``tstop``."""
        netlist = Path(netlist)
        if not netlist.exists():
            return self._missing_netlist(netlist)
        analysis = f".tran {tstep} {tstop} {tstart}" if tstart > 0 else f".tran {tstep} {tstop}"
        return self._run_with_control(
            netlist,
            analysis_card=analysis,
            analysis_kind="tran",
            config=config,
        )

    def run_op(
        self,
        netlist: Path,
        config: SpiceAnalysisConfig | None = None,
    ) -> ToolResult:
        """Compute the DC operating point."""
        netlist = Path(netlist)
        if not netlist.exists():
            return self._missing_netlist(netlist)
        return self._run_with_control(
            netlist,
            analysis_card=".op",
            analysis_kind="op",
            config=config,
        )

    def run_noise(
        self,
        netlist: Path,
        output: str,
        source: str,
        fstart: float,
        fstop: float,
        points_per_decade: int = 10,
        config: SpiceAnalysisConfig | None = None,
    ) -> ToolResult:
        """Run a noise analysis between ``source`` and ``output``."""
        netlist = Path(netlist)
        if not netlist.exists():
            return self._missing_netlist(netlist)
        analysis = f".noise v({output}) {source} dec {points_per_decade} {fstart} {fstop}"
        return self._run_with_control(
            netlist,
            analysis_card=analysis,
            analysis_kind="noise",
            config=config,
        )

    def run_monte_carlo(
        self,
        netlist: Path,
        runs: int = 100,
        analysis: str = "op",
        config: SpiceAnalysisConfig | None = None,
    ) -> ToolResult:
        """Run a basic Monte Carlo loop using ngspice's control language.

        Each iteration runs the requested analysis after letting ngspice
        re-evaluate any ``.param`` lines that use the ``agauss`` /
        ``gauss`` distributions. The number of completed iterations is
        embedded in the result log.
        """
        netlist = Path(netlist)
        if not netlist.exists():
            return self._missing_netlist(netlist)
        if analysis not in self.KNOWN_ANALYSES:
            analysis = "op"
        loop = [
            f"* Monte Carlo wrapper - {runs} runs",
            f".include {netlist.resolve().as_posix()}",
            ".control",
            f"let mc_runs = {runs}",
            "let i = 0",
            "while i < mc_runs",
            "  reset",
            f"  {analysis}",
            "  let i = i + 1",
            "end",
            "quit",
            ".endc",
            ".end",
        ]
        return self._exec_control_lines(loop, kind="mc")

    # ------------------------------------------------------------------
    # Internal control deck handling
    # ------------------------------------------------------------------
    def _run_with_control(
        self,
        netlist: Path,
        *,
        analysis_card: str,
        analysis_kind: str,
        config: SpiceAnalysisConfig | None,
    ) -> ToolResult:
        """Build a wrapper deck that includes ``netlist`` and run it."""
        cfg = config or SpiceAnalysisConfig()
        raw_path = cfg.output_raw or Path(tempfile.gettempdir()) / f"ngspice_{analysis_kind}.raw"

        save_lines: list[str] = []
        for sig in cfg.save_signals:
            save_lines.append(f"  save {sig}")

        extra_lines = [f"  {cmd}" for cmd in cfg.extra_commands]

        deck = [
            f"* OpenForge ngspice {analysis_kind} wrapper",
            f".include {netlist.resolve().as_posix()}",
            analysis_card,
            ".control",
            "set filetype=ascii",
            *save_lines,
            "run",
            *extra_lines,
            f"write {raw_path.as_posix()}",
            "quit",
            ".endc",
            ".end",
        ]
        return self._exec_control_lines(deck, kind=analysis_kind, raw_path=raw_path)

    def _exec_control_lines(
        self,
        lines: Sequence[str],
        *,
        kind: str,
        raw_path: Path | None = None,
    ) -> ToolResult:
        """Write a deck to a tempfile and invoke ngspice in batch mode."""
        with tempfile.NamedTemporaryFile(
            "w", suffix=f"_{kind}.cir", delete=False, encoding="utf-8"
        ) as fh:
            fh.write("\n".join(lines))
            fh.write("\n")
            deck_path = Path(fh.name)

        args = ["-b", deck_path.as_posix()]
        result = self.run(args, timeout=600.0)

        # Append the raw path so callers can recover it from result.command.
        if raw_path is not None:
            new_cmd = list(result.command) + ["#raw=" + raw_path.as_posix()]
            result = ToolResult(
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                duration=result.duration,
                command=new_cmd,
            )
        return result

    def _missing_netlist(self, path: Path) -> ToolResult:
        return ToolResult(
            returncode=-1,
            stderr=f"Netlist not found: {path}",
            command=[self.binary],
        )

    # ------------------------------------------------------------------
    # High-level parsed wrappers used by the desktop panel
    # ------------------------------------------------------------------
    @staticmethod
    def _raw_from_result(result: ToolResult) -> Path | None:
        for tok in result.command:
            if isinstance(tok, str) and tok.startswith("#raw="):
                return Path(tok[len("#raw="):])
        return None

    def _parsed_from_result(self, result: ToolResult) -> dict:
        raw = self._raw_from_result(result)
        if raw is None or not raw.exists():
            return {
                "error": (result.stderr or "").strip() or "no raw file produced",
                "stdout": result.stdout,
                "stderr": result.stderr,
                "signals": {},
            }
        parsed = self.parse_raw_ascii(raw)
        vars_ = parsed.get("variables", [])
        values = parsed.get("values", [])
        names = [v["name"] for v in vars_]
        columns: dict[str, list[float]] = {n: [] for n in names}
        for row in values:
            for i, name in enumerate(names):
                if i < len(row):
                    columns[name].append(row[i])
        return {
            "plotname": parsed.get("plotname", ""),
            "variables": vars_,
            "signals": columns,
            "num_points": parsed.get("num_points", 0),
            "raw_path": str(raw),
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def parse_raw_file(self, raw_path: Path) -> dict:
        """Parse an ngspice ASCII raw output file into a dict."""
        return self.parse_raw_ascii(Path(raw_path))

    def run_transient(
        self,
        netlist: Path,
        tstep: float,
        tstop: float,
        tstart: float = 0.0,
    ) -> dict:
        """Run transient and return a parsed dict ``{time, signals, ...}``."""
        result = self.run_tran(netlist, tstep, tstop, tstart)
        parsed = self._parsed_from_result(result)
        sigs = parsed.get("signals", {})
        time_col: list[float] = []
        for k in list(sigs.keys()):
            if k.lower() == "time":
                time_col = sigs.pop(k)
                break
        parsed["time"] = time_col
        return parsed

    def run_dc_sweep(
        self,
        netlist: Path,
        src: str,
        vstart: float,
        vstop: float,
        vinc: float,
    ) -> dict:
        """Run a DC sweep and return a parsed dict."""
        result = self.run_dc(netlist, src, vstart, vstop, vinc)
        parsed = self._parsed_from_result(result)
        sigs = parsed.get("signals", {})
        sweep_var = ""
        sweep_values: list[float] = []
        for k in list(sigs.keys()):
            kl = k.lower()
            if "sweep" in kl or kl == src.lower() or kl == f"v({src.lower()})":
                sweep_var = k
                sweep_values = sigs.pop(k)
                break
        if not sweep_var and sigs:
            # Fallback: take the first column as the sweep axis.
            k = next(iter(sigs))
            sweep_var = k
            sweep_values = sigs.pop(k)
        parsed["sweep_var"] = sweep_var
        parsed["sweep"] = sweep_values
        return parsed

    def run_ac_analysis(
        self,
        netlist: Path,
        sweep: str = "dec",
        points_per_dec: int = 10,
        fstart: float = 1.0,
        fstop: float = 1e9,
    ) -> dict:
        """Run an AC analysis and return a parsed dict ``{freq, signals}``."""
        result = self.run_ac(netlist, fstart, fstop, points_per_dec)
        parsed = self._parsed_from_result(result)
        sigs = parsed.get("signals", {})
        freq: list[float] = []
        for k in list(sigs.keys()):
            if k.lower() == "frequency":
                freq = sigs.pop(k)
                break
        parsed["freq"] = freq
        return parsed

    def run_op_analysis(self, netlist: Path) -> dict:
        """Run operating point and return ``{node_voltages: {name: value}}``."""
        result = self.run_op(netlist)
        parsed = self._parsed_from_result(result)
        node_voltages: dict[str, float] = {}
        for name, vals in parsed.get("signals", {}).items():
            if vals:
                node_voltages[name] = vals[-1]
        parsed["node_voltages"] = node_voltages
        return parsed

    def run_noise_analysis(
        self,
        netlist: Path,
        output: str,
        source: str,
        fstart: float = 1.0,
        fstop: float = 1e9,
        points_per_dec: int = 10,
    ) -> dict:
        """Run noise analysis and return parsed dict."""
        result = self.run_noise(netlist, output, source, fstart, fstop, points_per_dec)
        parsed = self._parsed_from_result(result)
        sigs = parsed.get("signals", {})
        freq: list[float] = []
        for k in list(sigs.keys()):
            if k.lower() in ("frequency", "freq"):
                freq = sigs.pop(k)
                break
        parsed["freq"] = freq
        parsed["onoise"] = sigs.get("onoise_total", sigs.get("onoise_spectrum", []))
        parsed["inoise"] = sigs.get("inoise_total", sigs.get("inoise_spectrum", []))
        return parsed

    # ------------------------------------------------------------------
    # Convenience parsers for ngspice ASCII raw files
    # ------------------------------------------------------------------
    @staticmethod
    def parse_raw_ascii(raw_path: Path) -> dict:
        """Parse a small subset of an ngspice ASCII raw file.

        Returns a dict with keys ``title``, ``plotname``, ``variables`` (list of
        ``{index, name, type}``), ``values`` (list of rows, each row a list of
        floats), and ``num_points``.
        """
        raw_path = Path(raw_path)
        if not raw_path.exists():
            return {"error": f"raw file missing: {raw_path}"}
        title = ""
        plotname = ""
        variables: list[dict] = []
        values: list[list[float]] = []
        no_vars = 0
        no_points = 0
        in_vars = False
        in_values = False
        with raw_path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                low = line.lower()
                if low.startswith("title:"):
                    title = line.split(":", 1)[1].strip()
                elif low.startswith("plotname:"):
                    plotname = line.split(":", 1)[1].strip()
                elif low.startswith("no. variables:"):
                    no_vars = int(line.split(":")[1].strip())
                elif low.startswith("no. points:"):
                    no_points = int(line.split(":")[1].strip())
                elif low.startswith("variables:"):
                    in_vars = True
                    in_values = False
                elif low.startswith("values:"):
                    in_vars = False
                    in_values = True
                elif in_vars:
                    parts = line.split()
                    if len(parts) >= 3:
                        variables.append(
                            {"index": int(parts[0]), "name": parts[1], "type": parts[2]}
                        )
                elif in_values:
                    parts = line.split()
                    if not parts:
                        continue
                    # ngspice ascii values rows: idx v0 \n v1 \n v2 ...
                    try:
                        nums = [float(p) for p in parts if _is_number(p)]
                    except ValueError:
                        continue
                    if nums:
                        if len(nums) == no_vars + 1:
                            values.append(nums[1:])
                        elif len(nums) == 1 and values and len(values[-1]) < no_vars:
                            values[-1].extend(nums)
                        else:
                            values.append(nums)
        return {
            "title": title,
            "plotname": plotname,
            "variables": variables,
            "values": values,
            "num_points": no_points or len(values),
        }


def _is_number(token: str) -> bool:
    """Return True if ``token`` parses as a float."""
    if not token:
        return False
    try:
        float(token)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Convenience helpers used by the desktop panel and co-simulator
# ---------------------------------------------------------------------------
_SI_SUFFIX = {
    "f": 1e-15,
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "m": 1e-3,
    "k": 1e3,
    "meg": 1e6,
    "g": 1e9,
    "t": 1e12,
}


def parse_si_value(value: str) -> float:
    """Parse a SPICE-style SI value such as ``1k``, ``2.2u``, ``5meg``."""
    if value is None:
        return 0.0
    s = str(value).strip().lower()
    if not s:
        return 0.0
    m = re.match(r"^([+-]?\d*\.?\d+(?:e[+-]?\d+)?)\s*([a-z]*)", s)
    if not m:
        try:
            return float(s)
        except ValueError:
            return 0.0
    num = float(m.group(1))
    suffix = m.group(2)
    if not suffix:
        return num
    if suffix in _SI_SUFFIX:
        return num * _SI_SUFFIX[suffix]
    if suffix.startswith("meg"):
        return num * 1e6
    return num


def format_si_value(value: float, unit: str = "") -> str:
    """Format a number with the most appropriate SI suffix."""
    if value == 0:
        return f"0{unit}"
    abs_v = abs(value)
    pairs = [
        (1e-15, "f"),
        (1e-12, "p"),
        (1e-9, "n"),
        (1e-6, "u"),
        (1e-3, "m"),
        (1.0, ""),
        (1e3, "k"),
        (1e6, "M"),
        (1e9, "G"),
        (1e12, "T"),
    ]
    chosen = pairs[5]
    for scale, suffix in pairs:
        if abs_v >= scale:
            chosen = (scale, suffix)
    scale, suffix = chosen
    return f"{value / scale:.3g}{suffix}{unit}"


__all__ = [
    "NgspiceEngine",
    "SpiceAnalysisConfig",
    "parse_si_value",
    "format_si_value",
]
