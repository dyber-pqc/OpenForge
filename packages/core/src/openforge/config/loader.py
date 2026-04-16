"""Locate and load ``openforge.yaml`` project configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Final

import yaml

from openforge.config.schema import OpenForgeConfig

CONFIG_FILENAMES: Final[tuple[str, ...]] = (
    "openforge.yaml",
    "openforge.yml",
    ".openforge.yaml",
    ".openforge.yml",
)


class ConfigNotFoundError(FileNotFoundError):
    """Raised when no openforge.yaml can be found in the search path."""


def find_config(start: Path | str = ".") -> Path:
    """Walk *start* and its parents looking for an OpenForge config file.

    Returns the resolved path to the first matching file, or raises
    :class:`ConfigNotFoundError`.
    """
    current = Path(start).resolve()
    while True:
        for name in CONFIG_FILENAMES:
            candidate = current / name
            if candidate.is_file():
                return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    raise ConfigNotFoundError(
        f"No OpenForge config found in {Path(start).resolve()} or any parent directory. "
        f"Expected one of: {', '.join(CONFIG_FILENAMES)}"
    )


def load_config(
    path: Path | str | None = None,
    *,
    search_dir: Path | str = ".",
) -> OpenForgeConfig:
    """Load and validate an OpenForge project configuration.

    Parameters
    ----------
    path:
        Explicit path to an ``openforge.yaml`` file.  When *None* the
        loader searches *search_dir* and its parents automatically.
    search_dir:
        Starting directory for automatic config discovery (default: cwd).

    Returns
    -------
    OpenForgeConfig
        Fully validated configuration instance.
    """
    path = find_config(search_dir) if path is None else Path(path)

    if not path.is_file():
        raise ConfigNotFoundError(f"Config file does not exist: {path}")

    raw = path.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    if data is None:
        data = {}

    return OpenForgeConfig.model_validate(data)
