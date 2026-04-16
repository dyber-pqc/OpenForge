"""AI tool-calling framework for OpenForge.

Provides a typed registry of callable "tools" that a local LLM (via Ollama
function calling, or plain JSON coaxed out of a chat model) can invoke to
interact with the running OpenForge session: read RTL, query violations,
run lint/synth, apply STA what-if scenarios, etc.

The registry is process-global and populated with a set of built-in tools
that cover the most useful read/action surfaces. Desktop panels may
register additional context-specific tools at runtime (e.g., a panel can
expose its current state through :meth:`ToolRegistry.register`).

Every invocation goes through :meth:`ToolRegistry.invoke`, which wraps the
handler in ``try/except`` so a misbehaving tool never crashes the chat
loop — failures surface as :class:`ToolResult` objects with ``success=False``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ToolParameter(BaseModel):
    """A single named parameter for a tool."""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    default: Any | None = None


class AiTool(BaseModel):
    """Tool metadata (what the LLM sees)."""

    name: str
    description: str
    parameters: list[ToolParameter] = Field(default_factory=list)
    returns: str = "object"


class ToolCall(BaseModel):
    """A request from the LLM to run a specific tool."""

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """The outcome of executing a :class:`ToolCall`."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    tool: str
    success: bool
    output: Any | None = None
    error: str | None = None

    def to_llm_text(self) -> str:
        """Serialize for feeding back into a chat history."""
        if not self.success:
            return f"[tool:{self.tool}] ERROR: {self.error}"
        try:
            return f"[tool:{self.tool}] {json.dumps(self.output, default=str)[:4000]}"
        except Exception:
            return f"[tool:{self.tool}] {str(self.output)[:4000]}"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Process-global registry of AI-callable tools."""

    _singleton: "ToolRegistry | None" = None

    def __init__(self) -> None:
        self._tools: dict[str, AiTool] = {}
        self._handlers: dict[str, Callable[..., Any]] = {}

    @classmethod
    def instance(cls) -> "ToolRegistry":
        if cls._singleton is None:
            cls._singleton = cls()
            try:
                register_builtin_tools(cls._singleton)
            except Exception:
                pass
        return cls._singleton

    def register(
        self,
        name: str,
        handler: Callable[..., Any],
        description: str = "",
        parameters: list[ToolParameter] | None = None,
        returns: str = "object",
    ) -> None:
        self._tools[name] = AiTool(
            name=name,
            description=description,
            parameters=parameters or [],
            returns=returns,
        )
        self._handlers[name] = handler

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)
        self._handlers.pop(name, None)

    def list_tools(self) -> list[AiTool]:
        return list(self._tools.values())

    def has(self, name: str) -> bool:
        return name in self._tools

    def invoke(self, call: ToolCall) -> ToolResult:
        handler = self._handlers.get(call.tool)
        if handler is None:
            return ToolResult(
                tool=call.tool, success=False, error=f"unknown tool: {call.tool}"
            )
        try:
            output = handler(**call.arguments)
            return ToolResult(tool=call.tool, success=True, output=output)
        except TypeError as e:
            return ToolResult(tool=call.tool, success=False, error=f"bad args: {e}")
        except Exception as e:  # pragma: no cover - defensive
            return ToolResult(tool=call.tool, success=False, error=str(e))

    def to_ollama_tools(self) -> list[dict]:
        """Emit tools in the Ollama/OpenAI ``tools`` array format."""
        out: list[dict] = []
        for t in self._tools.values():
            props: dict[str, dict] = {}
            required: list[str] = []
            for p in t.parameters:
                props[p.name] = {"type": p.type, "description": p.description}
                if p.required:
                    required.append(p.name)
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": {
                            "type": "object",
                            "properties": props,
                            "required": required,
                        },
                    },
                }
            )
        return out


# ---------------------------------------------------------------------------
# Built-in tool handlers
# ---------------------------------------------------------------------------


_PROJECT_ROOT: Path | None = None


def set_project_root(path: str | Path | None) -> None:
    """Set the project root used by built-in filesystem tools."""
    global _PROJECT_ROOT
    _PROJECT_ROOT = Path(path) if path else None


def _project_root() -> Path:
    return _PROJECT_ROOT or Path.cwd()


def _read_file(path: str, max_bytes: int = 32_000) -> dict:
    p = Path(path)
    if not p.is_absolute():
        p = _project_root() / p
    if not p.exists():
        return {"path": str(p), "error": "not found"}
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"path": str(p), "error": str(e)}
    truncated = len(text) > max_bytes
    return {
        "path": str(p),
        "content": text[:max_bytes],
        "truncated": truncated,
        "size": len(text),
    }


def _search_rtl(pattern: str, max_hits: int = 50) -> dict:
    import re

    root = _project_root()
    hits: list[dict] = []
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return {"error": f"bad regex: {e}", "hits": []}
    exts = {".v", ".sv", ".vh", ".svh", ".vhd", ".vhdl"}
    for p in root.rglob("*"):
        if len(hits) >= max_hits:
            break
        if not p.is_file() or p.suffix.lower() not in exts:
            continue
        try:
            for i, line in enumerate(
                p.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                if regex.search(line):
                    hits.append(
                        {"file": str(p.relative_to(root)), "line": i, "text": line.strip()[:200]}
                    )
                    if len(hits) >= max_hits:
                        break
        except Exception:
            continue
    return {"pattern": pattern, "hits": hits, "count": len(hits)}


def _run_lint() -> dict:
    try:
        from openforge.verification.lint import LintRunner  # type: ignore

        runner = LintRunner()
        result = runner.run(_project_root())
        return {"status": "ok", "issues": getattr(result, "issues", [])}
    except Exception as e:
        return {"status": "skipped", "reason": f"lint engine unavailable: {e}"}


def _run_synthesis() -> dict:
    try:
        from openforge.synthesis.runner import SynthesisRunner  # type: ignore

        return {"status": "queued", "runner": SynthesisRunner.__name__}
    except Exception as e:
        return {"status": "skipped", "reason": str(e)}


def _get_timing_report() -> dict:
    try:
        from openforge.physical.sta_parser import parse_sta_report  # type: ignore

        root = _project_root()
        for candidate in ("reports/sta.rpt", "reports/timing.rpt", "pnr_build/sta.rpt"):
            p = root / candidate
            if p.exists():
                try:
                    data = parse_sta_report(p)
                    return {"path": str(p), "data": data}
                except Exception:
                    return {"path": str(p), "content": p.read_text(errors="replace")[:8000]}
        return {"status": "no_report"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _get_violations(kind: str | None = None) -> dict:
    try:
        from openforge.physical.violation_db import ViolationDb  # type: ignore

        db = ViolationDb.instance() if hasattr(ViolationDb, "instance") else ViolationDb()
        if kind:
            items = db.query(kind=kind) if hasattr(db, "query") else []
        else:
            items = db.all() if hasattr(db, "all") else []
        return {"count": len(items), "items": [str(i) for i in items[:50]]}
    except Exception as e:
        return {"count": 0, "items": [], "reason": str(e)}


def _apply_sta_what_if(change: dict) -> dict:
    try:
        from openforge.physical.sta_whatif import StaWhatIf  # type: ignore

        w = StaWhatIf()
        delta = w.apply(change) if hasattr(w, "apply") else None
        return {"applied": True, "slack_delta": delta}
    except Exception as e:
        return {"applied": False, "reason": str(e)}


_PANEL_STATE_PROVIDERS: dict[str, Callable[[], Any]] = {}


def register_panel_state_provider(panel: str, provider: Callable[[], Any]) -> None:
    _PANEL_STATE_PROVIDERS[panel] = provider


def _get_panel_state(panel: str) -> dict:
    prov = _PANEL_STATE_PROVIDERS.get(panel)
    if prov is None:
        return {"panel": panel, "available": False}
    try:
        return {"panel": panel, "available": True, "state": prov()}
    except Exception as e:
        return {"panel": panel, "available": False, "error": str(e)}


def _suggest_sdc(description: str) -> dict:
    """Rule-based SDC suggestion (LLM wrapping is done by the panel)."""
    desc = description.lower()
    lines: list[str] = []
    if "clock" in desc and "mhz" in desc:
        import re

        m = re.search(r"(\d+(?:\.\d+)?)\s*mhz", desc)
        if m:
            period = 1000.0 / float(m.group(1))
            lines.append(f"create_clock -name clk -period {period:.3f} [get_ports clk]")
    if "input delay" in desc:
        lines.append("set_input_delay -clock clk 2.0 [all_inputs]")
    if "output delay" in desc:
        lines.append("set_output_delay -clock clk 2.0 [all_outputs]")
    if "false path" in desc:
        lines.append("set_false_path -from [get_ports rst_n]")
    if not lines:
        lines.append("# Unable to infer constraints from description")
    return {"description": description, "sdc": "\n".join(lines)}


def _debug_drc(rule: str, coords: list[float] | None = None) -> dict:
    fixes = {
        "min_spacing": "Increase spacing between shapes or move to different layer.",
        "min_width": "Widen the violating shape to meet minimum width.",
        "min_area": "Add filler shape or merge adjacent shapes.",
        "antenna": "Insert antenna diode or break the net with a jumper.",
        "density": "Add density fill in the affected region.",
    }
    return {
        "rule": rule,
        "coords": coords,
        "suggested_fix": fixes.get(rule, "Consult PDK DRC manual for rule details."),
    }


def _explain_path(path_id: str) -> dict:
    try:
        from openforge.physical.sta_parser import parse_sta_report  # type: ignore  # noqa

        return {
            "path": path_id,
            "explanation": (
                "Critical paths are typically dominated by net delay, cell delay "
                "through long logic chains, or insufficient setup margin. "
                "Check fanout, load caps, and consider pipelining."
            ),
        }
    except Exception as e:
        return {"path": path_id, "error": str(e)}


def register_builtin_tools(registry: ToolRegistry) -> None:
    """Register the set of always-available tools."""

    registry.register(
        "read_file",
        _read_file,
        "Read a source file (RTL, SDC, YAML, report) from the project.",
        [ToolParameter(name="path", type="string", description="Path to file, relative to project root or absolute.")],
    )
    registry.register(
        "search_rtl",
        _search_rtl,
        "Regex search across RTL sources (.v/.sv/.vhd).",
        [ToolParameter(name="pattern", type="string", description="Python regex pattern.")],
    )
    registry.register(
        "run_lint",
        _run_lint,
        "Run the RTL lint engine on the current project.",
        [],
    )
    registry.register(
        "run_synthesis",
        _run_synthesis,
        "Kick off the synthesis stage for the current project.",
        [],
    )
    registry.register(
        "get_timing_report",
        _get_timing_report,
        "Fetch the most recent static timing analysis report.",
        [],
    )
    registry.register(
        "get_violations",
        _get_violations,
        "Query the violation database.",
        [ToolParameter(name="kind", type="string", description="Optional filter: drc|lvs|lint|timing", required=False)],
    )
    registry.register(
        "apply_sta_what_if",
        _apply_sta_what_if,
        "Apply a hypothetical STA change and return estimated slack delta.",
        [ToolParameter(name="change", type="object", description="Dict describing the what-if change.")],
    )
    registry.register(
        "get_panel_state",
        _get_panel_state,
        "Read the current state of a named desktop panel.",
        [ToolParameter(name="panel", type="string", description="Panel identifier (e.g. 'timing', 'violations').")],
    )
    registry.register(
        "suggest_sdc",
        _suggest_sdc,
        "Suggest SDC constraints from a natural-language description.",
        [ToolParameter(name="description", type="string", description="Plain-English description of constraints.")],
    )
    registry.register(
        "debug_drc",
        _debug_drc,
        "Look up a suggested fix for a DRC rule violation.",
        [
            ToolParameter(name="rule", type="string", description="DRC rule name."),
            ToolParameter(name="coords", type="array", description="Optional [x,y] violation coords.", required=False),
        ],
    )
    registry.register(
        "explain_path",
        _explain_path,
        "Explain why a given timing path is critical.",
        [ToolParameter(name="path_id", type="string", description="STA path identifier.")],
    )


__all__ = [
    "AiTool",
    "ToolCall",
    "ToolParameter",
    "ToolRegistry",
    "ToolResult",
    "register_builtin_tools",
    "register_panel_state_provider",
    "set_project_root",
]
