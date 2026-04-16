"""Hierarchical schematic sheet templates.

Each factory returns a ``(Schematic, SchSheet)`` tuple describing a ready
to drop sub-schematic implementing a common reusable block (regulator,
USB-C, MCU minimum system, etc.).

The returned :class:`Schematic` and :class:`SchSheet` come from
``openforge_desktop.widgets.schematic_editor`` when available; when that
import is not possible (headless environment / no Qt) we fall back on
lightweight dataclass stand-ins so the library can still be imported and
unit tested.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

try:  # pragma: no cover - optional Qt dependency
    from openforge_desktop.widgets.schematic_editor import (  # type: ignore
        SchComponent,
        Schematic,
        SchLabel,
        SchPort,
        SchPowerSymbol,
        SchSheet,
        SchWireSegment,
    )

    _HAS_EDITOR = True
except Exception:  # pragma: no cover - headless fallback
    _HAS_EDITOR = False

    @dataclass
    class SchComponent:  # type: ignore[no-redef]
        refdes: str
        symbol_name: str
        library: str
        value: str
        x: float = 0
        y: float = 0
        rotation: int = 0
        mirrored: bool = False
        fields: dict = field(default_factory=dict)

    @dataclass
    class SchWireSegment:  # type: ignore[no-redef]
        x1: float
        y1: float
        x2: float
        y2: float
        net_name: str = ""

    @dataclass
    class SchLabel:  # type: ignore[no-redef]
        text: str
        x: float
        y: float
        rotation: int = 0
        label_type: str = "net"

    @dataclass
    class SchPowerSymbol:  # type: ignore[no-redef]
        net_name: str
        x: float
        y: float
        is_ground: bool = False

    @dataclass
    class SchPort:  # type: ignore[no-redef]
        name: str
        direction: str = "bidir"
        width: int = 1
        net_name: str = ""
        side: str = "L"

    @dataclass
    class SchSheet:  # type: ignore[no-redef]
        name: str
        filename: str
        ports: list = field(default_factory=list)
        position: tuple = (0.0, 0.0)
        parent_sheet: str = ""

    @dataclass
    class Schematic:  # type: ignore[no-redef]
        title: str = "Untitled"
        components: list = field(default_factory=list)
        wires: list = field(default_factory=list)
        labels: list = field(default_factory=list)
        power_symbols: list = field(default_factory=list)
        sheet_size: tuple = (11000, 8500)
        sub_sheets: list = field(default_factory=list)
        buses: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


@dataclass
class SchSheetTemplate:
    """Named sheet template with factory callable."""

    id: str
    title: str
    description: str
    factory: Callable[..., tuple[Any, Any]]


def _mk_sch(title: str) -> Any:
    s = Schematic(title=title)
    # Some fields (sub_sheets/buses) live on the editor-provided class
    # only; ensure they exist.
    if not hasattr(s, "sub_sheets"):
        s.sub_sheets = []  # type: ignore[attr-defined]
    if not hasattr(s, "buses"):
        s.buses = []  # type: ignore[attr-defined]
    return s


def _comp(refdes: str, sym: str, lib: str, value: str, x: float, y: float, **fields) -> Any:
    return SchComponent(
        refdes=refdes,
        symbol_name=sym,
        library=lib,
        value=value,
        x=float(x),
        y=float(y),
        fields=dict(fields),
    )


def _wire(x1: float, y1: float, x2: float, y2: float, net: str = "") -> Any:
    return SchWireSegment(x1=float(x1), y1=float(y1), x2=float(x2), y2=float(y2), net_name=net)


def _label(text: str, x: float, y: float) -> Any:
    return SchLabel(text=text, x=float(x), y=float(y))


def _pwr(net: str, x: float, y: float, is_ground: bool = False) -> Any:
    return SchPowerSymbol(net_name=net, x=float(x), y=float(y), is_ground=is_ground)


def _sheet(
    name: str, filename: str, ports: list[Any], pos: tuple[float, float] = (4000, 3000)
) -> Any:
    return SchSheet(name=name, filename=filename, ports=ports, position=pos)


def _port(
    name: str, direction: str = "bidir", side: str = "L", width: int = 1, net: str = ""
) -> Any:
    return SchPort(name=name, direction=direction, side=side, width=width, net_name=net or name)


# ---------------------------------------------------------------------------
# Template factories
# ---------------------------------------------------------------------------


def linear_regulator_3v3(input_v: float = 5.0, output_current_a: float = 1.0) -> tuple[Any, Any]:
    """AMS1117-3.3 linear regulator with input/output caps and power LED."""
    sch = _mk_sch("LDO 3.3V (AMS1117)")
    # Choose cap values based on current capability.
    cin_val = "10uF" if output_current_a >= 1.0 else "4.7uF"
    cout_val = "22uF" if output_current_a >= 1.0 else "10uF"
    # Input cap
    sch.components.append(_comp("C1", "C", "Device", cin_val, 1000, 2000))
    # Output cap
    sch.components.append(_comp("C2", "C", "Device", cout_val, 3000, 2000))
    # Regulator
    sch.components.append(_comp("U1", "AMS1117-3.3", "Regulator_Linear", "AMS1117-3.3", 2000, 1800))
    # LED + resistor indicator
    sch.components.append(_comp("R1", "R", "Device", "1k", 3500, 1800))
    sch.components.append(_comp("D1", "LED", "Device", "Green", 3500, 2200))
    # Wires
    sch.wires.append(_wire(1000, 1800, 2000, 1800, "VIN"))
    sch.wires.append(_wire(2000, 1800, 3000, 1800, "VOUT"))
    sch.wires.append(_wire(1000, 1800, 1000, 2000, "VIN"))
    sch.wires.append(_wire(3000, 1800, 3000, 2000, "VOUT"))
    # Power
    sch.power_symbols.append(_pwr(f"+{input_v}V", 1000, 1600))
    sch.power_symbols.append(_pwr("+3V3", 3500, 1600))
    sch.power_symbols.append(_pwr("GND", 1000, 2200, True))
    sch.power_symbols.append(_pwr("GND", 3000, 2200, True))
    sch.power_symbols.append(_pwr("GND", 3500, 2400, True))
    sh = _sheet(
        "LDO_3V3",
        "ldo_3v3.sch",
        [
            _port(f"+{input_v}V", "power_in", "L"),
            _port("+3V3", "power_out", "R"),
            _port("GND", "power_in", "B"),
        ],
    )
    return sch, sh


def usb_c_power_only() -> tuple[Any, Any]:
    """USB-C receptacle wired only for 5V power (CC1/CC2 with 5.1k)."""
    sch = _mk_sch("USB-C Power Only")
    sch.components.append(_comp("J1", "USB_C_Receptacle_USB2.0", "Connector", "USB-C", 2000, 2000))
    sch.components.append(_comp("R1", "R", "Device", "5.1k", 2800, 2200))
    sch.components.append(_comp("R2", "R", "Device", "5.1k", 2800, 2400))
    sch.wires.append(_wire(2400, 2200, 2800, 2200, "CC1"))
    sch.wires.append(_wire(2400, 2400, 2800, 2400, "CC2"))
    sch.power_symbols.append(_pwr("+5V", 2400, 1800))
    sch.power_symbols.append(_pwr("GND", 2400, 2800, True))
    sch.power_symbols.append(_pwr("GND", 2800, 2600, True))
    sch.power_symbols.append(_pwr("GND", 2800, 2800, True))
    sh = _sheet(
        "USB_C_PWR",
        "usb_c_pwr.sch",
        [
            _port("+5V", "power_out", "R"),
            _port("GND", "power_out", "B"),
        ],
    )
    return sch, sh


def usb_c_data() -> tuple[Any, Any]:
    """Full USB-C 2.0 connector with CC + D+/D- + ESD protection."""
    sch = _mk_sch("USB-C Data")
    sch.components.append(_comp("J1", "USB_C_Receptacle_USB2.0", "Connector", "USB-C", 2000, 2000))
    sch.components.append(_comp("R1", "R", "Device", "5.1k", 2800, 2200))
    sch.components.append(_comp("R2", "R", "Device", "5.1k", 2800, 2400))
    sch.components.append(_comp("U2", "USBLC6-2SC6", "Power_Protection", "USBLC6", 2800, 2800))
    sch.wires.append(_wire(2400, 2600, 2800, 2600, "DP"))
    sch.wires.append(_wire(2400, 2700, 2800, 2700, "DN"))
    sch.power_symbols.append(_pwr("+5V", 2400, 1800))
    sch.power_symbols.append(_pwr("GND", 2400, 3000, True))
    sh = _sheet(
        "USB_C_DATA",
        "usb_c_data.sch",
        [
            _port("+5V", "power_out", "R"),
            _port("GND", "power_out", "B"),
            _port("USB_DP", "bidir", "R"),
            _port("USB_DN", "bidir", "R"),
        ],
    )
    return sch, sh


def power_switch_slide() -> tuple[Any, Any]:
    """Slide switch on power rail."""
    sch = _mk_sch("Power Slide Switch")
    sch.components.append(_comp("SW1", "SW_SPDT", "Switch", "Slide", 2000, 2000))
    sch.power_symbols.append(_pwr("VIN", 1700, 2000))
    sch.power_symbols.append(_pwr("VOUT", 2300, 2000))
    sh = _sheet(
        "PWR_SW",
        "pwr_sw.sch",
        [
            _port("VIN", "power_in", "L"),
            _port("VOUT", "power_out", "R"),
        ],
    )
    return sch, sh


def ftdi_ft232h_uart() -> tuple[Any, Any]:
    """FT232H USB-UART bridge section."""
    sch = _mk_sch("FT232H UART")
    sch.components.append(_comp("U1", "FT232HL", "Interface_USB", "FT232HL", 2500, 2000))
    for i, v in enumerate(("100nF",) * 4):
        sch.components.append(_comp(f"C{i + 1}", "C", "Device", v, 1500 + i * 300, 2800))
    sch.components.append(_comp("Y1", "Crystal", "Device", "12MHz", 3500, 2400))
    sch.components.append(_comp("C5", "C", "Device", "18pF", 3700, 2600))
    sch.components.append(_comp("C6", "C", "Device", "18pF", 3700, 2800))
    sch.power_symbols.append(_pwr("+3V3", 2500, 1600))
    sch.power_symbols.append(_pwr("GND", 2500, 3200, True))
    sh = _sheet(
        "FT232H",
        "ft232h.sch",
        [
            _port("+3V3", "power_in", "L"),
            _port("GND", "power_in", "B"),
            _port("USB_DP", "bidir", "L"),
            _port("USB_DN", "bidir", "L"),
            _port("TXD", "output", "R"),
            _port("RXD", "input", "R"),
            _port("RTS", "output", "R"),
            _port("CTS", "input", "R"),
        ],
    )
    return sch, sh


def stm32f4_min_system() -> tuple[Any, Any]:
    """STM32F4 minimum system: MCU, 8MHz HSE, reset, decoupling."""
    sch = _mk_sch("STM32F4 Min System")
    sch.components.append(_comp("U1", "STM32F401RE", "MCU_ST_STM32F4", "STM32F401RET6", 3000, 2500))
    # Decoupling caps - 1 per VDD pin (4 on STM32F4)
    for i in range(4):
        sch.components.append(_comp(f"C{i + 1}", "C", "Device", "100nF", 1500 + i * 300, 3800))
    sch.components.append(_comp("C5", "C", "Device", "4.7uF", 2700, 3800))  # VDDA bulk
    # HSE crystal
    sch.components.append(_comp("Y1", "Crystal", "Device", "8MHz", 4500, 2300))
    sch.components.append(_comp("C6", "C", "Device", "18pF", 4700, 2100))
    sch.components.append(_comp("C7", "C", "Device", "18pF", 4700, 2500))
    # Reset button + RC
    sch.components.append(_comp("SW1", "SW_Push", "Switch", "Reset", 1800, 2500))
    sch.components.append(_comp("R1", "R", "Device", "10k", 1800, 2300))
    sch.components.append(_comp("C8", "C", "Device", "100nF", 1800, 2700))
    # BOOT0 pulldown
    sch.components.append(_comp("R2", "R", "Device", "10k", 1800, 3000))
    sch.power_symbols.append(_pwr("+3V3", 3000, 1800))
    sch.power_symbols.append(_pwr("GND", 3000, 4000, True))
    sh = _sheet(
        "STM32F4",
        "stm32f4.sch",
        [
            _port("+3V3", "power_in", "L"),
            _port("GND", "power_in", "B"),
            _port("SWDIO", "bidir", "R"),
            _port("SWCLK", "input", "R"),
            _port("NRST", "input", "R"),
            _port("UART_TX", "output", "R"),
            _port("UART_RX", "input", "R"),
            _port("I2C_SDA", "bidir", "R"),
            _port("I2C_SCL", "output", "R"),
            _port("SPI_MOSI", "output", "R"),
            _port("SPI_MISO", "input", "R"),
            _port("SPI_SCK", "output", "R"),
        ],
    )
    return sch, sh


def rp2040_min_system() -> tuple[Any, Any]:
    """RP2040 minimum system: MCU, flash, 12MHz crystal, 1.1V LDO."""
    sch = _mk_sch("RP2040 Min System")
    sch.components.append(_comp("U1", "RP2040", "MCU_RaspberryPi", "RP2040", 3000, 2500))
    sch.components.append(_comp("U2", "W25Q128JV", "Memory_Flash", "W25Q128JV", 4500, 2500))
    sch.components.append(_comp("U3", "LDO_1V1", "Regulator_Linear", "NCP1117-1.1", 1500, 2500))
    # Decoupling
    for i in range(8):
        sch.components.append(_comp(f"C{i + 1}", "C", "Device", "100nF", 1200 + i * 250, 3800))
    sch.components.append(_comp("C9", "C", "Device", "1uF", 1500, 2800))
    sch.components.append(_comp("C10", "C", "Device", "1uF", 1800, 2800))
    # Crystal
    sch.components.append(_comp("Y1", "Crystal", "Device", "12MHz", 4500, 3200))
    sch.components.append(_comp("C11", "C", "Device", "15pF", 4300, 3400))
    sch.components.append(_comp("C12", "C", "Device", "15pF", 4700, 3400))
    sch.power_symbols.append(_pwr("+3V3", 3000, 1800))
    sch.power_symbols.append(_pwr("+1V1", 3000, 2000))
    sch.power_symbols.append(_pwr("GND", 3000, 4000, True))
    sh = _sheet(
        "RP2040",
        "rp2040.sch",
        [
            _port("+3V3", "power_in", "L"),
            _port("GND", "power_in", "B"),
            _port("SWDIO", "bidir", "R"),
            _port("SWCLK", "input", "R"),
            _port("USB_DP", "bidir", "R"),
            _port("USB_DN", "bidir", "R"),
            _port("GPIO0", "bidir", "R"),
            _port("GPIO1", "bidir", "R"),
            _port("GPIO2", "bidir", "R"),
        ],
    )
    return sch, sh


def esp32_wroom_section() -> tuple[Any, Any]:
    """ESP32-WROOM-32 module section with strap & boot/enable."""
    sch = _mk_sch("ESP32-WROOM")
    sch.components.append(_comp("U1", "ESP32-WROOM-32", "RF_Module", "ESP32-WROOM-32", 3000, 2500))
    sch.components.append(_comp("C1", "C", "Device", "10uF", 2000, 3500))
    sch.components.append(_comp("C2", "C", "Device", "100nF", 2300, 3500))
    # EN pullup + reset cap
    sch.components.append(_comp("R1", "R", "Device", "10k", 2000, 2200))
    sch.components.append(_comp("C3", "C", "Device", "1uF", 2000, 2500))
    # BOOT button
    sch.components.append(_comp("SW1", "SW_Push", "Switch", "BOOT", 4000, 2500))
    sch.components.append(_comp("SW2", "SW_Push", "Switch", "EN", 4000, 2200))
    sch.power_symbols.append(_pwr("+3V3", 3000, 1800))
    sch.power_symbols.append(_pwr("GND", 3000, 4000, True))
    sh = _sheet(
        "ESP32",
        "esp32.sch",
        [
            _port("+3V3", "power_in", "L"),
            _port("GND", "power_in", "B"),
            _port("UART_TX", "output", "R"),
            _port("UART_RX", "input", "R"),
            _port("GPIO0", "bidir", "R"),
            _port("EN", "input", "R"),
        ],
    )
    return sch, sh


def ethernet_rj45_magjack() -> tuple[Any, Any]:
    """Ethernet RJ45 with integrated magnetics (mag-jack)."""
    sch = _mk_sch("RJ45 MagJack")
    sch.components.append(_comp("J1", "RJ45_Magjack_HX1188", "Connector", "HX1188", 3000, 2500))
    sch.components.append(_comp("R1", "R", "Device", "75", 2000, 2800))
    sch.components.append(_comp("R2", "R", "Device", "75", 2000, 3000))
    sch.components.append(_comp("R3", "R", "Device", "75", 2000, 3200))
    sch.components.append(_comp("R4", "R", "Device", "75", 2000, 3400))
    sch.components.append(_comp("C1", "C", "Device", "1nF/2kV", 2300, 3600))
    sch.power_symbols.append(_pwr("GND", 2300, 3800, True))
    sh = _sheet(
        "RJ45",
        "rj45.sch",
        [
            _port("TX_P", "bidir", "L"),
            _port("TX_N", "bidir", "L"),
            _port("RX_P", "bidir", "L"),
            _port("RX_N", "bidir", "L"),
            _port("LED_G", "input", "L"),
            _port("LED_Y", "input", "L"),
            _port("GND", "power_in", "B"),
        ],
    )
    return sch, sh


def ddr3_single_chip_layout() -> tuple[Any, Any]:
    """Single DDR3 x16 chip with decoupling and VTT termination."""
    sch = _mk_sch("DDR3 Single Chip")
    sch.components.append(_comp("U1", "MT41K256M16", "Memory_RAM", "DDR3-1600", 3000, 2500))
    # VDD decoupling (9 caps typical for x16)
    for i in range(9):
        sch.components.append(
            _comp(f"C{i + 1}", "C", "Device", "100nF", 1200 + (i % 5) * 250, 3800 + (i // 5) * 200)
        )
    # Bulk
    sch.components.append(_comp("C10", "C", "Device", "10uF", 2600, 4200))
    sch.components.append(_comp("C11", "C", "Device", "10uF", 2900, 4200))
    # VTT termination network (simplified)
    sch.components.append(_comp("R1", "R", "Device", "39", 4500, 2500))
    sch.power_symbols.append(_pwr("+1V5", 3000, 1800))
    sch.power_symbols.append(_pwr("VTT", 4500, 2300))
    sch.power_symbols.append(_pwr("GND", 3000, 4400, True))
    sh = _sheet(
        "DDR3",
        "ddr3.sch",
        [
            _port("+1V5", "power_in", "L"),
            _port("VTT", "power_in", "L"),
            _port("GND", "power_in", "B"),
            _port("DQ", "bidir", "R", width=16),
            _port("DQS", "bidir", "R", width=2),
            _port("ADDR", "input", "R", width=15),
            _port("BA", "input", "R", width=3),
            _port("CMD", "input", "R", width=5),
            _port("CLK", "input", "R", width=2),
        ],
    )
    return sch, sh


def oscillator_canned() -> tuple[Any, Any]:
    """3-pin canned oscillator with decoupling cap."""
    sch = _mk_sch("Canned Oscillator")
    sch.components.append(_comp("X1", "Oscillator", "Oscillator", "25MHz", 2500, 2500))
    sch.components.append(_comp("C1", "C", "Device", "100nF", 2800, 2800))
    sch.power_symbols.append(_pwr("+3V3", 2500, 2300))
    sch.power_symbols.append(_pwr("GND", 2500, 2900, True))
    sh = _sheet(
        "OSC",
        "osc.sch",
        [
            _port("+3V3", "power_in", "L"),
            _port("GND", "power_in", "B"),
            _port("CLK_OUT", "output", "R"),
        ],
    )
    return sch, sh


def crystal_circuit() -> tuple[Any, Any]:
    """HC-49 crystal + two load caps."""
    sch = _mk_sch("Crystal Circuit")
    sch.components.append(_comp("Y1", "Crystal", "Device", "16MHz", 2500, 2500))
    sch.components.append(_comp("C1", "C", "Device", "22pF", 2300, 2700))
    sch.components.append(_comp("C2", "C", "Device", "22pF", 2700, 2700))
    sch.power_symbols.append(_pwr("GND", 2500, 2900, True))
    sh = _sheet(
        "XTAL",
        "xtal.sch",
        [
            _port("XIN", "bidir", "L"),
            _port("XOUT", "bidir", "R"),
            _port("GND", "power_in", "B"),
        ],
    )
    return sch, sh


def mosfet_driver_high_side() -> tuple[Any, Any]:
    """High-side P-MOS load switch driven by NPN."""
    sch = _mk_sch("High-Side Load Switch")
    sch.components.append(_comp("Q1", "PMOS", "Device", "IRF9540", 2500, 2000))
    sch.components.append(_comp("Q2", "NPN", "Device", "2N3904", 2500, 2600))
    sch.components.append(_comp("R1", "R", "Device", "10k", 2200, 2000))
    sch.components.append(_comp("R2", "R", "Device", "10k", 2200, 2600))
    sch.components.append(_comp("R3", "R", "Device", "4.7k", 2800, 2600))
    sch.power_symbols.append(_pwr("VIN", 2500, 1700))
    sch.power_symbols.append(_pwr("VOUT", 2800, 1700))
    sch.power_symbols.append(_pwr("GND", 2500, 2900, True))
    sh = _sheet(
        "HS_SW",
        "hs_sw.sch",
        [
            _port("VIN", "power_in", "L"),
            _port("VOUT", "power_out", "R"),
            _port("EN", "input", "L"),
            _port("GND", "power_in", "B"),
        ],
    )
    return sch, sh


def op_amp_inverting(gain: float = 10.0) -> tuple[Any, Any]:
    """Inverting op-amp stage with user-selected gain."""
    sch = _mk_sch(f"Inverting Op-Amp (Av={gain})")
    sch.components.append(_comp("U1", "OPAMP", "Amplifier_Operational", "MCP6002", 2500, 2500))
    rf = 10_000 * gain
    sch.components.append(_comp("R1", "R", "Device", "10k", 2000, 2400))
    sch.components.append(_comp("R2", "R", "Device", f"{rf:.0f}", 2500, 2200))
    sch.components.append(_comp("C1", "C", "Device", "100nF", 2800, 2800))
    sch.power_symbols.append(_pwr("+V", 2500, 2200))
    sch.power_symbols.append(_pwr("-V", 2500, 2900))
    sch.power_symbols.append(_pwr("GND", 2800, 2900, True))
    sh = _sheet(
        "OA_INV",
        "oa_inv.sch",
        [
            _port("VIN", "input", "L"),
            _port("VOUT", "output", "R"),
            _port("+V", "power_in", "T"),
            _port("-V", "power_in", "B"),
        ],
    )
    return sch, sh


def op_amp_noninverting(gain: float = 10.0) -> tuple[Any, Any]:
    """Non-inverting op-amp stage."""
    sch = _mk_sch(f"Non-Inv Op-Amp (Av={gain})")
    sch.components.append(_comp("U1", "OPAMP", "Amplifier_Operational", "MCP6002", 2500, 2500))
    rf = 10_000 * (gain - 1)
    sch.components.append(_comp("R1", "R", "Device", "10k", 2000, 2600))
    sch.components.append(_comp("R2", "R", "Device", f"{rf:.0f}", 2500, 2600))
    sch.components.append(_comp("C1", "C", "Device", "100nF", 2800, 2800))
    sch.power_symbols.append(_pwr("+V", 2500, 2200))
    sch.power_symbols.append(_pwr("-V", 2500, 2900))
    sch.power_symbols.append(_pwr("GND", 2800, 2900, True))
    sh = _sheet(
        "OA_NONINV",
        "oa_noninv.sch",
        [
            _port("VIN", "input", "L"),
            _port("VOUT", "output", "R"),
            _port("+V", "power_in", "T"),
            _port("-V", "power_in", "B"),
        ],
    )
    return sch, sh


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


BUILTIN_TEMPLATES: list[SchSheetTemplate] = [
    SchSheetTemplate("ldo_3v3", "LDO 3.3V", "AMS1117-3.3 linear regulator", linear_regulator_3v3),
    SchSheetTemplate("usb_c_pwr", "USB-C Power", "USB-C receptacle, 5V only", usb_c_power_only),
    SchSheetTemplate("usb_c_data", "USB-C Data", "USB-C with data pair + ESD", usb_c_data),
    SchSheetTemplate("pwr_sw", "Power Switch", "Slide switch on power rail", power_switch_slide),
    SchSheetTemplate("ft232h", "FT232H UART", "FTDI FT232H USB-UART", ftdi_ft232h_uart),
    SchSheetTemplate("stm32f4", "STM32F4 Min System", "STM32F4 min system", stm32f4_min_system),
    SchSheetTemplate("rp2040", "RP2040 Min System", "RP2040 + flash + 12MHz XO", rp2040_min_system),
    SchSheetTemplate("esp32", "ESP32-WROOM", "ESP32-WROOM-32 module", esp32_wroom_section),
    SchSheetTemplate("rj45", "Ethernet RJ45", "RJ45 magjack + termination", ethernet_rj45_magjack),
    SchSheetTemplate(
        "ddr3", "DDR3 Single Chip", "DDR3 x16 + decoupling + VTT", ddr3_single_chip_layout
    ),
    SchSheetTemplate("osc", "Canned Oscillator", "3-pin oscillator + decap", oscillator_canned),
    SchSheetTemplate("xtal", "Crystal", "HC-49 crystal + load caps", crystal_circuit),
    SchSheetTemplate("hs_sw", "High-Side Switch", "P-MOS load switch", mosfet_driver_high_side),
    SchSheetTemplate("oa_inv", "Inverting Op-Amp", "Inverting op-amp", op_amp_inverting),
    SchSheetTemplate("oa_noninv", "Non-Inv Op-Amp", "Non-inverting op-amp", op_amp_noninverting),
]


def get_template(id: str) -> SchSheetTemplate | None:
    for t in BUILTIN_TEMPLATES:
        if t.id == id:
            return t
    return None
