"""Post-Quantum Cryptography IP library catalog and template generator.

This module provides a catalog of NIST-standardized post-quantum cryptographic
IP modules (ML-KEM, ML-DSA, SLH-DSA/SPHINCS+, Falcon) along with template
generators for Verilog wrappers, AXI4-Lite slaves, and resource estimation.

Standards referenced:
    - NIST FIPS 203: Module-Lattice-Based Key-Encapsulation Mechanism (ML-KEM)
    - NIST FIPS 204: Module-Lattice-Based Digital Signature Algorithm (ML-DSA)
    - NIST FIPS 205: Stateless Hash-Based Digital Signature Algorithm (SLH-DSA)
    - Falcon (NIST Round 3 alternate - informal spec)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class PqcAlgorithm(Enum):
    """Enumeration of supported post-quantum cryptographic algorithms."""

    ML_KEM_512 = "ml-kem-512"
    ML_KEM_768 = "ml-kem-768"
    ML_KEM_1024 = "ml-kem-1024"
    ML_DSA_44 = "ml-dsa-44"
    ML_DSA_65 = "ml-dsa-65"
    ML_DSA_87 = "ml-dsa-87"
    SPHINCS_128S = "slh-dsa-sha2-128s"
    SPHINCS_128F = "slh-dsa-sha2-128f"
    SPHINCS_192S = "slh-dsa-sha2-192s"
    SPHINCS_256S = "slh-dsa-sha2-256s"
    FALCON_512 = "falcon-512"
    FALCON_1024 = "falcon-1024"


class PqcFamily(Enum):
    """Algorithm families."""

    KEM = "kem"
    SIGNATURE = "signature"


@dataclass
class PqcParams:
    """Parameter set for a PQC algorithm."""

    algorithm: PqcAlgorithm
    public_key_bytes: int
    secret_key_bytes: int
    ciphertext_bytes: int = 0
    signature_bytes: int = 0
    security_level_nist: int = 1
    nist_doc: str = ""
    family: PqcFamily = PqcFamily.KEM
    shared_secret_bytes: int = 32
    seed_bytes: int = 32

    @property
    def is_kem(self) -> bool:
        return self.family == PqcFamily.KEM

    @property
    def is_signature(self) -> bool:
        return self.family == PqcFamily.SIGNATURE


# NIST parameter sets extracted from FIPS 203/204/205 and Falcon spec.
PQC_PARAMS: dict[PqcAlgorithm, PqcParams] = {
    PqcAlgorithm.ML_KEM_512: PqcParams(
        algorithm=PqcAlgorithm.ML_KEM_512,
        public_key_bytes=800,
        secret_key_bytes=1632,
        ciphertext_bytes=768,
        security_level_nist=1,
        nist_doc="FIPS 203",
        family=PqcFamily.KEM,
    ),
    PqcAlgorithm.ML_KEM_768: PqcParams(
        algorithm=PqcAlgorithm.ML_KEM_768,
        public_key_bytes=1184,
        secret_key_bytes=2400,
        ciphertext_bytes=1088,
        security_level_nist=3,
        nist_doc="FIPS 203",
        family=PqcFamily.KEM,
    ),
    PqcAlgorithm.ML_KEM_1024: PqcParams(
        algorithm=PqcAlgorithm.ML_KEM_1024,
        public_key_bytes=1568,
        secret_key_bytes=3168,
        ciphertext_bytes=1568,
        security_level_nist=5,
        nist_doc="FIPS 203",
        family=PqcFamily.KEM,
    ),
    PqcAlgorithm.ML_DSA_44: PqcParams(
        algorithm=PqcAlgorithm.ML_DSA_44,
        public_key_bytes=1312,
        secret_key_bytes=2560,
        signature_bytes=2420,
        security_level_nist=2,
        nist_doc="FIPS 204",
        family=PqcFamily.SIGNATURE,
    ),
    PqcAlgorithm.ML_DSA_65: PqcParams(
        algorithm=PqcAlgorithm.ML_DSA_65,
        public_key_bytes=1952,
        secret_key_bytes=4032,
        signature_bytes=3309,
        security_level_nist=3,
        nist_doc="FIPS 204",
        family=PqcFamily.SIGNATURE,
    ),
    PqcAlgorithm.ML_DSA_87: PqcParams(
        algorithm=PqcAlgorithm.ML_DSA_87,
        public_key_bytes=2592,
        secret_key_bytes=4896,
        signature_bytes=4627,
        security_level_nist=5,
        nist_doc="FIPS 204",
        family=PqcFamily.SIGNATURE,
    ),
    PqcAlgorithm.SPHINCS_128S: PqcParams(
        algorithm=PqcAlgorithm.SPHINCS_128S,
        public_key_bytes=32,
        secret_key_bytes=64,
        signature_bytes=7856,
        security_level_nist=1,
        nist_doc="FIPS 205",
        family=PqcFamily.SIGNATURE,
    ),
    PqcAlgorithm.SPHINCS_128F: PqcParams(
        algorithm=PqcAlgorithm.SPHINCS_128F,
        public_key_bytes=32,
        secret_key_bytes=64,
        signature_bytes=17088,
        security_level_nist=1,
        nist_doc="FIPS 205",
        family=PqcFamily.SIGNATURE,
    ),
    PqcAlgorithm.SPHINCS_192S: PqcParams(
        algorithm=PqcAlgorithm.SPHINCS_192S,
        public_key_bytes=48,
        secret_key_bytes=96,
        signature_bytes=16224,
        security_level_nist=3,
        nist_doc="FIPS 205",
        family=PqcFamily.SIGNATURE,
    ),
    PqcAlgorithm.SPHINCS_256S: PqcParams(
        algorithm=PqcAlgorithm.SPHINCS_256S,
        public_key_bytes=64,
        secret_key_bytes=128,
        signature_bytes=29792,
        security_level_nist=5,
        nist_doc="FIPS 205",
        family=PqcFamily.SIGNATURE,
    ),
    PqcAlgorithm.FALCON_512: PqcParams(
        algorithm=PqcAlgorithm.FALCON_512,
        public_key_bytes=897,
        secret_key_bytes=1281,
        signature_bytes=666,
        security_level_nist=1,
        nist_doc="Falcon (Round 3)",
        family=PqcFamily.SIGNATURE,
    ),
    PqcAlgorithm.FALCON_1024: PqcParams(
        algorithm=PqcAlgorithm.FALCON_1024,
        public_key_bytes=1793,
        secret_key_bytes=2305,
        signature_bytes=1280,
        security_level_nist=5,
        nist_doc="Falcon (Round 3)",
        family=PqcFamily.SIGNATURE,
    ),
}


@dataclass
class PqcModule:
    """A synthesizable PQC module template."""

    algorithm: PqcAlgorithm
    name: str
    description: str
    estimated_gates: int
    estimated_cycles_keygen: int
    estimated_cycles_encaps_or_sign: int
    estimated_cycles_decaps_or_verify: int
    side_channel_protected: bool = False
    fault_protected: bool = False
    interface: str = "axi4-lite"
    clock_mhz: float = 100.0
    verilog_top: str = ""
    register_map: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def params(self) -> PqcParams:
        return PQC_PARAMS[self.algorithm]


def _default_register_map_kem(p: PqcParams) -> dict[str, tuple[int, int]]:
    """Build a typical (offset, size_bytes) register map for a KEM."""
    offset = 0
    rmap: dict[str, tuple[int, int]] = {}
    rmap["CTRL"] = (offset, 4)
    offset += 4
    rmap["STATUS"] = (offset, 4)
    offset += 4
    rmap["IRQ_ENABLE"] = (offset, 4)
    offset += 4
    rmap["VERSION"] = (offset, 4)
    offset += 4
    offset = (offset + 0xF) & ~0xF
    rmap["PUBLIC_KEY"] = (offset, p.public_key_bytes)
    offset += (p.public_key_bytes + 0xF) & ~0xF
    rmap["SECRET_KEY"] = (offset, p.secret_key_bytes)
    offset += (p.secret_key_bytes + 0xF) & ~0xF
    rmap["CIPHERTEXT"] = (offset, p.ciphertext_bytes)
    offset += (p.ciphertext_bytes + 0xF) & ~0xF
    rmap["SHARED_SECRET"] = (offset, p.shared_secret_bytes)
    offset += (p.shared_secret_bytes + 0xF) & ~0xF
    rmap["SEED"] = (offset, p.seed_bytes)
    return rmap


def _default_register_map_sig(p: PqcParams) -> dict[str, tuple[int, int]]:
    """Build a typical (offset, size_bytes) register map for a signature scheme."""
    offset = 0
    rmap: dict[str, tuple[int, int]] = {}
    rmap["CTRL"] = (offset, 4)
    offset += 4
    rmap["STATUS"] = (offset, 4)
    offset += 4
    rmap["IRQ_ENABLE"] = (offset, 4)
    offset += 4
    rmap["VERSION"] = (offset, 4)
    offset += 4
    rmap["MSG_LEN"] = (offset, 4)
    offset += 4
    offset = (offset + 0xF) & ~0xF
    rmap["PUBLIC_KEY"] = (offset, p.public_key_bytes)
    offset += (p.public_key_bytes + 0xF) & ~0xF
    rmap["SECRET_KEY"] = (offset, p.secret_key_bytes)
    offset += (p.secret_key_bytes + 0xF) & ~0xF
    rmap["MESSAGE"] = (offset, 4096)
    offset += 4096
    rmap["SIGNATURE"] = (offset, p.signature_bytes)
    offset += (p.signature_bytes + 0xF) & ~0xF
    rmap["SEED"] = (offset, p.seed_bytes)
    return rmap


# Rough gate-count estimates (ASIC, 65nm-class) extrapolated from public
# literature on hardware implementations of these algorithms.
_GATE_ESTIMATES: dict[PqcAlgorithm, int] = {
    PqcAlgorithm.ML_KEM_512: 80_000,
    PqcAlgorithm.ML_KEM_768: 120_000,
    PqcAlgorithm.ML_KEM_1024: 160_000,
    PqcAlgorithm.ML_DSA_44: 180_000,
    PqcAlgorithm.ML_DSA_65: 240_000,
    PqcAlgorithm.ML_DSA_87: 310_000,
    PqcAlgorithm.SPHINCS_128S: 90_000,
    PqcAlgorithm.SPHINCS_128F: 95_000,
    PqcAlgorithm.SPHINCS_192S: 110_000,
    PqcAlgorithm.SPHINCS_256S: 140_000,
    PqcAlgorithm.FALCON_512: 220_000,
    PqcAlgorithm.FALCON_1024: 340_000,
}

_CYCLE_ESTIMATES: dict[PqcAlgorithm, tuple[int, int, int]] = {
    PqcAlgorithm.ML_KEM_512: (40_000, 50_000, 55_000),
    PqcAlgorithm.ML_KEM_768: (50_000, 60_000, 65_000),
    PqcAlgorithm.ML_KEM_1024: (70_000, 85_000, 90_000),
    PqcAlgorithm.ML_DSA_44: (80_000, 250_000, 90_000),
    PqcAlgorithm.ML_DSA_65: (110_000, 340_000, 120_000),
    PqcAlgorithm.ML_DSA_87: (160_000, 480_000, 170_000),
    PqcAlgorithm.SPHINCS_128S: (40_000_000, 4_000_000_000, 3_000_000),
    PqcAlgorithm.SPHINCS_128F: (1_500_000, 40_000_000, 2_000_000),
    PqcAlgorithm.SPHINCS_192S: (60_000_000, 7_000_000_000, 4_500_000),
    PqcAlgorithm.SPHINCS_256S: (160_000_000, 9_000_000_000, 8_000_000),
    PqcAlgorithm.FALCON_512: (10_000_000, 1_200_000, 80_000),
    PqcAlgorithm.FALCON_1024: (25_000_000, 2_500_000, 160_000),
}


def _build_module(algo: PqcAlgorithm) -> PqcModule:
    p = PQC_PARAMS[algo]
    keygen_cyc, op_cyc, verify_cyc = _CYCLE_ESTIMATES[algo]
    rmap = (
        _default_register_map_kem(p)
        if p.is_kem
        else _default_register_map_sig(p)
    )
    top = f"{algo.value.replace('-', '_')}_top"
    desc_family = "KEM" if p.is_kem else "digital signature"
    return PqcModule(
        algorithm=algo,
        name=algo.value,
        description=f"{algo.value.upper()} post-quantum {desc_family} (NIST {p.nist_doc})",
        estimated_gates=_GATE_ESTIMATES[algo],
        estimated_cycles_keygen=keygen_cyc,
        estimated_cycles_encaps_or_sign=op_cyc,
        estimated_cycles_decaps_or_verify=verify_cyc,
        side_channel_protected=False,
        fault_protected=False,
        interface="axi4-lite",
        clock_mhz=100.0,
        verilog_top=top,
        register_map=rmap,
    )


class PqcCatalog:
    """Catalog of PQC IP modules."""

    def __init__(self) -> None:
        self._modules: dict[PqcAlgorithm, PqcModule] = {
            a: _build_module(a) for a in PqcAlgorithm
        }

    def list_modules(self) -> list[PqcModule]:
        """Return all modules in the catalog."""
        return list(self._modules.values())

    def list_kem_modules(self) -> list[PqcModule]:
        return [m for m in self._modules.values() if m.params.is_kem]

    def list_signature_modules(self) -> list[PqcModule]:
        return [m for m in self._modules.values() if m.params.is_signature]

    def get_module(self, algorithm: PqcAlgorithm) -> PqcModule | None:
        return self._modules.get(algorithm)

    def find_by_name(self, name: str) -> PqcModule | None:
        for m in self._modules.values():
            if m.name == name:
                return m
        return None

    def filter_by_security_level(self, level: int) -> list[PqcModule]:
        return [
            m for m in self._modules.values() if m.params.security_level_nist == level
        ]

    def generate_wrapper(
        self, module: PqcModule, instance_name: str | None = None
    ) -> str:
        """Generate a Verilog wrapper instantiation for the given module."""
        inst = instance_name or f"u_{module.verilog_top}"
        p = module.params
        lines: list[str] = []
        lines.append(f"// Instance of {module.name} ({p.nist_doc})")
        lines.append(f"// Security level: NIST L{p.security_level_nist}")
        lines.append(f"// Estimated gates: {module.estimated_gates}")
        lines.append(f"{module.verilog_top} {inst} (")
        lines.append("    .axi_aclk     (axi_aclk),")
        lines.append("    .axi_aresetn  (axi_aresetn),")
        lines.append("    .awaddr       (s_awaddr),")
        lines.append("    .awvalid      (s_awvalid),")
        lines.append("    .awready      (s_awready),")
        lines.append("    .wdata        (s_wdata),")
        lines.append("    .wstrb        (s_wstrb),")
        lines.append("    .wvalid       (s_wvalid),")
        lines.append("    .wready       (s_wready),")
        lines.append("    .bresp        (s_bresp),")
        lines.append("    .bvalid       (s_bvalid),")
        lines.append("    .bready       (s_bready),")
        lines.append("    .araddr       (s_araddr),")
        lines.append("    .arvalid      (s_arvalid),")
        lines.append("    .arready      (s_arready),")
        lines.append("    .rdata        (s_rdata),")
        lines.append("    .rresp        (s_rresp),")
        lines.append("    .rvalid       (s_rvalid),")
        lines.append("    .rready       (s_rready),")
        lines.append("    .busy         (busy),")
        lines.append("    .done         (done),")
        lines.append("    .error        (error)")
        lines.append(");")
        return "\n".join(lines)

    def generate_axi_slave(self, module: PqcModule) -> str:
        """Generate an AXI4-Lite slave wrapper around the PQC module."""
        p = module.params
        name = module.verilog_top
        lines: list[str] = []
        lines.append(f"// AXI4-Lite slave wrapper for {module.name}")
        lines.append(f"// {p.nist_doc} - NIST L{p.security_level_nist}")
        lines.append(f"module {name}_axi_slave #(")
        lines.append("    parameter AXI_ADDR_WIDTH = 16,")
        lines.append("    parameter AXI_DATA_WIDTH = 32")
        lines.append(") (")
        lines.append("    input  wire                       axi_aclk,")
        lines.append("    input  wire                       axi_aresetn,")
        lines.append("    input  wire [AXI_ADDR_WIDTH-1:0]  awaddr,")
        lines.append("    input  wire                       awvalid,")
        lines.append("    output reg                        awready,")
        lines.append("    input  wire [AXI_DATA_WIDTH-1:0]  wdata,")
        lines.append("    input  wire [(AXI_DATA_WIDTH/8)-1:0] wstrb,")
        lines.append("    input  wire                       wvalid,")
        lines.append("    output reg                        wready,")
        lines.append("    output reg  [1:0]                 bresp,")
        lines.append("    output reg                        bvalid,")
        lines.append("    input  wire                       bready,")
        lines.append("    input  wire [AXI_ADDR_WIDTH-1:0]  araddr,")
        lines.append("    input  wire                       arvalid,")
        lines.append("    output reg                        arready,")
        lines.append("    output reg  [AXI_DATA_WIDTH-1:0]  rdata,")
        lines.append("    output reg  [1:0]                 rresp,")
        lines.append("    output reg                        rvalid,")
        lines.append("    input  wire                       rready,")
        lines.append("    output wire                       irq,")
        lines.append("    output wire                       busy,")
        lines.append("    output wire                       done,")
        lines.append("    output wire                       error")
        lines.append(");")
        lines.append("")
        lines.append("    // Register map:")
        for reg, (off, sz) in module.register_map.items():
            lines.append(f"    //   0x{off:04X}: {reg} ({sz} bytes)")
        lines.append("")
        lines.append("    // -- Core instantiation placeholder --")
        lines.append(f"    // {name} u_core ( ... );")
        lines.append("")
        lines.append("    assign irq = done;")
        lines.append("    assign busy = 1'b0;")
        lines.append("    assign done = 1'b0;")
        lines.append("    assign error = 1'b0;")
        lines.append("")
        lines.append("endmodule")
        return "\n".join(lines)

    def estimate_resources(
        self, module: PqcModule, target: str = "asic"
    ) -> dict[str, Any]:
        """Estimate gates, area, power, latency for the given module.

        Args:
            module: The PqcModule to estimate.
            target: "asic" or "fpga".

        Returns:
            dict with fields: gates, area_um2, power_mw, latency_ms_keygen,
            latency_ms_op, latency_ms_verify, throughput_ops_per_sec.
        """
        gates = module.estimated_gates
        if target == "asic":
            area_um2 = gates * 2.5
            power_mw = gates * 0.0002
        else:  # fpga
            area_um2 = 0.0
            power_mw = gates * 0.0004
        clk = module.clock_mhz * 1e6
        lat_kg = module.estimated_cycles_keygen / clk * 1000.0
        lat_op = module.estimated_cycles_encaps_or_sign / clk * 1000.0
        lat_v = module.estimated_cycles_decaps_or_verify / clk * 1000.0
        throughput = 1000.0 / lat_op if lat_op > 0 else 0.0
        lut_estimate = int(gates * 0.5) if target == "fpga" else 0
        ff_estimate = int(gates * 0.15) if target == "fpga" else 0
        bram_estimate = 0
        if target == "fpga":
            total_bytes = (
                module.params.public_key_bytes
                + module.params.secret_key_bytes
                + module.params.ciphertext_bytes
                + module.params.signature_bytes
            )
            bram_estimate = max(1, total_bytes // 4096)
        return {
            "gates": gates,
            "area_um2": area_um2,
            "power_mw": power_mw,
            "latency_ms_keygen": lat_kg,
            "latency_ms_op": lat_op,
            "latency_ms_verify": lat_v,
            "throughput_ops_per_sec": throughput,
            "target": target,
            "clock_mhz": module.clock_mhz,
            "lut_estimate": lut_estimate,
            "ff_estimate": ff_estimate,
            "bram_estimate": bram_estimate,
        }

    def generate_catalog_yaml(self) -> str:
        """Generate a YAML representation of the entire catalog."""
        lines: list[str] = []
        lines.append("# OpenForge PQC IP Catalog")
        lines.append("modules:")
        for m in self._modules.values():
            p = m.params
            lines.append(f"  - name: {m.name}")
            lines.append(f"    algorithm: {p.algorithm.value}")
            lines.append(f"    family: {p.family.value}")
            lines.append(f"    nist_doc: {p.nist_doc}")
            lines.append(f"    security_level: {p.security_level_nist}")
            lines.append(f"    public_key_bytes: {p.public_key_bytes}")
            lines.append(f"    secret_key_bytes: {p.secret_key_bytes}")
            lines.append(f"    ciphertext_bytes: {p.ciphertext_bytes}")
            lines.append(f"    signature_bytes: {p.signature_bytes}")
            lines.append(f"    estimated_gates: {m.estimated_gates}")
            lines.append(f"    interface: {m.interface}")
        return "\n".join(lines)

    def export_to_json(self) -> dict[str, Any]:
        """Export the entire catalog to a JSON-compatible dict."""
        out: dict[str, Any] = {"modules": []}
        for m in self._modules.values():
            p = m.params
            out["modules"].append(
                {
                    "name": m.name,
                    "algorithm": p.algorithm.value,
                    "family": p.family.value,
                    "nist_doc": p.nist_doc,
                    "security_level_nist": p.security_level_nist,
                    "params": {
                        "public_key_bytes": p.public_key_bytes,
                        "secret_key_bytes": p.secret_key_bytes,
                        "ciphertext_bytes": p.ciphertext_bytes,
                        "signature_bytes": p.signature_bytes,
                        "shared_secret_bytes": p.shared_secret_bytes,
                        "seed_bytes": p.seed_bytes,
                    },
                    "estimated_gates": m.estimated_gates,
                    "estimated_cycles": {
                        "keygen": m.estimated_cycles_keygen,
                        "encaps_or_sign": m.estimated_cycles_encaps_or_sign,
                        "decaps_or_verify": m.estimated_cycles_decaps_or_verify,
                    },
                    "side_channel_protected": m.side_channel_protected,
                    "fault_protected": m.fault_protected,
                    "interface": m.interface,
                    "clock_mhz": m.clock_mhz,
                    "verilog_top": m.verilog_top,
                    "register_map": {
                        k: {"offset": v[0], "size": v[1]}
                        for k, v in m.register_map.items()
                    },
                }
            )
        return out

    def generate_c_header(self, module: PqcModule) -> str:
        """Generate a C header with register offsets for a module."""
        p = module.params
        guard = f"__{module.verilog_top.upper()}_REGS_H__"
        lines: list[str] = []
        lines.append(f"/* Auto-generated register header for {module.name} */")
        lines.append(f"/* {p.nist_doc} - NIST L{p.security_level_nist} */")
        lines.append(f"#ifndef {guard}")
        lines.append(f"#define {guard}")
        lines.append("")
        for reg, (off, sz) in module.register_map.items():
            lines.append(
                f"#define {module.verilog_top.upper()}_{reg}_OFFSET 0x{off:04X} /* {sz} bytes */"
            )
        lines.append("")
        lines.append("/* CTRL register bits */")
        if p.is_kem:
            lines.append(f"#define {module.verilog_top.upper()}_CTRL_START_KEYGEN  (1<<0)")
            lines.append(f"#define {module.verilog_top.upper()}_CTRL_START_ENCAPS  (1<<1)")
            lines.append(f"#define {module.verilog_top.upper()}_CTRL_START_DECAPS  (1<<2)")
        else:
            lines.append(f"#define {module.verilog_top.upper()}_CTRL_START_KEYGEN  (1<<0)")
            lines.append(f"#define {module.verilog_top.upper()}_CTRL_START_SIGN    (1<<1)")
            lines.append(f"#define {module.verilog_top.upper()}_CTRL_START_VERIFY  (1<<2)")
        lines.append(f"#define {module.verilog_top.upper()}_CTRL_CLEAR         (1<<3)")
        lines.append("")
        lines.append("/* STATUS register bits */")
        lines.append(f"#define {module.verilog_top.upper()}_STATUS_BUSY  (1<<0)")
        lines.append(f"#define {module.verilog_top.upper()}_STATUS_DONE  (1<<1)")
        lines.append(f"#define {module.verilog_top.upper()}_STATUS_ERROR (1<<2)")
        lines.append("")
        lines.append(f"#endif /* {guard} */")
        return "\n".join(lines)

    def write_catalog(self, output_dir: Path) -> list[Path]:
        """Write the full catalog (YAML + C headers + wrapper skeletons) to disk."""
        output_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        yaml_path = output_dir / "pqc_catalog.yaml"
        yaml_path.write_text(self.generate_catalog_yaml(), encoding="utf-8")
        written.append(yaml_path)
        for m in self._modules.values():
            hdr = output_dir / f"{m.verilog_top}_regs.h"
            hdr.write_text(self.generate_c_header(m), encoding="utf-8")
            written.append(hdr)
            wrap = output_dir / f"{m.verilog_top}_axi_slave.v"
            wrap.write_text(self.generate_axi_slave(m), encoding="utf-8")
            written.append(wrap)
        return written


def get_default_catalog() -> PqcCatalog:
    """Return a default catalog instance."""
    return PqcCatalog()


def list_all_algorithms() -> list[str]:
    """List all supported algorithm names."""
    return [a.value for a in PqcAlgorithm]


def get_params(algorithm: PqcAlgorithm | str) -> PqcParams:
    """Get parameter set by algorithm enum or name."""
    if isinstance(algorithm, str):
        for a in PqcAlgorithm:
            if a.value == algorithm:
                algorithm = a
                break
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}")
    return PQC_PARAMS[algorithm]


__all__ = [
    "PqcAlgorithm",
    "PqcFamily",
    "PqcParams",
    "PqcModule",
    "PqcCatalog",
    "PQC_PARAMS",
    "get_default_catalog",
    "list_all_algorithms",
    "get_params",
]
