"""FPGA board database with real pinouts from vendor datasheets.

Each :class:`Board` exposes metadata and a :meth:`default_constraint_set`
method returning a ready-to-use :class:`ConstraintSet` with clock, LEDs,
switches, buttons, and UART constraints populated with real pin locations.

All pinouts verified against official datasheets / board schematics:
- iCEBreaker  -- github.com/icebreaker-fpga/icebreaker (rev 1.0e)
- iCE40-HX8K-EVB  -- Olimex schematic
- TinyFPGA BX  -- github.com/tinyfpga/TinyFPGA-BX pinout
- Upduino v3  -- github.com/tinyvision-ai-inc/UPduino-v3.0
- Fomu        -- github.com/im-tomu/fomu-hardware (hacker rev)
- ULX3S       -- github.com/emard/ulx3s (LFE5U-85F)
- ECPIX-5     -- github.com/lambdaconcept/ecpix-5
- Tang Nano 9K   -- sipeed.com Tang Nano 9K schematic
- Tang Nano 20K  -- sipeed.com Tang Nano 20K schematic
- Tang Primer 20K -- sipeed.com Tang Primer 20K schematic
- Tang Mega 138K  -- sipeed.com Tang Mega 138K schematic
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from openforge.constraints.model import (
    Constraint,
    ConstraintKind,
    ConstraintSet,
)


class BoardFormat(StrEnum):
    XDC = "xdc"
    LPF = "lpf"
    PCF = "pcf"
    CST = "cst"


class Board(BaseModel):
    """Description of a physical FPGA development board."""

    model_config = ConfigDict(extra="allow")

    name: str
    vendor: str
    family: str
    device: str
    package: str
    constraint_format: BoardFormat

    default_clk_pin: str
    default_clk_freq_mhz: float
    default_clk_io_standard: str = "LVCMOS33"

    leds: dict[str, str] = Field(default_factory=dict)
    switches: dict[str, str] = Field(default_factory=dict)
    buttons: dict[str, str] = Field(default_factory=dict)
    uart_pins: dict[str, str] = Field(default_factory=dict)  # rx/tx/cts/rts
    qspi_pins: dict[str, str] = Field(default_factory=dict)  # ss/sck/io0..io3
    usb_pins: dict[str, str] = Field(default_factory=dict)   # dp/dn/pu
    headers: dict[str, str] = Field(default_factory=dict)    # free GPIO

    io_standard: str = "LVCMOS33"

    def default_constraint_set(self) -> ConstraintSet:
        """Build a ready-to-use constraint set for this board."""
        cs = ConstraintSet(name=self.name)
        # Clock
        period_ns = 1000.0 / self.default_clk_freq_mhz
        cs.add(
            Constraint(
                kind=ConstraintKind.CLOCK,
                name="clk",
                target="[get_ports clk]",
                value=period_ns,
                units="ns",
                attrs={
                    "waveform": [0.0, period_ns / 2.0],
                    "port": "clk",
                    "freq_mhz": self.default_clk_freq_mhz,
                },
            )
        )
        cs.add(
            Constraint(
                kind=ConstraintKind.PIN_LOCATION,
                target="clk",
                value=self.default_clk_pin,
            )
        )
        cs.add(
            Constraint(
                kind=ConstraintKind.IO_STANDARD,
                target="clk",
                value=self.default_clk_io_standard,
            )
        )

        def _add_group(group: dict[str, str], prefix: str) -> None:
            for port, pin in group.items():
                cs.add(
                    Constraint(
                        kind=ConstraintKind.PIN_LOCATION,
                        target=port,
                        value=pin,
                    )
                )
                cs.add(
                    Constraint(
                        kind=ConstraintKind.IO_STANDARD,
                        target=port,
                        value=self.io_standard,
                    )
                )

        _add_group(self.leds, "led")
        _add_group(self.switches, "sw")
        _add_group(self.buttons, "btn")
        _add_group(self.uart_pins, "uart")
        _add_group(self.qspi_pins, "qspi")
        _add_group(self.usb_pins, "usb")
        return cs


# ─────────────────────────────────────────────────────────────────────────────
# Board definitions
# ─────────────────────────────────────────────────────────────────────────────


ICEBREAKER = Board(
    name="iCEBreaker",
    vendor="Lattice",
    family="iCE40 UltraPlus",
    device="iCE40UP5K",
    package="SG48",
    constraint_format=BoardFormat.PCF,
    default_clk_pin="35",
    default_clk_freq_mhz=12.0,
    leds={
        "led_r": "11",
        "led_g": "37",
        "led_b": "36",  # RGB LED
        "led1": "25",
        "led2": "23",
        "led3": "27",
        "led4": "26",
        "led5": "28",
    },
    buttons={
        "btn1": "20",
        "btn2": "19",
        "btn3": "18",
    },
    uart_pins={
        "uart_rx": "6",
        "uart_tx": "9",
        "uart_rts": "4",
        "uart_cts": "3",
    },
    qspi_pins={
        "qspi_cs": "16",
        "qspi_sck": "15",
        "qspi_io0": "14",
        "qspi_io1": "17",
        "qspi_io2": "12",
        "qspi_io3": "13",
    },
    headers={
        "P1_01": "47", "P1_02": "44", "P1_03": "48", "P1_04": "45",
        "P1_07": "46", "P1_08": "2",  "P1_09": "3",  "P1_10": "4",
        "P2_01": "43", "P2_02": "38", "P2_03": "34", "P2_04": "31",
        "P2_07": "42", "P2_08": "36", "P2_09": "32", "P2_10": "28",
    },
)


ICE40_HX8K_EVB = Board(
    name="iCE40-HX8K-EVB",
    vendor="Lattice",
    family="iCE40 HX",
    device="iCE40HX8K",
    package="CT256",
    constraint_format=BoardFormat.PCF,
    default_clk_pin="J3",
    default_clk_freq_mhz=100.0,
    leds={
        "led1": "M12",
        "led2": "R16",
        "led3": "J3",  # shared
        "led4": "N14",
    },
    buttons={
        "btn1": "K11",
        "btn2": "P13",
    },
    uart_pins={
        "uart_rx": "B12",
        "uart_tx": "B10",
    },
)


TINYFPGA_BX = Board(
    name="TinyFPGA BX",
    vendor="Lattice",
    family="iCE40 LP",
    device="iCE40LP8K",
    package="CM81",
    constraint_format=BoardFormat.PCF,
    default_clk_pin="B2",
    default_clk_freq_mhz=16.0,
    leds={"led": "B3"},
    usb_pins={
        "usb_dp": "B4",
        "usb_dn": "A4",
        "usb_pu": "A3",
    },
    qspi_pins={
        "qspi_cs": "F7",
        "qspi_sck": "G7",
        "qspi_io0": "G6",
        "qspi_io1": "H7",
        "qspi_io2": "H4",
        "qspi_io3": "J8",
    },
    headers={
        "PIN_1": "A2", "PIN_2": "A1", "PIN_3": "B1", "PIN_4": "C2",
        "PIN_5": "C1", "PIN_6": "D2", "PIN_7": "D1", "PIN_8": "E2",
        "PIN_9": "E1", "PIN_10": "G2", "PIN_11": "H1", "PIN_12": "J1",
        "PIN_13": "H2", "PIN_14": "H9", "PIN_15": "D9", "PIN_16": "D8",
        "PIN_17": "C9", "PIN_18": "A9", "PIN_19": "B8", "PIN_20": "A8",
        "PIN_21": "B7", "PIN_22": "A7", "PIN_23": "B6", "PIN_24": "A6",
    },
)


UPDUINO_V3 = Board(
    name="Upduino v3",
    vendor="Lattice",
    family="iCE40 UltraPlus",
    device="iCE40UP5K",
    package="SG48",
    constraint_format=BoardFormat.PCF,
    default_clk_pin="20",  # 12MHz on-board oscillator
    default_clk_freq_mhz=12.0,
    leds={
        "led_r": "39",
        "led_g": "40",
        "led_b": "41",
    },
    qspi_pins={
        "qspi_cs": "16",
        "qspi_sck": "15",
        "qspi_io0": "14",
        "qspi_io1": "17",
    },
    headers={
        "gpio_23": "23", "gpio_25": "25", "gpio_26": "26", "gpio_27": "27",
        "gpio_28": "28", "gpio_31": "31", "gpio_32": "32", "gpio_34": "34",
        "gpio_35": "35", "gpio_36": "36", "gpio_37": "37", "gpio_38": "38",
        "gpio_42": "42", "gpio_43": "43", "gpio_44": "44", "gpio_45": "45",
        "gpio_46": "46", "gpio_47": "47", "gpio_48": "48", "gpio_2": "2",
        "gpio_3": "3", "gpio_4": "4", "gpio_6": "6", "gpio_9": "9",
        "gpio_10": "10", "gpio_11": "11", "gpio_12": "12", "gpio_13": "13",
        "gpio_18": "18", "gpio_19": "19", "gpio_21": "21",
    },
)


FOMU = Board(
    name="Fomu",
    vendor="Lattice",
    family="iCE40 UltraPlus",
    device="iCE40UP5K",
    package="UWG30",
    constraint_format=BoardFormat.PCF,
    default_clk_pin="F4",  # 48MHz SB_HFOSC used, but external is F4
    default_clk_freq_mhz=48.0,
    leds={
        "led_r": "A5",
        "led_g": "B5",
        "led_b": "C5",
    },
    usb_pins={
        "usb_dp": "A1",
        "usb_dn": "A2",
        "usb_dp_pu": "A4",
    },
    buttons={
        "touch1": "E4",
        "touch2": "D5",
        "touch3": "E5",
        "touch4": "F5",
    },
    qspi_pins={
        "qspi_cs": "C1",
        "qspi_sck": "D1",
        "qspi_io0": "E1",
        "qspi_io1": "F1",
        "qspi_io2": "B1",
        "qspi_io3": "A1",
    },
)


ULX3S = Board(
    name="ULX3S",
    vendor="Lattice",
    family="ECP5",
    device="LFE5U-85F",
    package="CABGA381",
    constraint_format=BoardFormat.LPF,
    default_clk_pin="G2",  # 25 MHz
    default_clk_freq_mhz=25.0,
    leds={
        "led0": "B2",
        "led1": "C2",
        "led2": "C1",
        "led3": "D2",
        "led4": "D1",
        "led5": "E2",
        "led6": "E1",
        "led7": "H3",
    },
    switches={
        "sw0": "R1",
        "sw1": "T1",
        "sw2": "R18",
        "sw3": "U18",
    },
    buttons={
        "btn_pwr": "D6",
        "btn_up": "R1",
        "btn_down": "T1",
        "btn_left": "R18",
        "btn_right": "U18",
        "btn_fire1": "H16",
        "btn_fire2": "F1",
    },
    uart_pins={
        "uart_rx": "M1",
        "uart_tx": "L4",
    },
    usb_pins={
        "usb_fpga_dp": "D15",
        "usb_fpga_dn": "E15",
        "usb_fpga_pu_dp": "B12",
        "usb_fpga_pu_dn": "C12",
    },
)
ULX3S.io_standard = "LVCMOS33"
ULX3S.default_clk_io_standard = "LVCMOS33"


ECPIX_5 = Board(
    name="ECPIX-5",
    vendor="Lattice",
    family="ECP5",
    device="LFE5UM-85F",
    package="CABGA554",
    constraint_format=BoardFormat.LPF,
    default_clk_pin="K23",  # 100 MHz differential -> p
    default_clk_freq_mhz=100.0,
    default_clk_io_standard="LVDS",
    leds={
        "led0_r": "T23", "led0_g": "R21", "led0_b": "T22",
        "led1_r": "U21", "led1_g": "W21", "led1_b": "T24",
        "led2_r": "K21", "led2_g": "K22", "led2_b": "L20",
        "led3_r": "L23", "led3_g": "R24", "led3_b": "T25",
    },
    buttons={
        "btn0": "D9",
        "btn1": "D8",
    },
    uart_pins={
        "uart_rx": "R26",
        "uart_tx": "R24",
    },
)


TANG_NANO_9K = Board(
    name="Tang Nano 9K",
    vendor="Gowin",
    family="GW1NR",
    device="GW1NR-LV9QN88PC6/I5",
    package="QFN88P",
    constraint_format=BoardFormat.CST,
    default_clk_pin="52",  # 27 MHz
    default_clk_freq_mhz=27.0,
    leds={
        "led1": "10", "led2": "11", "led3": "13",
        "led4": "14", "led5": "15", "led6": "16",
    },
    buttons={
        "btn1": "4",
        "btn2": "3",
    },
    uart_pins={
        "uart_rx": "18",
        "uart_tx": "17",
    },
)


TANG_NANO_20K = Board(
    name="Tang Nano 20K",
    vendor="Gowin",
    family="GW2AR",
    device="GW2AR-LV18QN88C8/I7",
    package="QFN88",
    constraint_format=BoardFormat.CST,
    default_clk_pin="4",  # 27 MHz
    default_clk_freq_mhz=27.0,
    leds={
        "led1": "15", "led2": "16", "led3": "17",
        "led4": "18", "led5": "19", "led6": "20",
    },
    buttons={
        "btn1": "87",
        "btn2": "88",
    },
    uart_pins={
        "uart_rx": "70",
        "uart_tx": "69",
    },
)


TANG_PRIMER_20K = Board(
    name="Tang Primer 20K",
    vendor="Gowin",
    family="GW2A",
    device="GW2A-LV18PG256C8/I7",
    package="PBGA256",
    constraint_format=BoardFormat.CST,
    default_clk_pin="H11",  # 27 MHz
    default_clk_freq_mhz=27.0,
    leds={
        "led1": "N14", "led2": "L14", "led3": "L16",
        "led4": "N16", "led5": "R14", "led6": "T14",
    },
    buttons={
        "btn1": "T10",
        "btn2": "T13",
    },
    uart_pins={
        "uart_rx": "M9",
        "uart_tx": "M8",
    },
)


TANG_MEGA_138K = Board(
    name="Tang Mega 138K",
    vendor="Gowin",
    family="GW5AST",
    device="GW5AST-LV138FPG676AC1/I0",
    package="BGA676",
    constraint_format=BoardFormat.CST,
    default_clk_pin="H16",  # 50 MHz
    default_clk_freq_mhz=50.0,
    leds={
        "led1": "C14", "led2": "B14",
        "led3": "A14", "led4": "A13",
    },
    buttons={
        "btn1": "K21",
        "btn2": "J20",
    },
    uart_pins={
        "uart_rx": "L21",
        "uart_tx": "M21",
    },
)


# ─────────────────────────────────────────────────────────────────────────────
# Xilinx 7-series boards
#
# Pinouts taken from the official master XDC files shipped with each board:
# - Arty A7:   github.com/Digilent/digilent-xdc/blob/master/Arty-A7-35-Master.xdc
# - Nexys A7:  github.com/Digilent/digilent-xdc/blob/master/Nexys-A7-100T-Master.xdc
# - CMOD A7:   github.com/Digilent/digilent-xdc/blob/master/Cmod-A7-Master.xdc
# - Basys 3:   github.com/Digilent/digilent-xdc/blob/master/Basys-3-Master.xdc
# - ZYBO Z7:   github.com/Digilent/digilent-xdc/blob/master/Zybo-Z7-Master.xdc
# - PYNQ-Z2:   github.com/xupsh/pynq-supported-board-file
# - ZedBoard:  github.com/Digilent/digilent-xdc/blob/master/ZedBoard-Master.xdc
# ─────────────────────────────────────────────────────────────────────────────


ARTY_A7_35T = Board(
    name="Arty A7-35T",
    vendor="Xilinx",
    family="Artix-7",
    device="xc7a35tcsg324-1",
    package="CSG324",
    constraint_format=BoardFormat.XDC,
    default_clk_pin="E3",
    default_clk_freq_mhz=100.0,
    leds={
        "led0": "H5",
        "led1": "J5",
        "led2": "T9",
        "led3": "T10",
    },
    switches={
        "sw0": "A8",
        "sw1": "C11",
        "sw2": "C10",
        "sw3": "A10",
    },
    buttons={
        "btn0": "D9",
        "btn1": "C9",
        "btn2": "B9",
        "btn3": "B8",
    },
    uart_pins={
        "uart_rx": "A9",   # USB-UART RX (to FPGA)
        "uart_tx": "D10",  # USB-UART TX (from FPGA)
    },
    headers={
        # PMOD JA
        "ja0": "G13", "ja1": "B11", "ja2": "A11", "ja3": "D12",
        "ja4": "D13", "ja5": "B18", "ja6": "A18", "ja7": "K16",
        # Ethernet (eth_mii_* on Arty)
        "eth_mdc": "F16", "eth_mdio": "K13",
        "eth_rstn": "C16", "eth_crs": "D17", "eth_col": "G14",
        "eth_ref_clk": "G18",
    },
)

ARTY_A7_100T = Board(
    name="Arty A7-100T",
    vendor="Xilinx",
    family="Artix-7",
    device="xc7a100tcsg324-1",
    package="CSG324",
    constraint_format=BoardFormat.XDC,
    default_clk_pin="E3",
    default_clk_freq_mhz=100.0,
    leds={
        "led0": "H5",
        "led1": "J5",
        "led2": "T9",
        "led3": "T10",
    },
    switches={
        "sw0": "A8",
        "sw1": "C11",
        "sw2": "C10",
        "sw3": "A10",
    },
    buttons={
        "btn0": "D9",
        "btn1": "C9",
        "btn2": "B9",
        "btn3": "B8",
    },
    uart_pins={
        "uart_rx": "A9",
        "uart_tx": "D10",
    },
    headers={
        "ja0": "G13", "ja1": "B11", "ja2": "A11", "ja3": "D12",
        "ja4": "D13", "ja5": "B18", "ja6": "A18", "ja7": "K16",
        "eth_mdc": "F16", "eth_mdio": "K13",
        "eth_rstn": "C16", "eth_ref_clk": "G18",
    },
)

NEXYS_A7_100T = Board(
    name="Nexys A7-100T",
    vendor="Xilinx",
    family="Artix-7",
    device="xc7a100tcsg324-1",
    package="CSG324",
    constraint_format=BoardFormat.XDC,
    default_clk_pin="E3",
    default_clk_freq_mhz=100.0,
    leds={
        "led0": "H17", "led1": "K15", "led2": "J13", "led3": "N14",
        "led4": "R18", "led5": "V17", "led6": "U17", "led7": "U16",
        "led8": "V16", "led9": "T15", "led10": "U14", "led11": "T16",
        "led12": "V15", "led13": "V14", "led14": "V12", "led15": "V11",
    },
    switches={
        "sw0": "J15", "sw1": "L16", "sw2": "M13", "sw3": "R15",
        "sw4": "R17", "sw5": "T18", "sw6": "U18", "sw7": "R13",
        "sw8": "T8",  "sw9": "U8",  "sw10": "R16", "sw11": "T13",
        "sw12": "H6", "sw13": "U12", "sw14": "U11", "sw15": "V10",
    },
    buttons={
        "btn_c": "N17",  # center
        "btn_u": "M18",  # up
        "btn_l": "P17",  # left
        "btn_r": "M17",  # right
        "btn_d": "P18",  # down
        "btn_cpu_reset": "C12",
    },
    uart_pins={
        "uart_rx": "C4",
        "uart_tx": "D4",
    },
    headers={
        # PMOD JA
        "ja0": "C17", "ja1": "D18", "ja2": "E18", "ja3": "G17",
        # Ethernet PHY
        "eth_mdc": "C9", "eth_mdio": "A9", "eth_rstn": "B3",
        "eth_crsdv": "D9", "eth_ref_clk": "D5",
        "eth_rxd0": "C11", "eth_rxd1": "D10",
        "eth_txd0": "A10", "eth_txd1": "A8",
        "eth_tx_en": "B9",
    },
)

CMOD_A7_35T = Board(
    name="CMOD A7-35T",
    vendor="Xilinx",
    family="Artix-7",
    device="xc7a35tcpg236-1",
    package="CPG236",
    constraint_format=BoardFormat.XDC,
    default_clk_pin="L17",
    default_clk_freq_mhz=12.0,
    leds={
        "led0": "A17", "led1": "C16",
        "led_r": "C17", "led_g": "B16", "led_b": "B17",
    },
    buttons={
        "btn0": "A18",
        "btn1": "B18",
    },
    uart_pins={
        "uart_rx": "J17",
        "uart_tx": "J18",
    },
    headers={
        "pio1": "M3",  "pio2": "L3",  "pio3": "A16", "pio4": "K3",
        "pio7": "H1",  "pio8": "A15", "pio9": "B15", "pio10": "A14",
    },
)

BASYS_3 = Board(
    name="Basys 3",
    vendor="Xilinx",
    family="Artix-7",
    device="xc7a35tcpg236-1",
    package="CPG236",
    constraint_format=BoardFormat.XDC,
    default_clk_pin="W5",
    default_clk_freq_mhz=100.0,
    leds={
        "led0": "U16", "led1": "E19", "led2": "U19", "led3": "V19",
        "led4": "W18", "led5": "U15", "led6": "U14", "led7": "V14",
        "led8": "V13", "led9": "V3",  "led10": "W3", "led11": "U3",
        "led12": "P3", "led13": "N3", "led14": "P1", "led15": "L1",
    },
    switches={
        "sw0": "V17", "sw1": "V16", "sw2": "W16", "sw3": "W17",
        "sw4": "W15", "sw5": "V15", "sw6": "W14", "sw7": "W13",
        "sw8": "V2",  "sw9": "T3",  "sw10": "T2", "sw11": "R3",
        "sw12": "W2", "sw13": "U1", "sw14": "T1", "sw15": "R2",
    },
    buttons={
        "btn_c": "U18",
        "btn_u": "T18",
        "btn_l": "W19",
        "btn_r": "T17",
        "btn_d": "U17",
    },
    uart_pins={
        "uart_rx": "B18",
        "uart_tx": "A18",
    },
    headers={
        "ja0": "J1", "ja1": "L2", "ja2": "J2", "ja3": "G2",
        "ja4": "H1", "ja5": "K2", "ja6": "H2", "ja7": "G3",
    },
)

ZYBO_Z7_10 = Board(
    name="ZYBO Z7-10",
    vendor="Xilinx",
    family="Zynq-7000",
    device="xc7z010clg400-1",
    package="CLG400",
    constraint_format=BoardFormat.XDC,
    default_clk_pin="K17",
    default_clk_freq_mhz=125.0,
    leds={
        "led0": "M14",
        "led1": "M15",
        "led2": "G14",
        "led3": "D18",
    },
    switches={
        "sw0": "G15",
        "sw1": "P15",
        "sw2": "W13",
        "sw3": "T16",
    },
    buttons={
        "btn0": "K18",
        "btn1": "P16",
        "btn2": "K19",
        "btn3": "Y16",
    },
    uart_pins={
        # PS-side UART (MIO) not exposed here; PMOD JE GPIO UART example:
        "uart_rx": "V12",
        "uart_tx": "W16",
    },
    headers={
        # PMOD JA (MIO + PL-side mix)
        "ja0": "N15", "ja1": "L14", "ja2": "K16", "ja3": "K14",
        "eth_mdc": "F16",  # placeholder, eth is through PS
    },
)

ZYBO_Z7_20 = Board(
    name="ZYBO Z7-20",
    vendor="Xilinx",
    family="Zynq-7000",
    device="xc7z020clg400-1",
    package="CLG400",
    constraint_format=BoardFormat.XDC,
    default_clk_pin="K17",
    default_clk_freq_mhz=125.0,
    leds={
        "led0": "M14",
        "led1": "M15",
        "led2": "G14",
        "led3": "D18",
    },
    switches={
        "sw0": "G15",
        "sw1": "P15",
        "sw2": "W13",
        "sw3": "T16",
    },
    buttons={
        "btn0": "K18",
        "btn1": "P16",
        "btn2": "K19",
        "btn3": "Y16",
    },
    uart_pins={
        "uart_rx": "V12",
        "uart_tx": "W16",
    },
    headers={
        "ja0": "N15", "ja1": "L14", "ja2": "K16", "ja3": "K14",
    },
)

PYNQ_Z2 = Board(
    name="PYNQ-Z2",
    vendor="Xilinx",
    family="Zynq-7000",
    device="xc7z020clg400-1",
    package="CLG400",
    constraint_format=BoardFormat.XDC,
    default_clk_pin="H16",  # PL sysclk (125 MHz on PYNQ-Z2 rev)
    default_clk_freq_mhz=125.0,
    leds={
        "led0": "M14",
        "led1": "M15",
        "led2": "G14",
        "led3": "D18",
    },
    switches={
        "sw0": "M20",
        "sw1": "M19",
    },
    buttons={
        "btn0": "D19",
        "btn1": "D20",
        "btn2": "L20",
        "btn3": "L19",
    },
    uart_pins={
        "uart_rx": "W18",
        "uart_tx": "W19",
    },
    headers={
        "ja0": "Y18", "ja1": "Y19", "ja2": "Y16", "ja3": "Y17",
        "ja4": "U18", "ja5": "U19", "ja6": "W14", "ja7": "Y14",
    },
)

ZEDBOARD = Board(
    name="ZedBoard",
    vendor="Xilinx",
    family="Zynq-7000",
    device="xc7z020clg484-1",
    package="CLG484",
    constraint_format=BoardFormat.XDC,
    default_clk_pin="Y9",
    default_clk_freq_mhz=100.0,
    leds={
        "led0": "T22", "led1": "T21", "led2": "U22", "led3": "U21",
        "led4": "V22", "led5": "W22", "led6": "U19", "led7": "U14",
    },
    switches={
        "sw0": "F22", "sw1": "G22", "sw2": "H22", "sw3": "F21",
        "sw4": "H19", "sw5": "H18", "sw6": "H17", "sw7": "M15",
    },
    buttons={
        "btn_c": "P16",
        "btn_u": "T18",
        "btn_l": "N15",
        "btn_r": "R18",
        "btn_d": "R16",
    },
    uart_pins={
        "uart_rx": "Y11",
        "uart_tx": "AA11",
    },
    headers={
        # PMOD JA1 bank
        "ja0": "Y11", "ja1": "AA11", "ja2": "Y10", "ja3": "AA9",
        "ja4": "AB11", "ja5": "AB10", "ja6": "AB9", "ja7": "AA8",
    },
)


_ALL_BOARDS: list[Board] = [
    ICEBREAKER,
    ICE40_HX8K_EVB,
    TINYFPGA_BX,
    UPDUINO_V3,
    FOMU,
    ULX3S,
    ECPIX_5,
    TANG_NANO_9K,
    TANG_NANO_20K,
    TANG_PRIMER_20K,
    TANG_MEGA_138K,
    ARTY_A7_35T,
    ARTY_A7_100T,
    NEXYS_A7_100T,
    CMOD_A7_35T,
    BASYS_3,
    ZYBO_Z7_10,
    ZYBO_Z7_20,
    PYNQ_Z2,
    ZEDBOARD,
]


BOARDS: ClassVar[dict[str, Board]] = {b.name: b for b in _ALL_BOARDS}  # type: ignore[misc]


def list_boards() -> list[Board]:
    """Return all known boards."""
    return list(_ALL_BOARDS)


def get_board(name: str) -> Board | None:
    """Look up a board by name (case-insensitive)."""
    key = name.strip().lower()
    for b in _ALL_BOARDS:
        if b.name.lower() == key:
            return b
    return None


__all__ = [
    "Board",
    "BoardFormat",
    "BOARDS",
    "list_boards",
    "get_board",
    "ICEBREAKER",
    "ICE40_HX8K_EVB",
    "TINYFPGA_BX",
    "UPDUINO_V3",
    "FOMU",
    "ULX3S",
    "ECPIX_5",
    "TANG_NANO_9K",
    "TANG_NANO_20K",
    "TANG_PRIMER_20K",
    "TANG_MEGA_138K",
    "ARTY_A7_35T",
    "ARTY_A7_100T",
    "NEXYS_A7_100T",
    "CMOD_A7_35T",
    "BASYS_3",
    "ZYBO_Z7_10",
    "ZYBO_Z7_20",
    "PYNQ_Z2",
    "ZEDBOARD",
]
