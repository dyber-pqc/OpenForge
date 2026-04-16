"""Incremental synthesis support.

Tracks per-module source and config hashes so subsequent synthesis runs
only rebuild modules whose inputs have changed.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Iterable


@dataclass
class ModuleSignature:
    """Cached signature of a previously-synthesized module."""

    name: str
    source_hash: str  # SHA256 of source files
    config_hash: str  # SHA256 of synthesis config
    netlist_path: Path
    timestamp: float
    cell_count: int
    area: float

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "source_hash": self.source_hash,
            "config_hash": self.config_hash,
            "netlist_path": str(self.netlist_path),
            "timestamp": self.timestamp,
            "cell_count": self.cell_count,
            "area": self.area,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ModuleSignature":
        return cls(
            name=data["name"],
            source_hash=data["source_hash"],
            config_hash=data["config_hash"],
            netlist_path=Path(data["netlist_path"]),
            timestamp=float(data.get("timestamp", 0.0)),
            cell_count=int(data.get("cell_count", 0)),
            area=float(data.get("area", 0.0)),
        )

    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.timestamp)


@dataclass
class IncrementalCache:
    """Cache of previously-synthesized module signatures.

    Persisted as JSON. Use :class:`IncrementalSynthesizer` for the
    full workflow.
    """

    modules: dict[str, ModuleSignature] = field(default_factory=dict)
    version: int = 1

    def save(self, path: Path) -> None:
        """Save cache to JSON at ``path``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.version,
            "modules": {k: v.to_dict() for k, v in self.modules.items()},
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "IncrementalCache":
        """Load cache from JSON. Returns an empty cache if missing/corrupt."""
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        modules_raw = data.get("modules", {})
        modules: dict[str, ModuleSignature] = {}
        for name, sig_data in modules_raw.items():
            try:
                modules[name] = ModuleSignature.from_dict(sig_data)
            except (KeyError, ValueError, TypeError):
                continue
        return cls(modules=modules, version=int(data.get("version", 1)))

    def get(self, module_name: str) -> Optional[ModuleSignature]:
        return self.modules.get(module_name)

    def put(self, sig: ModuleSignature) -> None:
        self.modules[sig.name] = sig

    def remove(self, module_name: str) -> bool:
        return self.modules.pop(module_name, None) is not None

    def clear(self) -> None:
        self.modules.clear()

    def names(self) -> list[str]:
        return list(self.modules.keys())

    def __len__(self) -> int:
        return len(self.modules)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self.modules

    def is_valid(
        self, module_name: str, source_hash: str, config_hash: str
    ) -> bool:
        """True if cache hit and netlist still exists on disk."""
        sig = self.get(module_name)
        if sig is None:
            return False
        if sig.source_hash != source_hash or sig.config_hash != config_hash:
            return False
        return sig.netlist_path.exists()


def compute_source_hash(sources: Iterable[Path]) -> str:
    """Combined SHA256 hash of source file contents.

    Files are read in sorted order so the result is deterministic. Missing
    files are skipped (but the missing path itself contributes to the
    hash, so changes from missing -> present are detected).
    """
    h = hashlib.sha256()
    paths = sorted(Path(p) for p in sources)
    for src in paths:
        h.update(str(src).encode("utf-8"))
        h.update(b"\0")
        if src.exists() and src.is_file():
            try:
                h.update(src.read_bytes())
            except OSError:
                h.update(b"<unreadable>")
        else:
            h.update(b"<missing>")
        h.update(b"\n")
    return h.hexdigest()


def compute_config_hash(config: dict) -> str:
    """SHA256 over a canonical JSON encoding of ``config``."""
    canonical = json.dumps(config, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_text_hash(text: str) -> str:
    """SHA256 hash of an arbitrary string (UTF-8)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class IncrementalReport:
    """Summary of an incremental analysis."""

    rebuilt: list[str] = field(default_factory=list)
    reused: list[str] = field(default_factory=list)
    invalidated: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.rebuilt) + len(self.reused)

    @property
    def speedup_ratio(self) -> float:
        if self.total == 0:
            return 1.0
        return self.total / max(1, len(self.rebuilt))

    def summary(self) -> str:
        return (
            f"Incremental synthesis: {len(self.reused)} reused, "
            f"{len(self.rebuilt)} rebuilt "
            f"({self.speedup_ratio:.1f}x speedup)"
        )


class IncrementalSynthesizer:
    """Drives incremental synthesis runs.

    Typical usage:

        synth = IncrementalSynthesizer(project_root)
        for mod, sources in modules.items():
            if synth.needs_rebuild(mod, sources, config):
                run_yosys(...)
                synth.mark_built(mod, sources, config, netlist, n_cells, area)
        synth.save_cache()
    """

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self.cache_path = self.project_root / ".openforge" / "incremental_cache.json"
        if self.cache_path.exists():
            self.cache = IncrementalCache.load(self.cache_path)
        else:
            self.cache = IncrementalCache()

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    def needs_rebuild(
        self,
        module_name: str,
        sources: list[Path],
        config: dict,
    ) -> bool:
        """Return True if ``module_name`` must be re-synthesized."""
        src_hash = compute_source_hash(sources)
        cfg_hash = compute_config_hash(config)
        return not self.cache.is_valid(module_name, src_hash, cfg_hash)

    def get_changed_modules(
        self,
        all_modules: dict[str, list[Path]],
        config: dict,
    ) -> list[str]:
        """Return names of modules that need rebuilding."""
        changed: list[str] = []
        for name, sources in all_modules.items():
            if self.needs_rebuild(name, sources, config):
                changed.append(name)
        return changed

    def analyze(
        self,
        all_modules: dict[str, list[Path]],
        config: dict,
    ) -> IncrementalReport:
        """Run a full analysis of which modules are stale."""
        report = IncrementalReport()
        cfg_hash = compute_config_hash(config)
        for name, sources in all_modules.items():
            src_hash = compute_source_hash(sources)
            if self.cache.is_valid(name, src_hash, cfg_hash):
                report.reused.append(name)
            else:
                if name in self.cache:
                    report.invalidated.append(name)
                report.rebuilt.append(name)
        return report

    def get_signature(self, module_name: str) -> Optional[ModuleSignature]:
        return self.cache.get(module_name)

    # ------------------------------------------------------------------ #
    # Mutations
    # ------------------------------------------------------------------ #
    def mark_built(
        self,
        module_name: str,
        sources: list[Path],
        config: dict,
        netlist: Path,
        cell_count: int,
        area: float,
    ) -> ModuleSignature:
        """Record that ``module_name`` was successfully synthesized."""
        sig = ModuleSignature(
            name=module_name,
            source_hash=compute_source_hash(sources),
            config_hash=compute_config_hash(config),
            netlist_path=Path(netlist),
            timestamp=time.time(),
            cell_count=int(cell_count),
            area=float(area),
        )
        self.cache.put(sig)
        return sig

    def invalidate(self, module_name: Optional[str] = None) -> None:
        """Invalidate cache for one module, or all when ``None``."""
        if module_name is None:
            self.cache.clear()
        else:
            self.cache.remove(module_name)

    def prune_missing_netlists(self) -> int:
        """Drop entries whose netlist file no longer exists. Returns count."""
        stale = [
            name
            for name, sig in self.cache.modules.items()
            if not sig.netlist_path.exists()
        ]
        for name in stale:
            self.cache.remove(name)
        return len(stale)

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def save_cache(self) -> None:
        """Write the cache back to disk."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache.save(self.cache_path)

    def reload_cache(self) -> None:
        """Discard in-memory state and reread the cache from disk."""
        self.cache = IncrementalCache.load(self.cache_path)

    # ------------------------------------------------------------------ #
    # Stats
    # ------------------------------------------------------------------ #
    def total_cells(self) -> int:
        return sum(s.cell_count for s in self.cache.modules.values())

    def total_area(self) -> float:
        return sum(s.area for s in self.cache.modules.values())

    def stats_summary(self) -> str:
        return (
            f"{len(self.cache)} cached modules, "
            f"{self.total_cells()} cells, "
            f"area={self.total_area():.2f}"
        )
