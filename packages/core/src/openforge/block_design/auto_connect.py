"""Smart auto-connect engine for OpenForge block designs.

Detects Xilinx/Vivado-style port naming on instances and automatically
produces :class:`BlockConnection` objects for clocks, resets, AXI4-Lite,
AXI4-Full, and AXI-Stream interfaces. When more than one AXI master is
present, it will suggest inserting an AXI SmartConnect crossbar.

The module is Qt-free and depends only on the existing dataclass-based
block design model plus Pydantic v2 for the rule/metadata schemas.
"""

from __future__ import annotations

import re
from typing import Final

from pydantic import BaseModel, Field

from openforge.block_design.generator import (
    BlockConnection,
    BlockDesign,
    BlockPort,
)

# ---------------------------------------------------------------------------
# Rule schema
# ---------------------------------------------------------------------------


class ConnectionRule(BaseModel):
    """Declarative description of an auto-connect rule."""

    name: str
    src_pattern: str
    dst_pattern: str
    direction: str = Field(
        description="master_to_slave, clock, reset, broadcast",
    )
    requires_clock_domain_match: bool = True
    description: str = ""


# ---------------------------------------------------------------------------
# Vivado-style AXI channel signal sets
# ---------------------------------------------------------------------------


_AXIL_SIGNALS: Final[set[str]] = {
    "awaddr",
    "awprot",
    "awvalid",
    "awready",
    "wdata",
    "wstrb",
    "wvalid",
    "wready",
    "bresp",
    "bvalid",
    "bready",
    "araddr",
    "arprot",
    "arvalid",
    "arready",
    "rdata",
    "rresp",
    "rvalid",
    "rready",
}

_AXI4_EXTRA: Final[set[str]] = {
    "awid",
    "awlen",
    "awsize",
    "awburst",
    "awlock",
    "awcache",
    "awqos",
    "awregion",
    "wlast",
    "bid",
    "arid",
    "arlen",
    "arsize",
    "arburst",
    "arlock",
    "arcache",
    "arqos",
    "arregion",
    "rid",
    "rlast",
}

_AXIS_SIGNALS: Final[set[str]] = {
    "tdata",
    "tvalid",
    "tready",
    "tlast",
    "tkeep",
    "tstrb",
    "tuser",
    "tid",
    "tdest",
}

_CLK_RE: Final[re.Pattern[str]] = re.compile(
    r"^(a?clk|clock|m_axi.*_aclk|s_axi.*_aclk|.*_aclk)$", re.IGNORECASE
)
_RST_RE: Final[re.Pattern[str]] = re.compile(
    r"^(a?rst_?n?|reset_?n?|.*_aresetn|m_axi.*_aresetn|s_axi.*_aresetn)$",
    re.IGNORECASE,
)
_AXI_PREFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<prefix>(?:m|s)\d*_axi(?:s|l|_lite)?(?:_[a-z0-9]+)?)_"
    r"(?P<sig>[a-z]+)$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class AutoConnector:
    """Inspect a :class:`BlockDesign` and produce auto-connect wires."""

    def __init__(self, design: BlockDesign) -> None:
        self.design = design
        self._already_sunk: set[tuple[str, str]] = {
            (c.to_inst, c.to_port) for c in design.connections
        }
        self._already_driven: set[tuple[str, str]] = {
            (c.from_inst, c.from_port) for c in design.connections
        }

    # ------------------------------------------------------------------
    # Low-level detection
    # ------------------------------------------------------------------

    def detect_clock_pins(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for inst in self.design.instances:
            hits: list[str] = []
            for p in inst.ports:
                if p.direction != "input":
                    continue
                if _CLK_RE.match(p.name) or p.name.lower().endswith("clk"):
                    hits.append(p.name)
            if hits:
                result[inst.name] = hits
        return result

    def detect_reset_pins(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for inst in self.design.instances:
            hits: list[str] = []
            for p in inst.ports:
                if p.direction != "input":
                    continue
                n = p.name.lower()
                if _RST_RE.match(p.name) or "rst" in n or "reset" in n:
                    hits.append(p.name)
            if hits:
                result[inst.name] = hits
        return result

    def detect_axi_interfaces(self) -> dict[str, list[dict]]:
        """Group ports by Xilinx-style interface prefix.

        Returns a mapping ``inst -> [{prefix, direction, kind, ports}]``
        where ``kind`` is one of ``lite``, ``full``, ``stream``.
        """
        result: dict[str, list[dict]] = {}
        for inst in self.design.instances:
            groups: dict[str, list[BlockPort]] = {}
            for p in inst.ports:
                m = _AXI_PREFIX_RE.match(p.name)
                if m is None:
                    continue
                groups.setdefault(m.group("prefix").lower(), []).append(p)

            ifaces: list[dict] = []
            for prefix, ports in groups.items():
                signames = {self._sig(p.name, prefix) for p in ports}
                direction = (
                    "master"
                    if prefix.startswith("m")
                    else "slave"
                    if prefix.startswith("s")
                    else "unknown"
                )
                kind = self._classify_iface(signames)
                if kind is None:
                    continue
                ifaces.append(
                    {
                        "prefix": prefix,
                        "direction": direction,
                        "kind": kind,
                        "ports": ports,
                        "signals": signames,
                        "data_width": self._infer_data_width(ports, kind),
                    }
                )
            if ifaces:
                result[inst.name] = ifaces
        return result

    @staticmethod
    def _sig(port_name: str, prefix: str) -> str:
        rest = (
            port_name[len(prefix) + 1 :]
            if port_name.lower().startswith(prefix + "_")
            else port_name
        )
        return rest.lower()

    @staticmethod
    def _classify_iface(signals: set[str]) -> str | None:
        if signals & _AXIS_SIGNALS and "tdata" in signals:
            return "stream"
        if _AXIL_SIGNALS.issubset(signals | {"awprot", "arprot"}):
            if signals & _AXI4_EXTRA:
                return "full"
            # Accept lite if at least AW/W/B/AR/R handshakes present
            needed = {"awvalid", "wvalid", "arvalid", "rvalid"}
            if needed.issubset(signals):
                return "lite"
        # Relaxed full check
        if {"awvalid", "wvalid", "arvalid", "rvalid", "wlast"}.issubset(signals):
            return "full"
        return None

    @staticmethod
    def _infer_data_width(ports: list[BlockPort], kind: str) -> int:
        want = "tdata" if kind == "stream" else "wdata"
        for p in ports:
            if p.name.lower().endswith(want):
                return p.width
        return 32

    # ------------------------------------------------------------------
    # High-level auto connects
    # ------------------------------------------------------------------

    def auto_connect_clocks(self, clock_net: str = "sys_clk") -> list[BlockConnection]:
        src_inst, src_port = self._find_or_create_source(clock_net, "clk")
        wires: list[BlockConnection] = []
        for inst_name, pins in self.detect_clock_pins().items():
            if inst_name == src_inst:
                continue
            for pin in pins:
                if (inst_name, pin) in self._already_sunk:
                    continue
                wires.append(
                    BlockConnection(
                        from_inst=src_inst,
                        from_port=src_port,
                        to_inst=inst_name,
                        to_port=pin,
                    )
                )
                self._already_sunk.add((inst_name, pin))
        return wires

    def auto_connect_resets(self, reset_net: str = "sys_rst_n") -> list[BlockConnection]:
        src_inst, src_port = self._find_or_create_source(reset_net, "rst")
        wires: list[BlockConnection] = []
        for inst_name, pins in self.detect_reset_pins().items():
            if inst_name == src_inst:
                continue
            for pin in pins:
                if (inst_name, pin) in self._already_sunk:
                    continue
                wires.append(
                    BlockConnection(
                        from_inst=src_inst,
                        from_port=src_port,
                        to_inst=inst_name,
                        to_port=pin,
                    )
                )
                self._already_sunk.add((inst_name, pin))
        return wires

    def auto_connect_axi(self) -> list[BlockConnection]:
        ifaces = self.detect_axi_interfaces()
        masters: list[tuple[str, dict]] = []
        slaves: list[tuple[str, dict]] = []
        for inst, group in ifaces.items():
            for ifc in group:
                if ifc["kind"] == "stream":
                    continue
                if ifc["direction"] == "master":
                    masters.append((inst, ifc))
                elif ifc["direction"] == "slave":
                    slaves.append((inst, ifc))

        wires: list[BlockConnection] = []
        used_slaves: set[tuple[str, str]] = set()
        for m_inst, m_ifc in masters:
            target = self._find_matching_slave(m_ifc, slaves, used_slaves)
            if target is None:
                continue
            s_inst, s_ifc = target
            used_slaves.add((s_inst, s_ifc["prefix"]))
            wires.extend(self._wire_axi_pair(m_inst, m_ifc, s_inst, s_ifc))
        return wires

    def auto_connect_streams(self) -> list[BlockConnection]:
        ifaces = self.detect_axi_interfaces()
        masters: list[tuple[str, dict]] = []
        slaves: list[tuple[str, dict]] = []
        for inst, group in ifaces.items():
            for ifc in group:
                if ifc["kind"] != "stream":
                    continue
                if ifc["direction"] == "master":
                    masters.append((inst, ifc))
                elif ifc["direction"] == "slave":
                    slaves.append((inst, ifc))

        wires: list[BlockConnection] = []
        used: set[tuple[str, str]] = set()
        for m_inst, m_ifc in masters:
            for s_inst, s_ifc in slaves:
                if (s_inst, s_ifc["prefix"]) in used:
                    continue
                if m_ifc["data_width"] != s_ifc["data_width"]:
                    continue
                used.add((s_inst, s_ifc["prefix"]))
                wires.extend(self._wire_stream_pair(m_inst, m_ifc, s_inst, s_ifc))
                break
        return wires

    def suggest_interconnect(self, masters: list[dict], slaves: list[dict]) -> list[dict]:
        """Return a list of crossbar IPs that should be inserted.

        Any configuration with more than one master or more than one slave
        on the same address domain benefits from an AXI SmartConnect.
        """
        if len(masters) <= 1 and len(slaves) <= 1:
            return []
        data_width = max((m.get("data_width", 32) for m in masters), default=32)
        return [
            {
                "type": "axi_smartconnect",
                "num_masters": len(masters),
                "num_slaves": len(slaves),
                "data_width": data_width,
                "reason": (
                    f"{len(masters)} AXI masters x {len(slaves)} slaves require "
                    f"crossbar arbitration"
                ),
            }
        ]

    def run_all(self) -> list[BlockConnection]:
        wires: list[BlockConnection] = []
        wires.extend(self.auto_connect_clocks())
        wires.extend(self.auto_connect_resets())
        wires.extend(self.auto_connect_axi())
        wires.extend(self.auto_connect_streams())
        return wires

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_or_create_source(self, net_name: str, kind: str) -> tuple[str, str]:
        """Locate an instance port that should drive the shared clock/reset.

        Strategy: find the first instance that has a matching output port
        named like the net (e.g., ``sys_clk``, ``clk_out``), otherwise use
        a synthetic top-level source with name ``(__top__, net_name)``.
        """
        for inst in self.design.instances:
            for p in inst.ports:
                if p.direction == "output" and p.name.lower() == net_name.lower():
                    return inst.name, p.name
        if kind == "clk":
            for inst in self.design.instances:
                for p in inst.ports:
                    if p.direction == "output" and (
                        "clk" in p.name.lower() or "clock" in p.name.lower()
                    ):
                        return inst.name, p.name
        if kind == "rst":
            for inst in self.design.instances:
                for p in inst.ports:
                    if p.direction == "output" and (
                        "rst" in p.name.lower() or "reset" in p.name.lower()
                    ):
                        return inst.name, p.name
        return "__top__", net_name

    def _find_matching_slave(
        self,
        master: dict,
        slaves: list[tuple[str, dict]],
        used: set[tuple[str, str]],
    ) -> tuple[str, dict] | None:
        for s_inst, s_ifc in slaves:
            if (s_inst, s_ifc["prefix"]) in used:
                continue
            if s_ifc["kind"] != master["kind"]:
                # lite<->full are not bit-compatible
                continue
            if s_ifc["data_width"] != master["data_width"]:
                continue
            return s_inst, s_ifc
        return None

    def _wire_axi_pair(
        self,
        m_inst: str,
        m_ifc: dict,
        s_inst: str,
        s_ifc: dict,
    ) -> list[BlockConnection]:
        m_prefix = m_ifc["prefix"]
        s_prefix = s_ifc["prefix"]
        m_sigs = {self._sig(p.name, m_prefix): p for p in m_ifc["ports"]}
        s_sigs = {self._sig(p.name, s_prefix): p for p in s_ifc["ports"]}

        # Address/data/control travel master->slave; responses travel back.
        m_to_s = [
            "awaddr",
            "awprot",
            "awvalid",
            "awid",
            "awlen",
            "awsize",
            "awburst",
            "awlock",
            "awcache",
            "awqos",
            "wdata",
            "wstrb",
            "wvalid",
            "wlast",
            "bready",
            "araddr",
            "arprot",
            "arvalid",
            "arid",
            "arlen",
            "arsize",
            "arburst",
            "arlock",
            "arcache",
            "arqos",
            "rready",
        ]
        s_to_m = [
            "awready",
            "wready",
            "bresp",
            "bid",
            "bvalid",
            "arready",
            "rdata",
            "rresp",
            "rid",
            "rlast",
            "rvalid",
        ]
        wires: list[BlockConnection] = []
        for sig in m_to_s:
            if sig in m_sigs and sig in s_sigs:
                wires.append(
                    BlockConnection(
                        from_inst=m_inst,
                        from_port=m_sigs[sig].name,
                        to_inst=s_inst,
                        to_port=s_sigs[sig].name,
                    )
                )
        for sig in s_to_m:
            if sig in s_sigs and sig in m_sigs:
                wires.append(
                    BlockConnection(
                        from_inst=s_inst,
                        from_port=s_sigs[sig].name,
                        to_inst=m_inst,
                        to_port=m_sigs[sig].name,
                    )
                )
        return wires

    def _wire_stream_pair(
        self,
        m_inst: str,
        m_ifc: dict,
        s_inst: str,
        s_ifc: dict,
    ) -> list[BlockConnection]:
        m_prefix = m_ifc["prefix"]
        s_prefix = s_ifc["prefix"]
        m_sigs = {self._sig(p.name, m_prefix): p for p in m_ifc["ports"]}
        s_sigs = {self._sig(p.name, s_prefix): p for p in s_ifc["ports"]}
        wires: list[BlockConnection] = []
        for sig in ("tdata", "tvalid", "tlast", "tkeep", "tstrb", "tuser", "tid", "tdest"):
            if sig in m_sigs and sig in s_sigs:
                wires.append(
                    BlockConnection(
                        from_inst=m_inst,
                        from_port=m_sigs[sig].name,
                        to_inst=s_inst,
                        to_port=s_sigs[sig].name,
                    )
                )
        if "tready" in s_sigs and "tready" in m_sigs:
            wires.append(
                BlockConnection(
                    from_inst=s_inst,
                    from_port=s_sigs["tready"].name,
                    to_inst=m_inst,
                    to_port=m_sigs["tready"].name,
                )
            )
        return wires


__all__ = ["AutoConnector", "ConnectionRule"]
