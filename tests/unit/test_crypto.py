"""Tests for the crypto verification modules."""

from __future__ import annotations

import numpy as np

from openforge_crypto.side_channel import PowerTrace, SideChannelSimulator


def test_hamming_weight() -> None:
    assert SideChannelSimulator.hamming_weight(0) == 0
    assert SideChannelSimulator.hamming_weight(0xFF) == 8
    assert SideChannelSimulator.hamming_weight(0b10101010) == 4


def test_hamming_distance() -> None:
    assert SideChannelSimulator.hamming_distance(0x00, 0xFF) == 8
    assert SideChannelSimulator.hamming_distance(0xFF, 0xFF) == 0
    assert SideChannelSimulator.hamming_distance(0b1100, 0b0011) == 4


def test_tvla_no_leakage() -> None:
    """Random traces with no fixed/random distinction should show no leakage."""
    sim = SideChannelSimulator(power_model="hamming_weight")
    rng = np.random.default_rng(42)

    # Generate random traces -- all from the same distribution
    for _ in range(200):
        power = rng.normal(loc=50.0, scale=5.0, size=100)
        sim.add_trace(power, inputs={"key": rng.integers(0, 256)})

    # TVLA with a "fixed" input that doesn't actually exist should find nothing
    result = sim.run_tvla(fixed_input={"key": 999}, threshold=4.5)
    # With random data, we might get spurious leakage points, but max_t should be modest
    assert result.max_t < 10.0  # Very loose bound for random data


def test_power_trace_computation() -> None:
    sim = SideChannelSimulator(power_model="hamming_weight")

    # Two cycles, two registers each
    register_values = [
        [0xFF, 0x00],  # cycle 0: HW=8, HW=0 -> power=8
        [0x0F, 0xF0],  # cycle 1: HW=4, HW=4 -> power=8
    ]

    trace = sim.compute_power_trace(register_values)
    assert len(trace) == 2
    assert trace[0] == 8.0  # HW(0xFF) + HW(0x00)
    assert trace[1] == 8.0  # HW(0x0F) + HW(0xF0)


def test_power_trace_hamming_distance() -> None:
    sim = SideChannelSimulator(power_model="hamming_distance")

    register_values = [
        [0x00, 0x00],  # cycle 0: HD from 0 -> power = 0
        [0xFF, 0xFF],  # cycle 1: HD(0xFF^0x00)=8 + HD(0xFF^0x00)=8 -> 16
    ]

    trace = sim.compute_power_trace(register_values)
    assert trace[0] == 0.0
    assert trace[1] == 16.0
