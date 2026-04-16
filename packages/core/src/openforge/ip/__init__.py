"""Parametric IP generators for the block design editor."""

from openforge.ip.generators import (
    axi_lite_to_full_bridge,
    axi_smartconnect,
    axi_stream_broadcast,
    axi_stream_demux,
    axi_stream_fifo,
    axi_stream_mux,
    axi_stream_switch,
    bram_controller,
    clock_wizard,
    dma_engine,
    interrupt_controller_plic,
    reset_bridge,
    reset_synchronizer,
    rom_init,
)

__all__ = [
    "axi_smartconnect",
    "axi_lite_to_full_bridge",
    "axi_stream_fifo",
    "axi_stream_mux",
    "axi_stream_demux",
    "axi_stream_broadcast",
    "axi_stream_switch",
    "clock_wizard",
    "reset_synchronizer",
    "reset_bridge",
    "bram_controller",
    "rom_init",
    "dma_engine",
    "interrupt_controller_plic",
]
