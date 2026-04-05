"""Tests for OpenForge config schema and loader."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from openforge.config.loader import load_config
from openforge.config.schema import OpenForgeConfig


MINIMAL_YAML = """\
project:
  name: test-project
  top_module: test_top
  target_pdk: sky130

design:
  sources:
    - src/*.v
"""

FULL_YAML = """\
project:
  name: crypto-test
  top_module: crypto_top
  target_pdk: sky130

design:
  sources:
    - src/rtl/*.sv
  includes:
    - src/include/
  constraints:
    - constraints/timing.sdc

verification:
  simulation:
    tool: verilator
    testbenches:
      - tb/test_tb.py
    coverage:
      line: true
      toggle: true

  formal:
    tool: symbiyosys
    properties:
      - formal/props.sv
    depth: 50

  crypto_verification:
    constant_time:
      enabled: true
      secrets:
        - key_reg
      public:
        - ciphertext

    side_channel:
      enabled: true
      power_model: hamming_distance
      tvla_threshold: 4.5
      num_traces: 5000

analysis:
  timing:
    tool: opensta
    clock_period: "10.0ns"
"""


def test_minimal_config_parses() -> None:
    config = OpenForgeConfig.model_validate({
        "project": {"name": "test", "top_module": "top", "target_pdk": "sky130"},
        "design": {"sources": ["src/*.v"]},
    })
    assert config.project.name == "test"
    assert config.project.top_module == "top"
    assert config.design.sources == ["src/*.v"]


def test_full_config_parses() -> None:
    import yaml

    data = yaml.safe_load(FULL_YAML)
    config = OpenForgeConfig.model_validate(data)

    assert config.project.name == "crypto-test"
    assert config.project.target_pdk == "sky130"
    assert config.verification is not None
    assert config.verification.simulation is not None
    assert config.verification.simulation.tool == "verilator"
    assert config.verification.formal is not None
    assert config.verification.formal.depth == 50
    assert config.verification.crypto_verification is not None
    assert config.verification.crypto_verification.constant_time is not None
    assert config.verification.crypto_verification.constant_time.enabled is True
    assert "key_reg" in config.verification.crypto_verification.constant_time.secrets


def test_load_config_from_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "openforge.yaml"
        config_path.write_text(MINIMAL_YAML)

        config = load_config(Path(tmpdir))
        assert config.project.name == "test-project"


def test_load_config_missing_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        with pytest.raises(FileNotFoundError):
            load_config(Path(tmpdir))


def test_defaults_applied() -> None:
    config = OpenForgeConfig.model_validate({
        "project": {"name": "test", "top_module": "top"},
        "design": {"sources": ["*.v"]},
    })
    # Defaults
    assert config.design.includes == []
    assert config.design.constraints == []
    assert config.verification is None or config.verification.simulation is None
