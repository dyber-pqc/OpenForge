"""Project management for OpenForge EDA."""

from __future__ import annotations

from pathlib import Path

from openforge.config.loader import load_config
from openforge.config.schema import OpenForgeConfig


class Project:
    """Represents an OpenForge EDA project."""

    def __init__(self, path: Path, config: OpenForgeConfig) -> None:
        self.path = path
        self.config = config

    @classmethod
    def load(cls, path: str | Path) -> Project:
        """Load a project from a directory."""
        path = Path(path)
        config = load_config(path)
        return cls(path=path, config=config)

    @property
    def name(self) -> str:
        return self.config.project.name

    @property
    def top_module(self) -> str:
        return self.config.project.top_module

    def source_files(self) -> list[Path]:
        """Resolve source file globs to actual file paths."""
        files = []
        for pattern in self.config.design.sources:
            files.extend(self.path.glob(pattern))
        return sorted(files)

    def constraint_files(self) -> list[Path]:
        """Resolve constraint file paths."""
        return [self.path / c for c in self.config.design.constraints if (self.path / c).exists()]
