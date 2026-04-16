"""Equivalence checking via Yosys ``eqy``.

Generates a real ``.eqy`` file and invokes the ``eqy`` binary. If ``eqy``
is unavailable the runner degrades gracefully with a UNKNOWN status so
the UI remains functional during development.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field


class EqyConfig(BaseModel):
    gold_files: list[str] = Field(default_factory=list)
    gate_files: list[str] = Field(default_factory=list)
    top: str
    match_strategy: str = "auto"
    timeout_s: int = 600


class EqyResult(BaseModel):
    status: str  # equivalent | not_equivalent | partial | error
    matched_pairs: int = 0
    proven_pairs: int = 0
    counterexample: str | None = None
    log: str = ""


class EqyRunner:
    def __init__(self, config: EqyConfig, work_dir: Path) -> None:
        self.config = config
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.eqy_path = self.work_dir / f"{self.config.top}.eqy"

    def generate_eqy_file(self) -> Path:
        cfg = self.config
        lines: list[str] = []
        lines.append("[gold]")
        for f in cfg.gold_files:
            lines.append(f"read -sv {f}")
        lines.append(f"prep -top {cfg.top}")
        lines.append("")
        lines.append("[gate]")
        for f in cfg.gate_files:
            lines.append(f"read -sv {f}")
        lines.append(f"prep -top {cfg.top}")
        lines.append("")
        lines.append("[strategy basic]")
        lines.append("use sat")
        lines.append("depth 10")
        lines.append("")
        lines.append("[match]")
        if cfg.match_strategy != "auto":
            lines.append(cfg.match_strategy)
        lines.append("")
        lines.append("[collect]")
        lines.append("")
        self.eqy_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return self.eqy_path

    def run(self) -> EqyResult:
        self.generate_eqy_file()
        eqy = shutil.which("eqy")
        if not eqy:
            return EqyResult(
                status="error", log="eqy binary not found in PATH"
            )
        cmd = [eqy, "-f", str(self.eqy_path.name)]
        try:
            cp = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.work_dir),
                timeout=self.config.timeout_s,
            )
        except subprocess.TimeoutExpired:
            return EqyResult(status="error", log="eqy timeout")
        log = cp.stdout + cp.stderr
        matched = 0
        proven = 0
        m = re.search(r"matched\s*:\s*(\d+)", log, re.IGNORECASE)
        if m:
            matched = int(m.group(1))
        m2 = re.search(r"proven\s*:\s*(\d+)", log, re.IGNORECASE)
        if m2:
            proven = int(m2.group(1))
        status = "error"
        cex: str | None = None
        if "Successfully proved designs equivalent" in log or re.search(
            r"DONE \(PASS", log
        ):
            status = "equivalent"
        elif "Failed to prove" in log or re.search(r"DONE \(FAIL", log):
            status = "not_equivalent"
            # Look for a witness VCD
            task_dir = self.work_dir / self.config.top
            if task_dir.exists():
                for v in task_dir.rglob("*.vcd"):
                    cex = str(v)
                    break
        elif matched and proven and proven < matched:
            status = "partial"
        elif cp.returncode == 0:
            status = "equivalent"
        return EqyResult(
            status=status,
            matched_pairs=matched,
            proven_pairs=proven,
            counterexample=cex,
            log=log,
        )
