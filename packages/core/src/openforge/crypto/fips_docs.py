"""FIPS 140-3 Security Policy document generator.

Generates NIST FIPS 140-3 compliance documentation templates, including:
- Security Policy (SP)
- Finite State Model (FSM) in DOT format
- Test requirements tracker
- Operator roles & services tables
- CSP (Critical Security Parameter) inventory

Reference: NIST SP 800-140x, FIPS 140-3 Implementation Guidance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CryptoKeyInfo:
    name: str
    algorithm: str
    length_bits: int
    generation: str  # "Internally generated" / "Imported"
    storage: str  # "Plaintext RAM" / "Encrypted" / "KEK-wrapped"
    zeroization: str  # "On reset" / "On zeroize command" / "On tamper"
    usage: str
    access_roles: list[str] = field(default_factory=list)


@dataclass
class CspInfo:
    """Critical Security Parameter."""

    name: str
    type: str  # "Key" / "Password" / "Authentication data" / "Seed"
    algorithm: str
    length_bits: int
    input_method: str
    output_method: str
    zeroization: str
    access_control: str


@dataclass
class FipsServiceInfo:
    name: str
    description: str
    roles_allowed: list[str]
    csps_accessed: list[str]
    access_type: str  # "R" / "W" / "RW" / "Z"
    approved: bool = True


@dataclass
class FipsModuleInfo:
    name: str
    version: str
    type: str = "Hardware"
    embodiment: str = "Single-Chip"
    security_level_overall: int = 1
    security_level_design: int = 1
    security_level_roles: int = 1
    security_level_states: int = 1
    security_level_io: int = 1
    security_level_keys: int = 1
    security_level_emi: int = 1
    security_level_self_test: int = 1
    security_level_lifecycle: int = 1
    security_level_mitigation: int = 1

    vendor: str = "OpenForge"
    fips_doc_version: str = "1.0"
    target_platform: str = "ASIC (Sky130 65nm)"
    identification: str = ""

    approved_algorithms: list[str] = field(default_factory=list)
    non_approved_allowed: list[str] = field(default_factory=list)
    non_approved_not_allowed: list[str] = field(default_factory=list)

    cryptographic_keys: list[dict] = field(default_factory=list)
    csps: list[dict] = field(default_factory=list)

    ports: list[dict] = field(default_factory=list)
    roles: list[str] = field(default_factory=lambda: ["Crypto Officer", "User"])
    services: list[dict] = field(default_factory=list)

    operational_environment: str = "N/A (Hardware)"
    physical_security: str = "Production-grade components"
    emi_compliance: str = "47 CFR FCC Part 15, Class B"
    self_tests: list[dict] = field(default_factory=list)
    lifecycle_assurance: list[str] = field(default_factory=list)
    mitigations: list[str] = field(default_factory=list)


@dataclass
class FipsTestRequirement:
    section: str
    requirement: str
    test_method: str
    status: str = "Not Tested"
    evidence: str = ""
    notes: str = ""


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


_SECURITY_LEVEL_DESCR = {
    1: "Level 1 - Basic security requirements.",
    2: "Level 2 - Role-based authentication, tamper-evidence.",
    3: "Level 3 - Identity-based authentication, tamper-resistance, physical isolation.",
    4: "Level 4 - Envelope protection, environmental failure protection.",
}


class FipsDocGenerator:
    """Generate FIPS 140-3 Security Policy documents."""

    def __init__(self) -> None:
        self._date = datetime.utcnow().strftime("%Y-%m-%d")

    # -- Section builders ----------------------------------------------------

    def _header(self, module: FipsModuleInfo) -> str:
        lines: list[str] = []
        lines.append(f"# FIPS 140-3 Non-Proprietary Security Policy")
        lines.append("")
        lines.append(f"## {module.name}")
        lines.append("")
        lines.append(f"**Version:** {module.version}  ")
        lines.append(f"**Document version:** {module.fips_doc_version}  ")
        lines.append(f"**Vendor:** {module.vendor}  ")
        lines.append(f"**Date:** {self._date}  ")
        lines.append(f"**Overall Security Level:** Level {module.security_level_overall}")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## 1. Introduction")
        lines.append("")
        lines.append(
            "This document is the non-proprietary FIPS 140-3 Security Policy for the "
            f"{module.name} cryptographic module, and it describes how the module "
            "complies with the requirements of FIPS 140-3."
        )
        lines.append("")
        lines.append("### 1.1 Hardware and Physical Cryptographic Boundary")
        lines.append("")
        lines.append(
            f"The cryptographic boundary of the {module.name} is the physical "
            f"perimeter of the {module.type.lower()} module implemented as a "
            f"{module.embodiment.lower()}."
        )
        lines.append("")
        lines.append(f"**Target platform:** {module.target_platform}")
        lines.append("")
        return "\n".join(lines)

    def _section_security_levels(self, module: FipsModuleInfo) -> str:
        lines: list[str] = []
        lines.append("## 2. Cryptographic Module Specification")
        lines.append("")
        lines.append("### 2.1 Security Level by Area")
        lines.append("")
        lines.append("| ISO/IEC 19790 Section | Security Level |")
        lines.append("|---|---|")
        lines.append(f"| 1 - Cryptographic module specification | {module.security_level_design} |")
        lines.append(f"| 2 - Cryptographic module interfaces | {module.security_level_io} |")
        lines.append(f"| 3 - Roles, services, and authentication | {module.security_level_roles} |")
        lines.append(f"| 4 - Software/firmware security | N/A |")
        lines.append(f"| 5 - Operational environment | N/A |")
        lines.append(f"| 6 - Physical security | {module.security_level_design} |")
        lines.append(f"| 7 - Non-invasive security | {module.security_level_mitigation} |")
        lines.append(f"| 8 - SSP management | {module.security_level_keys} |")
        lines.append(f"| 9 - Self-tests | {module.security_level_self_test} |")
        lines.append(f"| 10 - Life-cycle assurance | {module.security_level_lifecycle} |")
        lines.append(f"| 11 - Mitigation of other attacks | {module.security_level_mitigation} |")
        lines.append(f"| **Overall** | **{module.security_level_overall}** |")
        lines.append("")
        lines.append(
            f"Overall level: {_SECURITY_LEVEL_DESCR.get(module.security_level_overall, '')}"
        )
        lines.append("")
        return "\n".join(lines)

    def _section_algorithms(self, module: FipsModuleInfo) -> str:
        lines: list[str] = []
        lines.append("### 2.2 Cryptographic Algorithms")
        lines.append("")
        lines.append("#### 2.2.1 Approved Algorithms")
        lines.append("")
        if module.approved_algorithms:
            lines.append("| Algorithm | Standard | Use | CAVP Cert |")
            lines.append("|---|---|---|---|")
            for a in module.approved_algorithms:
                lines.append(f"| {a} | FIPS / SP 800 | General | Pending |")
        else:
            lines.append("_None declared._")
        lines.append("")
        lines.append("#### 2.2.2 Non-Approved but Allowed Algorithms")
        lines.append("")
        if module.non_approved_allowed:
            for a in module.non_approved_allowed:
                lines.append(f"- {a}")
        else:
            lines.append("_None._")
        lines.append("")
        lines.append("#### 2.2.3 Non-Approved / Not Allowed Algorithms")
        lines.append("")
        if module.non_approved_not_allowed:
            for a in module.non_approved_not_allowed:
                lines.append(f"- {a}")
        else:
            lines.append("_None._")
        lines.append("")
        return "\n".join(lines)

    def _section_ports(self, module: FipsModuleInfo) -> str:
        lines: list[str] = []
        lines.append("## 3. Module Ports and Interfaces")
        lines.append("")
        lines.append("| Port | Direction | Logical Interface | Description |")
        lines.append("|---|---|---|---|")
        if module.ports:
            for p in module.ports:
                lines.append(
                    f"| {p.get('name', '')} | {p.get('direction', '')} | "
                    f"{p.get('interface', '')} | {p.get('description', '')} |"
                )
        else:
            lines.append("| axi_* | bidir | Data/Control | AXI4-Lite slave |")
            lines.append("| clk | in | Clock | System clock |")
            lines.append("| rst_n | in | Control | Reset (active low) |")
            lines.append("| irq | out | Status | Completion interrupt |")
        lines.append("")
        return "\n".join(lines)

    def _section_roles_services(self, module: FipsModuleInfo) -> str:
        lines: list[str] = []
        lines.append("## 4. Roles, Services, and Authentication")
        lines.append("")
        lines.append("### 4.1 Roles")
        lines.append("")
        for r in module.roles:
            lines.append(f"- **{r}**")
        lines.append("")
        lines.append("### 4.2 Authentication")
        lines.append("")
        if module.security_level_roles >= 2:
            lines.append("Role-based authentication via pre-shared credential.")
        else:
            lines.append("No authentication required at Level 1.")
        lines.append("")
        lines.append("### 4.3 Services")
        lines.append("")
        lines.append("| Service | Roles | CSPs Accessed | Access | Approved |")
        lines.append("|---|---|---|---|---|")
        if module.services:
            for s in module.services:
                roles = ", ".join(s.get("roles", []))
                csps = ", ".join(s.get("csps", []))
                lines.append(
                    f"| {s.get('name', '')} | {roles} | {csps} | "
                    f"{s.get('access', '')} | {'Yes' if s.get('approved', True) else 'No'} |"
                )
        else:
            lines.append("| Show Status | CO, User | - | R | Yes |")
            lines.append("| Self-Test | CO | - | - | Yes |")
            lines.append("| Zeroize | CO | All keys | Z | Yes |")
        lines.append("")
        return "\n".join(lines)

    def _section_keys(self, module: FipsModuleInfo) -> str:
        lines: list[str] = []
        lines.append("## 5. Sensitive Security Parameters (SSPs)")
        lines.append("")
        lines.append("### 5.1 Cryptographic Keys")
        lines.append("")
        if module.cryptographic_keys:
            lines.append("| Key | Algorithm | Size | Generation | Storage | Zeroization |")
            lines.append("|---|---|---|---|---|---|")
            for k in module.cryptographic_keys:
                lines.append(
                    f"| {k.get('name', '')} | {k.get('algorithm', '')} | "
                    f"{k.get('length_bits', 0)} bits | {k.get('generation', '')} | "
                    f"{k.get('storage', '')} | {k.get('zeroization', '')} |"
                )
        else:
            lines.append("_No keys declared._")
        lines.append("")
        lines.append("### 5.2 Critical Security Parameters")
        lines.append("")
        if module.csps:
            lines.append("| CSP | Type | Algorithm | Length | Access |")
            lines.append("|---|---|---|---|---|")
            for c in module.csps:
                lines.append(
                    f"| {c.get('name', '')} | {c.get('type', '')} | "
                    f"{c.get('algorithm', '')} | {c.get('length_bits', 0)} | "
                    f"{c.get('access_control', '')} |"
                )
        else:
            lines.append("_No CSPs declared._")
        lines.append("")
        return "\n".join(lines)

    def _section_environment(self, module: FipsModuleInfo) -> str:
        lines: list[str] = []
        lines.append("## 6. Operational Environment")
        lines.append("")
        lines.append(module.operational_environment)
        lines.append("")
        return "\n".join(lines)

    def _section_physical(self, module: FipsModuleInfo) -> str:
        lines: list[str] = []
        lines.append("## 7. Physical Security")
        lines.append("")
        lines.append(module.physical_security)
        lines.append("")
        lines.append("## 8. Non-Invasive Security")
        lines.append("")
        if module.security_level_mitigation >= 2:
            lines.append("Side-channel mitigations: power analysis countermeasures, EM shielding.")
        else:
            lines.append("No specific non-invasive countermeasures claimed at this level.")
        lines.append("")
        lines.append("## 9. EMI/EMC")
        lines.append("")
        lines.append(module.emi_compliance)
        lines.append("")
        return "\n".join(lines)

    def _section_self_tests(self, module: FipsModuleInfo) -> str:
        lines: list[str] = []
        lines.append("## 10. Self-Tests")
        lines.append("")
        lines.append("### 10.1 Pre-Operational Self-Tests")
        lines.append("")
        lines.append("- Integrity Test: CRC-32 over module firmware/configuration.")
        lines.append("- Cryptographic Algorithm Self-Test (CAST) for each approved algorithm.")
        lines.append("")
        lines.append("### 10.2 Conditional Self-Tests")
        lines.append("")
        lines.append("- Pairwise consistency test on key generation.")
        lines.append("- Continuous RNG test.")
        lines.append("")
        if module.self_tests:
            lines.append("### 10.3 Self-Test Table")
            lines.append("")
            lines.append("| Test | Type | Algorithm | Result |")
            lines.append("|---|---|---|---|")
            for t in module.self_tests:
                lines.append(
                    f"| {t.get('name', '')} | {t.get('type', '')} | "
                    f"{t.get('algorithm', '')} | {t.get('status', 'N/A')} |"
                )
            lines.append("")
        return "\n".join(lines)

    def _section_lifecycle(self, module: FipsModuleInfo) -> str:
        lines: list[str] = []
        lines.append("## 11. Life-Cycle Assurance")
        lines.append("")
        if module.lifecycle_assurance:
            for item in module.lifecycle_assurance:
                lines.append(f"- {item}")
        else:
            lines.append("- Configuration management via Git.")
            lines.append("- Secure delivery through signed artifacts.")
            lines.append("- End-of-life zeroization procedures documented in vendor manual.")
        lines.append("")
        return "\n".join(lines)

    def _section_mitigations(self, module: FipsModuleInfo) -> str:
        lines: list[str] = []
        lines.append("## 12. Mitigation of Other Attacks")
        lines.append("")
        if module.mitigations:
            for m in module.mitigations:
                lines.append(f"- {m}")
        else:
            lines.append("No mitigations of other attacks claimed.")
        lines.append("")
        return "\n".join(lines)

    def _section_references(self) -> str:
        lines: list[str] = []
        lines.append("## 13. References")
        lines.append("")
        lines.append("- FIPS 140-3, Security Requirements for Cryptographic Modules (NIST)")
        lines.append("- ISO/IEC 19790:2012, Security requirements for cryptographic modules")
        lines.append("- NIST SP 800-140, 800-140A through 800-140F")
        lines.append("- FIPS 203, Module-Lattice-Based Key-Encapsulation Mechanism")
        lines.append("- FIPS 204, Module-Lattice-Based Digital Signature Algorithm")
        lines.append("- FIPS 205, Stateless Hash-Based Digital Signature Algorithm")
        lines.append("")
        return "\n".join(lines)

    # -- Top-level API -------------------------------------------------------

    def generate_security_policy(
        self,
        module: FipsModuleInfo,
        output_dir: Path,
    ) -> Path:
        """Generate a complete FIPS 140-3 Security Policy document."""
        output_dir.mkdir(parents=True, exist_ok=True)
        parts = [
            self._header(module),
            self._section_security_levels(module),
            self._section_algorithms(module),
            self._section_ports(module),
            self._section_roles_services(module),
            self._section_keys(module),
            self._section_environment(module),
            self._section_physical(module),
            self._section_self_tests(module),
            self._section_lifecycle(module),
            self._section_mitigations(module),
            self._section_references(),
        ]
        doc = "\n".join(parts)
        out = output_dir / f"{module.name.replace(' ', '_')}_SecurityPolicy.md"
        out.write_text(doc, encoding="utf-8")
        return out

    def generate_test_report(
        self,
        requirements: list[FipsTestRequirement],
        output: Path,
    ) -> Path:
        """Generate a FIPS 140-3 test requirements tracker."""
        lines: list[str] = []
        lines.append("# FIPS 140-3 Test Requirements Report")
        lines.append("")
        lines.append(f"**Date:** {self._date}")
        lines.append("")
        total = len(requirements)
        passed = sum(1 for r in requirements if r.status == "Pass")
        failed = sum(1 for r in requirements if r.status == "Fail")
        na = sum(1 for r in requirements if r.status == "N/A")
        not_tested = sum(1 for r in requirements if r.status == "Not Tested")
        lines.append(f"- Total: {total}")
        lines.append(f"- Pass: {passed}")
        lines.append(f"- Fail: {failed}")
        lines.append(f"- N/A: {na}")
        lines.append(f"- Not tested: {not_tested}")
        lines.append("")
        lines.append("| Section | Requirement | Test Method | Status | Evidence |")
        lines.append("|---|---|---|---|---|")
        for r in requirements:
            req = r.requirement.replace("|", "\\|")
            tm = r.test_method.replace("|", "\\|")
            ev = r.evidence.replace("|", "\\|")
            lines.append(f"| {r.section} | {req} | {tm} | {r.status} | {ev} |")
        lines.append("")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines), encoding="utf-8")
        return output

    def generate_finite_state_model(
        self,
        states: list[str],
        transitions: list[tuple[str, str, str]],
        output: Path,
    ) -> Path:
        """Generate FSM diagram in Graphviz DOT format."""
        lines: list[str] = []
        lines.append("digraph FIPS_FSM {")
        lines.append('    rankdir=LR;')
        lines.append('    node [shape=ellipse, fontname="Helvetica"];')
        for s in states:
            safe = s.replace(" ", "_")
            lines.append(f'    {safe} [label="{s}"];')
        for src, dst, ev in transitions:
            s1 = src.replace(" ", "_")
            s2 = dst.replace(" ", "_")
            lines.append(f'    {s1} -> {s2} [label="{ev}"];')
        lines.append("}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines), encoding="utf-8")
        return output

    def generate_csp_inventory(
        self,
        csps: list[CspInfo],
        output: Path,
    ) -> Path:
        """Generate a CSP inventory table."""
        lines: list[str] = []
        lines.append("# Critical Security Parameter Inventory")
        lines.append("")
        lines.append("| Name | Type | Algorithm | Length (bits) | Input | Output | Zeroization | Access |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for c in csps:
            lines.append(
                f"| {c.name} | {c.type} | {c.algorithm} | {c.length_bits} | "
                f"{c.input_method} | {c.output_method} | {c.zeroization} | "
                f"{c.access_control} |"
            )
        lines.append("")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines), encoding="utf-8")
        return output


def default_test_requirements() -> list[FipsTestRequirement]:
    """Return a baseline set of FIPS 140-3 test requirements."""
    return [
        FipsTestRequirement("AS01", "Module specification document", "Document review"),
        FipsTestRequirement("AS02", "Module boundary identified", "Design review"),
        FipsTestRequirement("AS03", "Approved algorithms only", "Algorithm enumeration"),
        FipsTestRequirement("AS04", "Interface separation", "I/O testing"),
        FipsTestRequirement("AS05", "Role-based access control", "Access test"),
        FipsTestRequirement("AS06", "Zeroization procedures", "Zeroize test"),
        FipsTestRequirement("AS07", "Pre-op self-tests", "Self-test execution"),
        FipsTestRequirement("AS08", "Conditional self-tests", "Self-test execution"),
        FipsTestRequirement("AS09", "CSP protection", "CSP flow analysis"),
        FipsTestRequirement("AS10", "Physical tamper evidence", "Physical inspection"),
        FipsTestRequirement("AS11", "EMI compliance", "EMC lab test"),
        FipsTestRequirement("AS12", "Life-cycle documentation", "Document review"),
    ]


def default_fsm() -> tuple[list[str], list[tuple[str, str, str]]]:
    """Default FIPS module FSM: Power On -> Self-Test -> Idle -> Crypto -> Error/Zeroize."""
    states = [
        "Power On",
        "Pre-Op Self-Test",
        "Idle",
        "Crypto Service",
        "Error",
        "Zeroize",
    ]
    transitions = [
        ("Power On", "Pre-Op Self-Test", "reset deasserted"),
        ("Pre-Op Self-Test", "Idle", "all tests pass"),
        ("Pre-Op Self-Test", "Error", "test failure"),
        ("Idle", "Crypto Service", "service request"),
        ("Crypto Service", "Idle", "service complete"),
        ("Crypto Service", "Error", "runtime failure"),
        ("Idle", "Zeroize", "zeroize command"),
        ("Error", "Zeroize", "zeroize command"),
        ("Zeroize", "Power On", "reset"),
    ]
    return states, transitions


__all__ = [
    "CryptoKeyInfo",
    "CspInfo",
    "FipsServiceInfo",
    "FipsModuleInfo",
    "FipsTestRequirement",
    "FipsDocGenerator",
    "default_test_requirements",
    "default_fsm",
]
