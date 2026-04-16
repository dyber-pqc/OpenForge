"""Signal integrity / crosstalk delay analysis - PrimeTime SI replacement.

Extracts coupling capacitance from a DEF, computes Miller-effect crosstalk
delay, and detects combinational glitches.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CrosstalkVictim:
    """A net suffering crosstalk-induced delay."""

    net: str
    delta_delay_ns: float
    aggressors: list[str] = field(default_factory=list)
    coupling_cap_ff: float = 0.0
    delta_slew_ps: float = 0.0

    def severity(self) -> str:
        if self.delta_delay_ns >= 0.1:
            return "critical"
        if self.delta_delay_ns >= 0.05:
            return "high"
        if self.delta_delay_ns >= 0.02:
            return "medium"
        return "low"


@dataclass
class SiResult:
    """Aggregate signal integrity results."""

    victims: list[CrosstalkVictim] = field(default_factory=list)
    worst_delta_delay: float = 0.0
    affected_paths: list[str] = field(default_factory=list)
    glitch_warnings: list[dict] = field(default_factory=list)
    total_coupling_ff: float = 0.0

    def by_severity(self) -> dict[str, int]:
        counts: dict[str, int] = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
        }
        for v in self.victims:
            counts[v.severity()] += 1
        return counts


class SignalIntegrityAnalyzer:
    """Coupling extraction, crosstalk delay, and glitch detection."""

    EPS0 = 8.854e-12  # F/m
    DEFAULT_VDD = 1.8

    def __init__(self, dielectric_k: float = 4.2) -> None:
        self.k = dielectric_k

    # ---------- coupling extraction ----------

    def extract_coupling(
        self,
        def_path: Path,
        layer_info: dict,
    ) -> dict[tuple[str, str], float]:
        """Extract coupling capacitance between adjacent nets in a DEF.

        Algorithm:
            1. Parse all SPECIALNETS / NETS routes from the DEF.
            2. Project routes onto each layer.
            3. For each pair on the same layer, find parallel runs that
               sit on adjacent tracks (within `track_pitch * 1.5`).
            4. Coupling cap = eps0 * k * (parallel_length * thickness) / spacing
        """
        try:
            text = Path(def_path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return {}

        # quick parser: find NET ... + ROUTED ... blocks
        net_segments: dict[str, list[tuple[str, float, float, float, float]]] = {}
        cur_net: str | None = None
        layer_re = re.compile(
            r"(metal\d+|met\d+|li\d*)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+|\*)\s+(-?\d+|\*)\s*\)",
            re.IGNORECASE,
        )
        net_re = re.compile(r"-\s+(\S+)")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                m = net_re.match(stripped)
                if m:
                    cur_net = m.group(1)
                    net_segments.setdefault(cur_net, [])
            for lm in layer_re.finditer(stripped):
                if cur_net is None:
                    continue
                layer = lm.group(1).lower()
                x1 = float(lm.group(2)) / 1000.0
                y1 = float(lm.group(3)) / 1000.0
                x2_raw = lm.group(4)
                y2_raw = lm.group(5)
                x2 = float(x2_raw) / 1000.0 if x2_raw != "*" else x1
                y2 = float(y2_raw) / 1000.0 if y2_raw != "*" else y1
                net_segments[cur_net].append((layer, x1, y1, x2, y2))

        coupling: dict[tuple[str, str], float] = {}
        nets = list(net_segments.keys())
        for i in range(len(nets)):
            for j in range(i + 1, len(nets)):
                a = nets[i]
                b = nets[j]
                cap = self._pair_coupling(net_segments[a], net_segments[b], layer_info)
                if cap > 0:
                    coupling[(a, b)] = cap
        return coupling

    def _pair_coupling(
        self,
        seg_a: list[tuple[str, float, float, float, float]],
        seg_b: list[tuple[str, float, float, float, float]],
        layer_info: dict,
    ) -> float:
        total = 0.0
        for la, ax1, ay1, ax2, ay2 in seg_a:
            for lb, bx1, by1, bx2, by2 in seg_b:
                if la != lb:
                    continue
                info = layer_info.get(la, {"pitch": 0.34, "thickness": 0.13, "spacing_min": 0.14})
                pitch = info["pitch"]
                thickness = info["thickness"]
                # both horizontal?
                if abs(ay2 - ay1) < 1e-9 and abs(by2 - by1) < 1e-9:
                    if abs(ay1 - by1) > pitch * 1.5:
                        continue
                    overlap = max(
                        0.0,
                        min(max(ax1, ax2), max(bx1, bx2)) - max(min(ax1, ax2), min(bx1, bx2)),
                    )
                    spacing = max(abs(ay1 - by1), info["spacing_min"])
                # both vertical?
                elif abs(ax2 - ax1) < 1e-9 and abs(bx2 - bx1) < 1e-9:
                    if abs(ax1 - bx1) > pitch * 1.5:
                        continue
                    overlap = max(
                        0.0,
                        min(max(ay1, ay2), max(by1, by2)) - max(min(ay1, ay2), min(by1, by2)),
                    )
                    spacing = max(abs(ax1 - bx1), info["spacing_min"])
                else:
                    continue
                if overlap <= 0.0:
                    continue
                # cap (F) = eps0 * k * (length * thickness) / spacing  - convert um to m
                cap = self.EPS0 * self.k * (overlap * 1e-6 * thickness * 1e-6) / (spacing * 1e-6)
                total += cap
        return total * 1e15  # to fF

    # ---------- crosstalk delay ----------

    def compute_crosstalk_delay(
        self,
        coupling_caps: dict[tuple[str, str], float],
        net_drivers: dict[str, str],
        net_capacitance: dict[str, float],
        switching_window: dict[str, tuple[float, float]] | None = None,
    ) -> SiResult:
        """Miller-effect crosstalk delay calculation.

        For each victim net the additional delay is approximated as
            dt = K_miller * Cc * Vdd / I_drv
        where I_drv is taken proportional to the net's nominal load capacitance.
        Aggressors are filtered to those with overlapping switching windows.
        """
        result = SiResult()
        victim_caps: dict[str, float] = {}
        victim_aggressors: dict[str, list[str]] = {}

        for (a, b), cc in coupling_caps.items():
            if switching_window is not None:
                wa = switching_window.get(a)
                wb = switching_window.get(b)
                if wa and wb and (wa[1] < wb[0] or wb[1] < wa[0]):
                    continue
            victim_caps[a] = victim_caps.get(a, 0.0) + cc
            victim_caps[b] = victim_caps.get(b, 0.0) + cc
            victim_aggressors.setdefault(a, []).append(b)
            victim_aggressors.setdefault(b, []).append(a)
            result.total_coupling_ff += cc

        for net, cc_total in victim_caps.items():
            cnet = net_capacitance.get(net, 10.0)
            # Miller factor - opposite-direction switching doubles effective coupling
            k_miller = 2.0
            # crude delta delay model: dt (ns) ~ k * cc_total / cnet * 0.05
            dt = k_miller * (cc_total / max(cnet, 0.1)) * 0.05
            slew = dt * 0.5 * 1000.0  # ps
            victim = CrosstalkVictim(
                net=net,
                delta_delay_ns=dt,
                aggressors=victim_aggressors.get(net, []),
                coupling_cap_ff=cc_total,
                delta_slew_ps=slew,
            )
            result.victims.append(victim)
            if dt > result.worst_delta_delay:
                result.worst_delta_delay = dt

        result.victims.sort(key=lambda v: -v.delta_delay_ns)
        return result

    # ---------- glitch detection ----------

    def detect_glitches(
        self,
        netlist_json: Path,
        timing_info: dict,
    ) -> list[dict]:
        """Detect combinational hazards from arrival-time skew at gate inputs."""
        warnings: list[dict] = []
        try:
            data = json.loads(Path(netlist_json).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return warnings
        arrivals = timing_info.get("arrivals", {})
        tpd_default = timing_info.get("tpd_default", 0.05)
        for mod in data.get("modules", {}).values():
            for cell_name, cell in mod.get("cells", {}).items():
                ctype = cell.get("type", "")
                if not any(g in ctype.lower() for g in ("xor", "and", "or", "mux")):
                    continue
                inputs: list[float] = []
                for pin, conn in cell.get("connections", {}).items():
                    if pin.lower() in ("a", "b", "c", "i0", "i1", "i2"):
                        if isinstance(conn, list) and conn:
                            arr = arrivals.get(str(conn[0]), 0.0)
                            inputs.append(arr)
                if len(inputs) >= 2:
                    spread = max(inputs) - min(inputs)
                    if spread > tpd_default:
                        warnings.append(
                            {
                                "cell": cell_name,
                                "type": ctype,
                                "input_skew_ns": spread,
                                "severity": "high" if spread > 2 * tpd_default else "medium",
                            }
                        )
        return warnings

    # ---------- reporting ----------

    def generate_si_report(self, result: SiResult) -> str:
        """Plain-text crosstalk report similar to PrimeTime SI."""
        lines: list[str] = []
        lines.append("=" * 72)
        lines.append("OpenForge Signal Integrity Report")
        lines.append("=" * 72)
        lines.append(f"Total victim nets:        {len(result.victims)}")
        lines.append(f"Worst delta delay:        {result.worst_delta_delay:.4f} ns")
        lines.append(f"Total coupling cap:       {result.total_coupling_ff:.2f} fF")
        sev = result.by_severity()
        lines.append(
            f"Severity:  critical={sev['critical']}  high={sev['high']}  "
            f"medium={sev['medium']}  low={sev['low']}"
        )
        lines.append("")
        lines.append(f"{'Net':<30} {'Cc(fF)':>10} {'dDly(ns)':>10} {'Sev':>10}")
        lines.append("-" * 72)
        for v in result.victims[:50]:
            lines.append(
                f"{v.net[:30]:<30} {v.coupling_cap_ff:>10.2f} "
                f"{v.delta_delay_ns:>10.4f} {v.severity():>10}"
            )
        if result.glitch_warnings:
            lines.append("")
            lines.append("Glitch warnings:")
            for w in result.glitch_warnings[:20]:
                lines.append(f"  {w['cell']} ({w['type']}) skew={w['input_skew_ns']:.3f}ns")
        lines.append("=" * 72)
        return "\n".join(lines)
