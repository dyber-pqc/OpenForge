"""OpenForge project configuration loading and schema."""

from openforge.config.loader import load_config
from openforge.config.schema import OpenForgeConfig

__all__ = ["OpenForgeConfig", "load_config"]
