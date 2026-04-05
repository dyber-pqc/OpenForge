"""Tests for the waveform loader (VCD parser)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from openforge.waveform.loader import (
    Signal,
    SignalType,
    TimeUnit,
    WaveformData,
    load_waveform,
)

SAMPLE_VCD = """\
$date
    Mon Apr 5 10:00:00 2026
$end
$version
    OpenForge VCD Generator
$end
$timescale 1ns $end
$scope module top $end
$var wire 1 ! clk $end
$var wire 1 " rst_n $end
$var reg 8 # count [7:0] $end
$upscope $end
$enddefinitions $end
$dumpvars
0!
0"
b00000000 #
$end
#0
0!
0"
b00000000 #
#5
1!
#10
0!
1"
#15
1!
b00000001 #
#20
0!
b00000010 #
#25
1!
b00000011 #
#30
0!
b00000100 #
#35
1!
#40
0!
#50
1!
b00001111 #
"""


def test_load_vcd_basic() -> None:
    with tempfile.NamedTemporaryFile(suffix=".vcd", mode="w", delete=False) as f:
        f.write(SAMPLE_VCD)
        f.flush()
        path = Path(f.name)

    try:
        data = load_waveform(path)

        assert data.timescale_unit == TimeUnit.NS
        assert data.timescale_magnitude == 1
        assert data.signal_count == 3
        assert data.total_time == 50

        clk = data.get_signal("clk")
        assert clk is not None
        assert clk.width == 1
        assert clk.signal_type == SignalType.WIRE
        assert clk.scope == "top"
        assert len(clk.changes) > 0

        count = data.get_signal("count")
        assert count is not None
        assert count.width == 8
        assert count.is_bus
        assert count.signal_type == SignalType.REG
    finally:
        path.unlink(missing_ok=True)


def test_signal_value_at_time() -> None:
    with tempfile.NamedTemporaryFile(suffix=".vcd", mode="w", delete=False) as f:
        f.write(SAMPLE_VCD)
        f.flush()
        path = Path(f.name)

    try:
        data = load_waveform(path)

        clk = data.get_signal("clk")
        assert clk is not None
        assert clk.value_at(0) == "0"
        assert clk.value_at(5) == "1"
        assert clk.value_at(10) == "0"
        assert clk.value_at(15) == "1"

        count = data.get_signal("count")
        assert count is not None
        assert count.value_at(0) == "00000000"
        assert count.value_at(15) == "00000001"
        assert count.value_at(50) == "00001111"
    finally:
        path.unlink(missing_ok=True)


def test_search_signals() -> None:
    with tempfile.NamedTemporaryFile(suffix=".vcd", mode="w", delete=False) as f:
        f.write(SAMPLE_VCD)
        f.flush()
        path = Path(f.name)

    try:
        data = load_waveform(path)

        results = data.search_signals("clk")
        assert len(results) == 1
        assert results[0].name == "clk"

        results = data.search_signals("count")
        assert len(results) == 1

        results = data.search_signals("nonexistent")
        assert len(results) == 0
    finally:
        path.unlink(missing_ok=True)


def test_time_range() -> None:
    with tempfile.NamedTemporaryFile(suffix=".vcd", mode="w", delete=False) as f:
        f.write(SAMPLE_VCD)
        f.flush()
        path = Path(f.name)

    try:
        data = load_waveform(path)
        min_t, max_t = data.time_range()
        assert min_t == 0
        assert max_t == 50
    finally:
        path.unlink(missing_ok=True)


def test_load_nonexistent_file() -> None:
    import pytest

    with pytest.raises(FileNotFoundError):
        load_waveform("/nonexistent/path.vcd")


def test_unsupported_format() -> None:
    import pytest

    with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as f:
        path = Path(f.name)

    try:
        with pytest.raises(ValueError, match="Unknown waveform format"):
            load_waveform(path)
    finally:
        path.unlink(missing_ok=True)
