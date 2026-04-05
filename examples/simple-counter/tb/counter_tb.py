"""Simple counter testbench using Cocotb."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles


@cocotb.test()
async def test_counter_reset(dut):
    """Test that counter resets to zero."""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    dut.rst_n.value = 0
    dut.enable.value = 0
    await ClockCycles(dut.clk, 5)

    assert dut.count.value == 0, "Counter should be 0 after reset"

    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 1)


@cocotb.test()
async def test_counter_increment(dut):
    """Test that counter increments when enabled."""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    dut.rst_n.value = 0
    dut.enable.value = 0
    await ClockCycles(dut.clk, 5)

    dut.rst_n.value = 1
    dut.enable.value = 1
    await ClockCycles(dut.clk, 1)

    for expected in range(1, 20):
        await RisingEdge(dut.clk)
        assert dut.count.value == expected, f"Expected {expected}, got {dut.count.value}"


@cocotb.test()
async def test_counter_overflow(dut):
    """Test overflow signal at max count."""
    clock = Clock(dut.clk, 10, units="ns")
    cocotb.start_soon(clock.start())

    dut.rst_n.value = 0
    dut.enable.value = 0
    await ClockCycles(dut.clk, 5)

    dut.rst_n.value = 1
    dut.enable.value = 1

    # Count to 255
    await ClockCycles(dut.clk, 256)
    assert dut.overflow.value == 1, "Overflow should be high at max count"
