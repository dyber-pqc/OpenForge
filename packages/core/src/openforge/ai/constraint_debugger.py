"""AI-assisted constraint debugger.

Given a failing STA path and a set of SDC files, this class asks a local
LLM to propose SDC tweaks (multicycle, false-path, clock-group, etc.) and
scores each proposal by running it through :class:`StaWhatIf` to get an
estimated slack delta.

The module is defensive: if the LLM is not reachable or StaWhatIf is
unavailable, it degrades to a rule-based proposer so the UI still has
something useful to display.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from openforge.ai.ollama_client import OllamaClient


class StaPath(BaseModel):
    """Minimal STA path record consumed by the debugger."""

    path_id: str
    startpoint: str = ""
    endpoint: str = ""
    slack: float = 0.0
    required: float = 0.0
    arrival: float = 0.0
    clock: str = ""
    stages: list[dict] = Field(default_factory=list)


class ProposedFix(BaseModel):
    sdc_change: str
    rationale: str
    estimated_slack_delta: float = 0.0
    confidence: float = 0.5


class ConstraintDebugger:
    """Propose and preview SDC fixes for failing STA paths."""

    def __init__(
        self,
        ollama_client: OllamaClient | None,
        sta_report: Any | None,
        sdc_files: list[str | Path] | None = None,
        model: str = "llama3.1",
    ) -> None:
        self.client = ollama_client
        self.sta_report = sta_report
        self.sdc_files = [Path(p) for p in (sdc_files or [])]
        self.model = model

    # ------------------------------------------------------------------

    def _paths(self) -> list[StaPath]:
        rep = self.sta_report
        if rep is None:
            return []
        if isinstance(rep, list):
            raw = rep
        else:
            raw = getattr(rep, "paths", None) or []
        out: list[StaPath] = []
        for p in raw:
            if isinstance(p, StaPath):
                out.append(p)
            elif isinstance(p, dict):
                try:
                    out.append(StaPath(**p))
                except Exception:
                    continue
        return out

    def analyze_path(self, path_id: str) -> dict:
        for p in self._paths():
            if p.path_id == path_id:
                return {
                    "path_id": p.path_id,
                    "startpoint": p.startpoint,
                    "endpoint": p.endpoint,
                    "slack": p.slack,
                    "clock": p.clock,
                    "stages": p.stages,
                    "is_failing": p.slack < 0,
                }
        return {"path_id": path_id, "error": "path not found"}

    # ------------------------------------------------------------------

    def propose_fixes(self, path: StaPath | dict) -> list[ProposedFix]:
        if isinstance(path, dict):
            try:
                path = StaPath(**path)
            except Exception:
                return []
        proposals = self._llm_proposals(path) if self.client is not None else []
        if not proposals:
            proposals = self._rule_based_proposals(path)
        for prop in proposals:
            prop.estimated_slack_delta = self.preview_with_whatif(
                {"type": "sdc", "text": prop.sdc_change, "path": path.path_id}
            )
        return proposals

    def _rule_based_proposals(self, path: StaPath) -> list[ProposedFix]:
        out: list[ProposedFix] = []
        if path.slack < 0:
            out.append(
                ProposedFix(
                    sdc_change=(
                        f"set_multicycle_path -setup 2 "
                        f"-from [get_pins {{{path.startpoint}}}] "
                        f"-to [get_pins {{{path.endpoint}}}]"
                    ),
                    rationale="Relax setup by 1 cycle on the failing path.",
                    confidence=0.6,
                )
            )
            out.append(
                ProposedFix(
                    sdc_change=(
                        f"set_false_path "
                        f"-from [get_pins {{{path.startpoint}}}] "
                        f"-to [get_pins {{{path.endpoint}}}]"
                    ),
                    rationale="Declare path as false if it is genuinely asynchronous.",
                    confidence=0.3,
                )
            )
            if path.clock:
                out.append(
                    ProposedFix(
                        sdc_change=(
                            f"set_clock_uncertainty -setup 0.05 [get_clocks {path.clock}]"
                        ),
                        rationale="Tighten uncertainty budget to reclaim margin.",
                        confidence=0.4,
                    )
                )
        return out

    def _llm_proposals(self, path: StaPath) -> list[ProposedFix]:
        assert self.client is not None
        prompt = (
            "You are an SDC/STA expert. Propose up to 3 SDC constraint changes "
            "that would fix this failing path. Respond with a JSON array of "
            "objects with keys sdc_change, rationale, confidence (0..1). "
            "Do not include prose outside the JSON.\n\n"
            f"Path: {path.model_dump_json()}\n"
            "Existing SDC files: "
            + ", ".join(str(p) for p in self.sdc_files)
        )
        try:
            chunks = list(
                self.client.generate(self.model, prompt, stream=False)
            )
        except Exception:
            return []
        text = "".join(chunks)
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            return []
        try:
            items = json.loads(m.group(0))
        except Exception:
            return []
        out: list[ProposedFix] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            try:
                out.append(
                    ProposedFix(
                        sdc_change=str(it.get("sdc_change", "")),
                        rationale=str(it.get("rationale", "")),
                        confidence=float(it.get("confidence", 0.5)),
                    )
                )
            except Exception:
                continue
        return out

    # ------------------------------------------------------------------

    def preview_with_whatif(self, proposed_change: dict) -> float:
        try:
            from openforge.physical.sta_whatif import StaWhatIf  # type: ignore

            w = StaWhatIf()
            if hasattr(w, "apply"):
                res = w.apply(proposed_change)
                if isinstance(res, (int, float)):
                    return float(res)
                if isinstance(res, dict):
                    return float(res.get("slack_delta", 0.0))
        except Exception:
            pass
        # crude heuristic fallback
        text = proposed_change.get("text", "") if isinstance(proposed_change, dict) else ""
        if "false_path" in text:
            return 10.0
        if "multicycle" in text:
            return 2.5
        if "uncertainty" in text:
            return 0.5
        return 0.0

    def apply_fix(self, choice: ProposedFix | dict) -> bool:
        if isinstance(choice, dict):
            try:
                choice = ProposedFix(**choice)
            except Exception:
                return False
        if not self.sdc_files:
            return False
        target = self.sdc_files[0]
        try:
            existing = target.read_text(encoding="utf-8") if target.exists() else ""
            stamp = "\n# Added by OpenForge ConstraintDebugger\n"
            target.write_text(existing + stamp + choice.sdc_change + "\n", encoding="utf-8")
            return True
        except Exception:
            return False


__all__ = ["ConstraintDebugger", "ProposedFix", "StaPath"]
