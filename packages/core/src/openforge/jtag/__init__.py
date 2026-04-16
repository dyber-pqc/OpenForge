"""JTAG bridge subpackage - adapter discovery, scan chain, IR/DR access.

This is the high-level in-system JTAG interface used by the ILA reader
and other debug tools. The low-level programming paths (SVF playback,
bitstream download) still live in :mod:`openforge.fpga.jtag`.
"""

from openforge.jtag.bridge import (
    KNOWN_ADAPTERS,
    KNOWN_IDCODES,
    JtagAdapter,
    JtagBridge,
    JtagDevice,
    lookup_idcode,
)

__all__ = [
    "JtagAdapter",
    "JtagDevice",
    "JtagBridge",
    "KNOWN_ADAPTERS",
    "KNOWN_IDCODES",
    "lookup_idcode",
]
