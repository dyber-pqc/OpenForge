"""Component database with datasheets, parametric data, and pricing.

Provides a local JSON-backed component catalog with a pluggable
Octopart-style lookup hook. Ships with a curated set of builtin
common parts so the database is useful out of the box.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable


@dataclass
class Component:
    """Parametric component record."""

    mpn: str
    manufacturer: str
    description: str
    category: str
    package: str
    parameters: dict[str, str] = field(default_factory=dict)
    datasheet_url: str = ""
    image_url: str = ""
    pricing: dict[str, float] = field(default_factory=dict)
    stock: int = 0
    rohs_compliant: bool = True
    lifecycle: str = "Active"
    footprint: str = ""
    symbol: str = ""

    def unit_price(self, qty: int = 1) -> float:
        if not self.pricing:
            return 0.0
        try:
            best = 0.0
            breaks = sorted((int(k), v) for k, v in self.pricing.items())
            for b, price in breaks:
                if qty >= b:
                    best = price
            return best or breaks[0][1]
        except (ValueError, TypeError):
            return 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Component":
        return cls(**d)


class ComponentDatabase:
    """Local + cloud component database."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or Path.home() / ".openforge" / "components.json"
        self._cache: dict[str, Component] = {}
        self._load()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        if self.db_path.exists():
            try:
                with self.db_path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                for d in data.get("components", []):
                    c = Component.from_dict(d)
                    self._cache[c.mpn] = c
            except (json.JSONDecodeError, OSError):
                pass
        # Seed from builtin if empty.
        if not self._cache:
            for c in BUILTIN_COMPONENTS:
                self._cache[c.mpn] = c

    def save(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"components": [c.to_dict() for c in self._cache.values()]}
        with self.db_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # ------------------------------------------------------------------
    def search(
        self,
        query: str,
        category: str | None = None,
        limit: int = 50,
    ) -> list[Component]:
        q = query.lower().strip()
        results: list[Component] = []
        for comp in self._cache.values():
            if category and comp.category != category:
                continue
            if q:
                haystack = " ".join(
                    [
                        comp.mpn,
                        comp.manufacturer,
                        comp.description,
                        comp.package,
                        comp.category,
                        " ".join(f"{k}={v}" for k, v in comp.parameters.items()),
                    ]
                ).lower()
                if q not in haystack:
                    continue
            results.append(comp)
            if len(results) >= limit:
                break
        return results

    def get(self, mpn: str) -> Component | None:
        return self._cache.get(mpn)

    def add(self, comp: Component) -> None:
        self._cache[comp.mpn] = comp

    def remove(self, mpn: str) -> None:
        self._cache.pop(mpn, None)

    def all(self) -> list[Component]:
        return list(self._cache.values())

    def categories(self) -> list[str]:
        return sorted({c.category for c in self._cache.values()})

    def count(self) -> int:
        return len(self._cache)

    # ------------------------------------------------------------------
    def import_csv(self, path: Path) -> int:
        count = 0
        with Path(path).open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                params = {
                    k: v
                    for k, v in row.items()
                    if k
                    not in {
                        "mpn",
                        "manufacturer",
                        "description",
                        "category",
                        "package",
                        "datasheet_url",
                        "stock",
                    }
                    and v
                }
                comp = Component(
                    mpn=row.get("mpn", ""),
                    manufacturer=row.get("manufacturer", ""),
                    description=row.get("description", ""),
                    category=row.get("category", ""),
                    package=row.get("package", ""),
                    parameters=params,
                    datasheet_url=row.get("datasheet_url", ""),
                    stock=int(row.get("stock", 0) or 0),
                )
                self.add(comp)
                count += 1
        return count

    def export_csv(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "mpn",
            "manufacturer",
            "description",
            "category",
            "package",
            "datasheet_url",
            "stock",
            "lifecycle",
        ]
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for c in self._cache.values():
                writer.writerow({k: getattr(c, k, "") for k in fields})

    # ------------------------------------------------------------------
    def lookup_octopart(self, query: str) -> list[Component]:
        """Search an Octopart-style API. Falls back to local db.

        Without a configured API key we just filter the local cache so
        callers always get a consistent return type.
        """
        # Intentional fallback: a future implementation can plug a
        # real HTTP client here.
        return self.search(query, limit=25)


# ----------------------------------------------------------------------
# Builtin commonly-used parts
# ----------------------------------------------------------------------
def _r(mpn: str, val: str) -> Component:
    return Component(
        mpn=mpn,
        manufacturer="Yageo",
        description=f"{val} resistor 0805 1%",
        category="resistor",
        package="0805",
        parameters={"value": val, "tolerance": "1%", "power": "0.125W"},
        pricing={"1": 0.02, "100": 0.008, "1000": 0.003},
        stock=100000,
    )


def _c(mpn: str, val: str, voltage: str = "50V") -> Component:
    return Component(
        mpn=mpn,
        manufacturer="Murata",
        description=f"{val} X7R ceramic capacitor {voltage} 0805",
        category="capacitor",
        package="0805",
        parameters={
            "value": val,
            "voltage": voltage,
            "dielectric": "X7R",
            "tolerance": "10%",
        },
        pricing={"1": 0.05, "100": 0.02, "1000": 0.008},
        stock=50000,
    )


BUILTIN_COMPONENTS: list[Component] = [
    # Resistors
    _r("RC0805FR-0710KL", "10kΩ"),
    _r("RC0805FR-071KL", "1kΩ"),
    _r("RC0805FR-07100RL", "100Ω"),
    _r("RC0805FR-074K7L", "4.7kΩ"),
    _r("RC0805FR-0722KL", "22kΩ"),
    _r("RC0805FR-07100KL", "100kΩ"),
    _r("RC0805FR-07220RL", "220Ω"),
    _r("RC0805FR-0747KL", "47kΩ"),
    _r("RC0805FR-0733KL", "33kΩ"),
    _r("RC0805FR-0768KL", "68kΩ"),
    # Capacitors
    _c("GRM21BR71H104KA01L", "100nF"),
    _c("GRM21BR71H103KA01L", "10nF"),
    _c("GRM21BR61A106KE19L", "10uF", "10V"),
    _c("GRM21BR71H105KA12L", "1uF", "50V"),
    _c("GRM21BR71E225KA73L", "2.2uF", "25V"),
    _c("GRM21BR71H222KA01L", "2.2nF"),
    _c("GRM21BR61A475KE51L", "4.7uF", "10V"),
    _c("GRM21BR60J476ME15L", "47uF", "6.3V"),
    # MCUs
    Component(
        mpn="STM32F103C8T6",
        manufacturer="STMicroelectronics",
        description="ARM Cortex-M3 MCU 64KB Flash 20KB RAM",
        category="ic",
        package="LQFP-48",
        parameters={
            "core": "Cortex-M3",
            "speed": "72MHz",
            "flash": "64KB",
            "ram": "20KB",
            "vcc": "2.0-3.6V",
        },
        datasheet_url="https://www.st.com/resource/en/datasheet/stm32f103c8.pdf",
        pricing={"1": 3.50, "100": 2.75, "1000": 2.10},
        stock=5000,
    ),
    Component(
        mpn="STM32F407VGT6",
        manufacturer="STMicroelectronics",
        description="ARM Cortex-M4 MCU 1MB Flash 192KB RAM",
        category="ic",
        package="LQFP-100",
        parameters={
            "core": "Cortex-M4",
            "speed": "168MHz",
            "flash": "1MB",
            "ram": "192KB",
        },
        pricing={"1": 11.50, "100": 9.20, "1000": 7.80},
        stock=2500,
    ),
    Component(
        mpn="ATMEGA328P-PU",
        manufacturer="Microchip",
        description="AVR 8-bit MCU 32KB Flash",
        category="ic",
        package="DIP-28",
        parameters={
            "core": "AVR",
            "speed": "20MHz",
            "flash": "32KB",
        },
        pricing={"1": 2.50, "100": 2.00, "1000": 1.70},
        stock=8000,
    ),
    Component(
        mpn="ESP32-WROOM-32",
        manufacturer="Espressif",
        description="Wi-Fi + BT SoC module",
        category="ic",
        package="Module",
        parameters={"wifi": "802.11 b/g/n", "bt": "4.2 BR/EDR+BLE"},
        pricing={"1": 3.80, "100": 3.10, "1000": 2.50},
        stock=12000,
    ),
    # Regulators
    Component(
        mpn="AMS1117-3.3",
        manufacturer="AMS",
        description="3.3V LDO regulator 1A",
        category="regulator",
        package="SOT-223",
        parameters={"vout": "3.3V", "iout": "1A", "dropout": "1.1V"},
        pricing={"1": 0.25, "100": 0.12, "1000": 0.07},
        stock=30000,
    ),
    Component(
        mpn="LM7805CT",
        manufacturer="Texas Instruments",
        description="5V linear regulator 1.5A",
        category="regulator",
        package="TO-220",
        parameters={"vout": "5V", "iout": "1.5A"},
        pricing={"1": 0.50, "100": 0.35, "1000": 0.25},
        stock=10000,
    ),
    # Connectors
    Component(
        mpn="USB4110-GF-A",
        manufacturer="GCT",
        description="USB Type-C receptacle 24-pin",
        category="connector",
        package="SMD",
        parameters={"pins": "24", "type": "USB-C"},
        pricing={"1": 0.85, "100": 0.55},
        stock=20000,
    ),
    Component(
        mpn="61300411121",
        manufacturer="Wurth",
        description="Pin header 1x4 2.54mm",
        category="connector",
        package="THT",
        parameters={"pitch": "2.54mm", "pins": "4"},
        pricing={"1": 0.15, "100": 0.08},
        stock=50000,
    ),
    # Diodes & LEDs
    Component(
        mpn="1N4148W-7-F",
        manufacturer="Diodes Inc",
        description="Small signal switching diode 100V 150mA",
        category="diode",
        package="SOD-123",
        parameters={"vr": "100V", "if": "150mA"},
        pricing={"1": 0.10, "100": 0.04, "1000": 0.015},
        stock=80000,
    ),
    Component(
        mpn="LTST-C170KRKT",
        manufacturer="Lite-On",
        description="Red LED 0805 2V 20mA",
        category="led",
        package="0805",
        parameters={"color": "red", "vf": "2.0V", "if": "20mA"},
        pricing={"1": 0.12, "100": 0.06, "1000": 0.025},
        stock=40000,
    ),
    # Crystals
    Component(
        mpn="ABM8G-16.000MHZ-4Y-T3",
        manufacturer="Abracon",
        description="16 MHz crystal 8pF",
        category="crystal",
        package="3225",
        parameters={"freq": "16MHz", "load": "8pF"},
        pricing={"1": 0.35, "100": 0.22},
        stock=15000,
    ),
]
