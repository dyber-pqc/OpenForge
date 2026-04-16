"""High-level importer for KiCad symbol and footprint libraries.

Scans a KiCad install (or user directories) for ``.kicad_sym`` and
``.kicad_mod`` files, parses them with the in-tree parsers and caches
the result to disk as JSON so subsequent OpenForge launches are fast.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from openforge.pcb.kicad_fp_parser import parse_kicad_mod_file
from openforge.pcb.kicad_sym_parser import (
    _LocalSchPin,
    _LocalSchSymbol,
    parse_kicad_sym_file,
)

log = logging.getLogger(__name__)


# Default curated lists of the most useful KiCad libraries.
DEFAULT_ALLOW_SYMBOL_LIBS: list[str] = [
    "Device",
    "Connector",
    "Connector_Generic",
    "Diode",
    "Transistor_BJT",
    "Transistor_FET",
    "Logic_74xx",
    "Amplifier_Operational",
    "Memory_RAM",
    "Memory_Flash",
    "MCU_Microchip_ATmega",
    "MCU_ST_STM32F4",
    "MCU_Espressif",
    "RF_Module",
    "Sensor",
    "Sensor_Temperature",
    "LED",
    "Relay",
    "Power_Management",
    "Interface_USB",
    "Interface_Ethernet",
]

DEFAULT_ALLOW_FOOTPRINT_PRETTIES: list[str] = [
    "Resistor_SMD",
    "Capacitor_SMD",
    "Inductor_SMD",
    "LED_SMD",
    "Diode_SMD",
    "Package_SO",
    "Package_TO_SOT_SMD",
    "Package_QFP",
    "Package_QFN",
    "Package_BGA",
    "Package_DIP",
    "Package_TO_SOT_THT",
    "Connector_USB",
    "Connector_PinHeader_2.54mm",
    "Crystal",
    "RF_Module",
]


class KicadLibraryImporter:
    """Scan and import KiCad libraries into OpenForge."""

    def __init__(self) -> None:
        self.symbols: dict[str, Any] = {}
        self.footprints: dict[str, Any] = {}
        self.symbol_lib_counts: dict[str, int] = {}
        self.footprint_lib_counts: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    @staticmethod
    def detect_kicad_libs() -> dict[str, Path]:
        """Return the best guess at the KiCad symbol/footprint directories."""
        candidates_sym: list[Path] = []
        candidates_fp: list[Path] = []

        env_sym = os.environ.get("KICAD_SYMBOL_DIR")
        env_fp = os.environ.get("KICAD_FOOTPRINT_DIR")
        if env_sym:
            candidates_sym.append(Path(env_sym))
        if env_fp:
            candidates_fp.append(Path(env_fp))

        # Windows: C:/Program Files/KiCad/<ver>/share/kicad/symbols
        for base in (
            Path("C:/Program Files/KiCad"),
            Path("C:/Program Files (x86)/KiCad"),
        ):
            if base.exists():
                for ver in sorted(base.iterdir(), reverse=True):
                    share = ver / "share" / "kicad"
                    if (share / "symbols").exists():
                        candidates_sym.append(share / "symbols")
                    if (share / "footprints").exists():
                        candidates_fp.append(share / "footprints")

        # Linux
        for p in (
            Path("/usr/share/kicad/symbols"),
            Path("/usr/local/share/kicad/symbols"),
        ):
            if p.exists():
                candidates_sym.append(p)
        for p in (
            Path("/usr/share/kicad/footprints"),
            Path("/usr/local/share/kicad/footprints"),
        ):
            if p.exists():
                candidates_fp.append(p)

        # macOS
        mac_sym = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols")
        mac_fp = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints")
        if mac_sym.exists():
            candidates_sym.append(mac_sym)
        if mac_fp.exists():
            candidates_fp.append(mac_fp)

        result: dict[str, Path] = {}
        if candidates_sym:
            result["symbols"] = candidates_sym[0]
        if candidates_fp:
            result["footprints"] = candidates_fp[0]
        return result

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def import_symbols(
        self,
        symbol_dir: Path,
        target: dict[str, Any] | None = None,
        allow_libraries: list[str] | None = None,
    ) -> int:
        """Parse .kicad_sym files under *symbol_dir*.

        Returns the number of symbols imported.  If *target* is supplied
        the parsed symbols are merged into it as well.
        """
        symbol_dir = Path(symbol_dir)
        if not symbol_dir.is_dir():
            log.warning("symbol dir does not exist: %s", symbol_dir)
            return 0
        allow = set(allow_libraries) if allow_libraries is not None else None
        imported = 0
        for sym_file in sorted(symbol_dir.glob("*.kicad_sym")):
            lib_name = sym_file.stem
            if allow is not None and lib_name not in allow:
                continue
            try:
                parsed = parse_kicad_sym_file(sym_file)
            except Exception as exc:
                log.warning("failed to parse %s: %s", sym_file, exc)
                continue
            if not parsed:
                continue
            self.symbol_lib_counts[lib_name] = len(parsed)
            for name, sym in parsed.items():
                key = f"{lib_name}:{name}"
                self.symbols[key] = sym
                if target is not None:
                    target[key] = sym
                imported += 1
        log.info("imported %d symbols from %s", imported, symbol_dir)
        return imported

    def import_footprints(
        self,
        footprint_dir: Path,
        target: dict[str, Any] | None = None,
        allow_pretty: list[str] | None = None,
    ) -> int:
        """Parse .kicad_mod files under *footprint_dir*/<lib>.pretty/*.kicad_mod."""
        footprint_dir = Path(footprint_dir)
        if not footprint_dir.is_dir():
            log.warning("footprint dir does not exist: %s", footprint_dir)
            return 0
        allow = set(allow_pretty) if allow_pretty is not None else None
        imported = 0
        for pretty in sorted(footprint_dir.iterdir()):
            if not pretty.is_dir() or not pretty.name.endswith(".pretty"):
                continue
            lib_name = pretty.name[: -len(".pretty")]
            if allow is not None and lib_name not in allow:
                continue
            lib_count = 0
            for mod_file in sorted(pretty.glob("*.kicad_mod")):
                try:
                    fp = parse_kicad_mod_file(mod_file)
                except Exception as exc:
                    log.debug("skip %s: %s", mod_file, exc)
                    continue
                if fp is None:
                    continue
                key = f"{lib_name}:{getattr(fp, 'name', mod_file.stem)}"
                self.footprints[key] = fp
                if target is not None:
                    target[key] = fp
                imported += 1
                lib_count += 1
            if lib_count:
                self.footprint_lib_counts[lib_name] = lib_count
        log.info("imported %d footprints from %s", imported, footprint_dir)
        return imported

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    @staticmethod
    def _serialize(obj: Any) -> Any:
        if is_dataclass(obj):
            return asdict(obj)
        if isinstance(obj, dict):
            return {k: KicadLibraryImporter._serialize(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [KicadLibraryImporter._serialize(v) for v in obj]
        if isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj
        # Last-resort: turn it into a dict of its __dict__
        if hasattr(obj, "__dict__"):
            return {
                k: KicadLibraryImporter._serialize(v)
                for k, v in obj.__dict__.items()
                if not k.startswith("_")
            }
        return str(obj)

    def cache_to_disk(self, cache_path: Path) -> None:
        """Write all parsed symbols/footprints to a single JSON cache."""
        cache_path = Path(cache_path)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "symbol_lib_counts": self.symbol_lib_counts,
            "footprint_lib_counts": self.footprint_lib_counts,
            "symbols": {k: self._serialize(v) for k, v in self.symbols.items()},
            "footprints": {k: self._serialize(v) for k, v in self.footprints.items()},
        }
        cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log.info("wrote KiCad cache: %s", cache_path)

    def load_from_cache(self, cache_path: Path) -> dict[str, Any]:
        """Load a previously-written cache; rehydrates into local dataclasses."""
        cache_path = Path(cache_path)
        if not cache_path.exists():
            return {}
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("failed to read cache %s: %s", cache_path, exc)
            return {}

        self.symbol_lib_counts = dict(data.get("symbol_lib_counts", {}))
        self.footprint_lib_counts = dict(data.get("footprint_lib_counts", {}))

        self.symbols = {}
        for key, raw in (data.get("symbols") or {}).items():
            try:
                pins = [_LocalSchPin(**p) for p in raw.get("pins", [])]
                sym = _LocalSchSymbol(
                    name=raw.get("name", key),
                    library=raw.get("library", ""),
                    description=raw.get("description", ""),
                    keywords=raw.get("keywords", ""),
                    width=raw.get("width", 200),
                    height=raw.get("height", 200),
                    pins=pins,
                    fields=dict(raw.get("fields", {})),
                    body_shape=raw.get("body_shape", "rectangle"),
                )
                self.symbols[key] = sym
            except Exception as exc:
                log.debug("skip cached symbol %s: %s", key, exc)

        self.footprints = {}
        for key, raw in (data.get("footprints") or {}).items():
            self.footprints[key] = raw  # keep as dict (viewers cope)

        return {
            "symbols": self.symbols,
            "footprints": self.footprints,
            "symbol_lib_counts": self.symbol_lib_counts,
            "footprint_lib_counts": self.footprint_lib_counts,
        }


def default_cache_path() -> Path:
    """Return ``~/.openforge/cache/kicad_libraries.json``."""
    return Path.home() / ".openforge" / "cache" / "kicad_libraries.json"


__all__ = [
    "KicadLibraryImporter",
    "DEFAULT_ALLOW_SYMBOL_LIBS",
    "DEFAULT_ALLOW_FOOTPRINT_PRETTIES",
    "default_cache_path",
]
