"""UVM-lite: a Verilator-friendly subset of UVM structure for OpenForge.

This is NOT a real UVM implementation. It ships a small SystemVerilog package
(``uvm_lite_pkg``) plus agent generators that compile cleanly with Verilator
5.x. The SV source is embedded as Python string constants in ``library.py`` so
it can be dropped onto disk on demand.
"""

from __future__ import annotations

from openforge.verification.uvm_lite.agents import (
    AgentSpec,
    generate_agent,
    get_protocol_template,
    list_protocols,
)
from openforge.verification.uvm_lite.library import (
    UVM_LITE_AGENT_TEMPLATE,
    UVM_LITE_BASE,
    generate_test_skeleton,
    write_uvm_lite_library,
)

__all__ = [
    "AgentSpec",
    "UVM_LITE_AGENT_TEMPLATE",
    "UVM_LITE_BASE",
    "generate_agent",
    "generate_test_skeleton",
    "get_protocol_template",
    "list_protocols",
    "write_uvm_lite_library",
]
