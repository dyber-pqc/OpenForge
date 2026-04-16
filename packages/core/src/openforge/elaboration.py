"""RTL elaboration -- pre-synthesis hierarchy/parameter resolution via Yosys.

Produces a parameter-resolved Verilog netlist *before* technology mapping.
This step is independent of synthesis and is useful for hierarchy inspection,
linting, and pre-synthesis simulation.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from openforge.config.schema import SourceFile
from openforge.engine.base import ExecutionBackend
from openforge.engine.yosys import YosysEngine


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class PortInfo:
    name: str
    direction: str  # input/output/inout
    width: int = 1
    signed: bool = False


@dataclass
class InstanceInfo:
    name: str
    module_type: str
    parameters: dict[str, str] = field(default_factory=dict)


@dataclass
class ModuleInfo:
    name: str
    parameters: dict[str, str] = field(default_factory=dict)
    ports: list[PortInfo] = field(default_factory=list)
    instances: list[InstanceInfo] = field(default_factory=list)
    line: int = 0


@dataclass
class ElaborationResult:
    success: bool
    elaborated_netlist: Path | None
    json_netlist: Path | None
    top_module: str
    modules: dict[str, ModuleInfo] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration: float = 0.0
    log_text: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_language(path: Path, declared: str = "auto") -> str:
    """Resolve a file's language from its declaration or extension."""
    if declared and declared != "auto":
        return declared
    suffix = path.suffix.lower()
    if suffix in (".sv", ".svh"):
        return "systemverilog"
    if suffix in (".vhd", ".vhdl"):
        return "vhdl"
    return "verilog"


def _flag_includes(include_dirs: Iterable[Path]) -> str:
    return " ".join(f"-I{Path(d).as_posix()}" for d in include_dirs)


def _flag_defines(defines: Mapping[str, str]) -> str:
    parts: list[str] = []
    for k, v in (defines or {}).items():
        if v == "" or v is None:
            parts.append(f"-D{k}")
        else:
            parts.append(f"-D{k}={v}")
    return " ".join(parts)


def _collect_warnings(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if re.search(r"(?i)\bwarning\b", ln)]


def _collect_errors(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if re.search(r"(?i)\berror\b", ln)]


def _parse_json_netlist(json_path: Path) -> dict[str, ModuleInfo]:
    """Parse a Yosys ``write_json`` netlist into ModuleInfo objects."""
    modules: dict[str, ModuleInfo] = {}
    if not json_path.exists():
        return modules
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return modules

    for mod_name, mod_data in (data.get("modules") or {}).items():
        info = ModuleInfo(name=mod_name)
        # Parameters (if Yosys preserved them)
        params = mod_data.get("parameter_default_values") or {}
        info.parameters = {k: str(v) for k, v in params.items()}

        # Ports
        for pname, pdata in (mod_data.get("ports") or {}).items():
            bits = pdata.get("bits") or []
            info.ports.append(
                PortInfo(
                    name=pname,
                    direction=pdata.get("direction", "input"),
                    width=len(bits) if bits else 1,
                    signed=bool(pdata.get("signed", False)),
                )
            )

        # Sub-instances (cells that point to other user modules)
        for cname, cdata in (mod_data.get("cells") or {}).items():
            ctype = cdata.get("type", "")
            cparams = cdata.get("parameters") or {}
            info.instances.append(
                InstanceInfo(
                    name=cname,
                    module_type=ctype,
                    parameters={k: str(v) for k, v in cparams.items()},
                )
            )

        # Source line attribute
        attrs = mod_data.get("attributes") or {}
        src = attrs.get("src", "")
        if isinstance(src, str) and ":" in src:
            try:
                info.line = int(src.rsplit(":", 1)[-1].split(".")[0])
            except ValueError:
                pass

        modules[mod_name] = info
    return modules


# ---------------------------------------------------------------------------
# Elaborator
# ---------------------------------------------------------------------------


class Elaborator:
    """Run Yosys to elaborate RTL into a parameter-resolved netlist."""

    def __init__(self, project_path: Path | str | None = None) -> None:
        self._project_path = Path(project_path).resolve() if project_path else Path.cwd()
        self._yosys = YosysEngine()
        if not self._yosys.check_installed():
            self._yosys = YosysEngine(backend=ExecutionBackend.DOCKER)

    def elaborate(
        self,
        sources: Sequence[SourceFile],
        top_module: str,
        include_dirs: Sequence[Path] = (),
        defines: Mapping[str, str] | None = None,
        output_dir: Path | None = None,
    ) -> ElaborationResult:
        """Elaborate ``sources`` into a parameter-resolved netlist.

        Generates a Yosys script that reads each source with the appropriate
        reader, runs ``hierarchy -check -top``, ``proc``, ``opt -fast``, and
        writes ``elaborated.v`` plus ``elaborated.json``.
        """
        start = time.monotonic()
        out_dir = Path(output_dir) if output_dir else self._project_path / "elab_build"
        out_dir.mkdir(parents=True, exist_ok=True)

        defines = dict(defines or {})
        inc_flag = _flag_includes(include_dirs)
        def_flag = _flag_defines(defines)
        rd_flags = " ".join(p for p in (inc_flag, def_flag) if p)

        lines: list[str] = []
        has_vhdl = False
        for src in sources:
            if src.is_testbench:
                continue
            path = Path(src.path).as_posix()
            lang = _detect_language(Path(src.path), src.language)
            lib_flag = f"-L {src.library}" if src.library and src.library != "work" else ""
            if lang == "systemverilog":
                lines.append(
                    " ".join(p for p in ("read_verilog -sv -defer", rd_flags, lib_flag, path) if p)
                )
            elif lang == "vhdl":
                has_vhdl = True
                lib = src.library or "work"
                lines.append(f"ghdl --std=08 --work={lib} {path} -e")
            else:
                lines.append(
                    " ".join(p for p in ("read_verilog -defer", rd_flags, lib_flag, path) if p)
                )

        if has_vhdl:
            lines.insert(0, "plugin -i ghdl")

        lines.append(f"hierarchy -check -top {top_module}")
        lines.append("proc")
        lines.append("opt -fast")

        elab_v = out_dir / "elaborated.v"
        elab_json = out_dir / "elaborated.json"
        try:
            rel_v = elab_v.relative_to(self._project_path).as_posix()
            rel_j = elab_json.relative_to(self._project_path).as_posix()
        except ValueError:
            rel_v = elab_v.as_posix()
            rel_j = elab_json.as_posix()

        lines.append(f"write_verilog -noattr {rel_v}")
        lines.append(f"write_json {rel_j}")
        lines.append("stat")

        script = "\n".join(lines) + "\n"
        script_path = out_dir / "elaborate.ys"
        script_path.write_text(script, encoding="utf-8")

        try:
            rel_script = script_path.relative_to(self._project_path).as_posix()
        except ValueError:
            rel_script = script_path.as_posix()

        result = self._yosys.run_script(rel_script, cwd=str(self._project_path))
        combined = (result.stdout or "") + (result.stderr or "")

        log_path = out_dir / "elaboration_log.txt"
        try:
            log_path.write_text(combined, encoding="utf-8")
        except OSError:
            pass

        modules = _parse_json_netlist(elab_json) if elab_json.exists() else {}
        elapsed = time.monotonic() - start

        return ElaborationResult(
            success=result.ok and elab_v.exists(),
            elaborated_netlist=elab_v if elab_v.exists() else None,
            json_netlist=elab_json if elab_json.exists() else None,
            top_module=top_module,
            modules=modules,
            errors=_collect_errors(combined) if not result.ok else [],
            warnings=_collect_warnings(combined),
            duration=elapsed,
            log_text=combined,
        )
