"""Curated library of analog/mixed-signal IP blocks.

Each entry ships a real ngspice ``.subckt`` definition, a list of port
names, default parameters, and a ready-to-run testbench (".cir") that
exercises the block. PDK device names target sky130A
(``sky130_fd_pr__nfet_01v8``, ``sky130_fd_pr__pfet_01v8``,
``sky130_fd_pr__res_xhigh_po``, ``sky130_fd_pr__cap_mim_m3_1``).

The library is intentionally small but real — these are the building
blocks every analog designer reaches for first. Generic (PDK-less)
entries fall back to LEVEL=1 MOS models defined in
``schematic_netlister._BUILTIN_INCLUDES`` so they always simulate.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AnalogIp(BaseModel):
    name: str
    category: str
    description: str
    pdk: str
    spice_subckt: str
    schematic_json: str | None = None
    ports: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    test_bench: str = ""


# ---------------------------------------------------------------------------
# Sky130 building blocks
# ---------------------------------------------------------------------------

_OTA_5T = AnalogIp(
    name="sky130_5t_ota",
    category="ota",
    description="Sky130 5-transistor OTA — diff-pair NMOS input, PMOS mirror load, NMOS tail.",
    pdk="sky130",
    ports=["vinp", "vinn", "vout", "vbias", "vdd", "vss"],
    params={"W_in": "4u", "L_in": "0.5u", "W_load": "8u", "L_load": "0.5u", "W_tail": "8u"},
    spice_subckt="""\
.subckt sky130_5t_ota vinp vinn vout vbias vdd vss
M1 n1   vinp ntail vss sky130_fd_pr__nfet_01v8 W=4u L=0.5u
M2 vout vinn ntail vss sky130_fd_pr__nfet_01v8 W=4u L=0.5u
M3 n1   n1   vdd   vdd sky130_fd_pr__pfet_01v8 W=8u L=0.5u
M4 vout n1   vdd   vdd sky130_fd_pr__pfet_01v8 W=8u L=0.5u
M5 ntail vbias vss vss sky130_fd_pr__nfet_01v8 W=8u L=1u
.ends sky130_5t_ota
""",
    test_bench="""\
* 5T OTA AC test
.include sky130_5t_ota.cir
Vdd vdd 0 1.8
Vss vss 0 0
Vbias vbias 0 0.7
Vinp vinp 0 DC 0.9 AC 1
Vinn vinn 0 0.9
X1 vinp vinn vout vbias vdd vss sky130_5t_ota
CL vout 0 1p
.ac dec 20 1 1g
.print ac vdb(vout) vp(vout)
.end
""",
)

_DIFF_AMP = AnalogIp(
    name="sky130_diff_amp",
    category="opamp",
    description="Single-stage differential amplifier with active load (sky130).",
    pdk="sky130",
    ports=["vinp", "vinn", "voutp", "voutn", "ibias", "vdd", "vss"],
    spice_subckt="""\
.subckt sky130_diff_amp vinp vinn voutp voutn ibias vdd vss
M1 voutn vinp ntail vss sky130_fd_pr__nfet_01v8 W=10u L=0.5u
M2 voutp vinn ntail vss sky130_fd_pr__nfet_01v8 W=10u L=0.5u
RL1 vdd voutn 20k
RL2 vdd voutp 20k
M5 ntail ibias vss vss sky130_fd_pr__nfet_01v8 W=20u L=1u
.ends sky130_diff_amp
""",
    test_bench="""\
.include sky130_diff_amp.cir
Vdd vdd 0 1.8
Vss vss 0 0
Vibias ibias 0 0.7
Vinp vinp 0 DC 0.9 AC 0.5
Vinn vinn 0 0.9
X1 vinp vinn voutp voutn ibias vdd vss sky130_diff_amp
.ac dec 20 1 1g
.end
""",
)

_MILLER_OPAMP = AnalogIp(
    name="sky130_miller_opamp",
    category="opamp",
    description="Two-stage Miller-compensated op-amp (sky130).",
    pdk="sky130",
    ports=["vinp", "vinn", "vout", "vbias", "vdd", "vss"],
    spice_subckt="""\
.subckt sky130_miller_opamp vinp vinn vout vbias vdd vss
* Stage 1: PMOS-input diff pair with NMOS mirror load
M1 n1   vinp ntail vdd sky130_fd_pr__pfet_01v8 W=20u L=0.5u
M2 n2   vinn ntail vdd sky130_fd_pr__pfet_01v8 W=20u L=0.5u
M3 n1   n1   vss   vss sky130_fd_pr__nfet_01v8 W=4u  L=0.5u
M4 n2   n1   vss   vss sky130_fd_pr__nfet_01v8 W=4u  L=0.5u
M5 ntail vbias vdd vdd sky130_fd_pr__pfet_01v8 W=40u L=1u
* Stage 2: common-source NMOS with PMOS current source
M6 vout n2   vss vss sky130_fd_pr__nfet_01v8 W=40u L=0.5u
M7 vout vbias vdd vdd sky130_fd_pr__pfet_01v8 W=80u L=1u
* Miller compensation
Cc n2 vout 1p
Rz n2 vout 2k
.ends sky130_miller_opamp
""",
    test_bench="""\
.include sky130_miller_opamp.cir
Vdd vdd 0 1.8
Vss vss 0 0
Vbias vbias 0 0.9
Vinp vinp 0 DC 0.9 AC 1
Vinn vinn 0 0.9
X1 vinp vinn vout vbias vdd vss sky130_miller_opamp
CL vout 0 2p
.ac dec 20 1 1g
.end
""",
)

_CASCODE_MIRROR = AnalogIp(
    name="sky130_cascode_mirror",
    category="current_mirror",
    description="Wide-swing cascode current mirror (sky130 NMOS).",
    pdk="sky130",
    ports=["iref", "iout", "vss"],
    spice_subckt="""\
.subckt sky130_cascode_mirror iref iout vss
M1 n1   iref n2 vss sky130_fd_pr__nfet_01v8 W=10u L=1u
M2 n2   iref vss vss sky130_fd_pr__nfet_01v8 W=10u L=1u
M3 iout n1   n3 vss sky130_fd_pr__nfet_01v8 W=10u L=1u
M4 n3   iref vss vss sky130_fd_pr__nfet_01v8 W=10u L=1u
.ends sky130_cascode_mirror
""",
    test_bench="""\
.include sky130_cascode_mirror.cir
Vss vss 0 0
Iref iref 0 DC 10u
Vout iout 0 0.9
X1 iref iout vss sky130_cascode_mirror
.dc Vout 0 1.8 0.05
.end
""",
)

_BANDGAP = AnalogIp(
    name="sky130_bandgap_brokaw",
    category="bandgap",
    description="Brokaw bandgap reference, sky130, ~1.25 V output.",
    pdk="sky130",
    ports=["vref", "vdd", "vss"],
    spice_subckt="""\
.subckt sky130_bandgap_brokaw vref vdd vss
* Two BJT branches with PTAT loop
Q1 n1 n2 vss Q2N3904 area=1
Q2 n3 n2 n4 Q2N3904 area=8
R1 n1 vref 10k
R2 n3 vref 10k
R3 n4 vss 1k
* Op-amp forces n1 = n3
EA n2 0 n1 n3 1e5
* Output buffer
Mp vref n2 vdd vdd sky130_fd_pr__pfet_01v8 W=20u L=1u
.ends sky130_bandgap_brokaw
""",
    test_bench="""\
.include sky130_bandgap_brokaw.cir
Vdd vdd 0 1.8
Vss vss 0 0
X1 vref vdd vss sky130_bandgap_brokaw
.dc Vdd 0.8 1.98 0.02
.print dc v(vref)
.end
""",
)

_LDO = AnalogIp(
    name="sky130_ldo_pmos",
    category="ldo",
    description="Low-dropout regulator with PMOS pass device, 1.2 V output.",
    pdk="sky130",
    ports=["vin", "vout", "vref", "vss"],
    spice_subckt="""\
.subckt sky130_ldo_pmos vin vout vref vss
* Error amplifier
EA fb_err 0 vref fb 1e4
* Pass PMOS
Mp vout fb_err vin vin sky130_fd_pr__pfet_01v8 W=400u L=0.5u
* Feedback divider 1.2/1.0
Rfb1 vout fb 100k
Rfb2 fb   vss 500k
* Output cap (ESR)
Resr vout vout_o 50m
Co  vout_o vss 1u
.ends sky130_ldo_pmos
""",
    test_bench="""\
.include sky130_ldo_pmos.cir
Vin  vin 0 1.8
Vref vref 0 1.0
Iload vout 0 PULSE(0 50m 1m 1u 1u 5m 10m)
X1 vin vout vref 0 sky130_ldo_pmos
.tran 10u 20m
.end
""",
)

_STRONG_ARM = AnalogIp(
    name="sky130_strongarm_latch",
    category="comparator",
    description="StrongARM latched comparator (sky130).",
    pdk="sky130",
    ports=["vinp", "vinn", "clk", "outp", "outn", "vdd", "vss"],
    spice_subckt="""\
.subckt sky130_strongarm_latch vinp vinn clk outp outn vdd vss
Mtail ntail clk vss vss sky130_fd_pr__nfet_01v8 W=20u L=0.15u
M1   da vinp ntail vss sky130_fd_pr__nfet_01v8 W=10u L=0.15u
M2   db vinn ntail vss sky130_fd_pr__nfet_01v8 W=10u L=0.15u
M3   outn da   vss vss sky130_fd_pr__nfet_01v8 W=4u  L=0.15u
M4   outp db   vss vss sky130_fd_pr__nfet_01v8 W=4u  L=0.15u
M5   outn outp vdd vdd sky130_fd_pr__pfet_01v8 W=8u  L=0.15u
M6   outp outn vdd vdd sky130_fd_pr__pfet_01v8 W=8u  L=0.15u
M7   outn clk  vdd vdd sky130_fd_pr__pfet_01v8 W=4u  L=0.15u
M8   outp clk  vdd vdd sky130_fd_pr__pfet_01v8 W=4u  L=0.15u
.ends sky130_strongarm_latch
""",
    test_bench="""\
.include sky130_strongarm_latch.cir
Vdd vdd 0 1.8
Vss vss 0 0
Vinp vinp 0 0.91
Vinn vinn 0 0.90
Vclk clk 0 PULSE(0 1.8 1n 0.1n 0.1n 5n 10n)
X1 vinp vinn clk outp outn vdd vss sky130_strongarm_latch
.tran 0.05n 50n
.end
""",
)

_R2R_DAC = AnalogIp(
    name="sky130_r2r_dac4",
    category="dac",
    description="4-bit R-2R DAC primitive.",
    pdk="sky130",
    ports=["b0", "b1", "b2", "b3", "vout", "vref", "vss"],
    spice_subckt="""\
.subckt sky130_r2r_dac4 b0 b1 b2 b3 vout vref vss
R0a b0 n0 20k
R0b n0 vss 20k
R1a b1 n1 20k
R1b n1 n0 10k
R2a b2 n2 20k
R2b n2 n1 10k
R3a b3 n3 20k
R3b n3 n2 10k
Eout vout 0 n3 0 1
Vref vref 0 1.8
.ends sky130_r2r_dac4
""",
    test_bench="""\
.include sky130_r2r_dac4.cir
Vb0 b0 0 1.8
Vb1 b1 0 0
Vb2 b2 0 1.8
Vb3 b3 0 0
X1 b0 b1 b2 b3 vout vref 0 sky130_r2r_dac4
.op
.end
""",
)

_SAR_ADC = AnalogIp(
    name="sky130_sar_adc8_frame",
    category="adc",
    description="8-bit SAR ADC top-level frame (DAC + comparator + SAR logic stub).",
    pdk="sky130",
    ports=["vin", "clk", "d7", "d6", "d5", "d4", "d3", "d2", "d1", "d0", "vdd", "vss"],
    spice_subckt="""\
.subckt sky130_sar_adc8_frame vin clk d7 d6 d5 d4 d3 d2 d1 d0 vdd vss
* Capacitive DAC node (idealised)
Cdac vdac vss 1p
* Comparator
Ecmp comp 0 vin vdac 1e5
* SAR logic stub: just latch comparator into d0
Edff d0 0 comp 0 1
Edummy d1 0 0 0 0
Edummy2 d2 0 0 0 0
Edummy3 d3 0 0 0 0
Edummy4 d4 0 0 0 0
Edummy5 d5 0 0 0 0
Edummy6 d6 0 0 0 0
Edummy7 d7 0 0 0 0
.ends sky130_sar_adc8_frame
""",
    test_bench="""\
.include sky130_sar_adc8_frame.cir
Vdd vdd 0 1.8
Vss vss 0 0
Vin vin 0 SIN(0.9 0.8 1k)
Vclk clk 0 PULSE(0 1.8 0 1n 1n 0.5u 1u)
X1 vin clk d7 d6 d5 d4 d3 d2 d1 d0 vdd vss sky130_sar_adc8_frame
.tran 1u 5m
.end
""",
)

# ---------------------------------------------------------------------------
# Generic (PDK-less)
# ---------------------------------------------------------------------------

_VCO = AnalogIp(
    name="generic_vco",
    category="pll",
    description="Behavioural voltage-controlled oscillator (1 MHz/V).",
    pdk="generic",
    ports=["vctrl", "vout", "vss"],
    spice_subckt="""\
.subckt generic_vco vctrl vout vss
* Behavioural: phase = 2*pi*Kvco*integral(vctrl)
Bphase phase 0 V=2*3.14159*1e6*idt(V(vctrl))
Bvco   vout 0 V=0.9+0.8*sin(V(phase))
.ends generic_vco
""",
    test_bench="""\
.include generic_vco.cir
Vctrl vctrl 0 PWL(0 0.5 5m 1.5)
X1 vctrl vout 0 generic_vco
.tran 10u 5m
.end
""",
)

_CHARGE_PUMP = AnalogIp(
    name="generic_charge_pump",
    category="pll",
    description="Charge-pump for PLL (UP/DN switched current sources).",
    pdk="generic",
    ports=["up", "dn", "vout", "vdd", "vss"],
    spice_subckt="""\
.subckt generic_charge_pump up dn vout vdd vss
Gup vdd vout VALUE={ if(V(up)>0.5, 100u, 0) }
Gdn vout vss VALUE={ if(V(dn)>0.5, 100u, 0) }
.ends generic_charge_pump
""",
    test_bench="""\
.include generic_charge_pump.cir
Vdd vdd 0 1.8
Vup up 0 PULSE(0 1.8 0 1n 1n 1u 4u)
Vdn dn 0 0
Cl vout 0 10p
X1 up dn vout vdd 0 generic_charge_pump
.tran 10n 20u
.end
""",
)

_RING_OSC = AnalogIp(
    name="generic_ring_osc5",
    category="oscillator",
    description="5-stage ring oscillator (sky130 inverters).",
    pdk="sky130",
    ports=["out", "vdd", "vss"],
    spice_subckt="""\
.subckt sky130_inv in out vdd vss
Mp out in vdd vdd sky130_fd_pr__pfet_01v8 W=2u L=0.15u
Mn out in vss vss sky130_fd_pr__nfet_01v8 W=1u L=0.15u
.ends sky130_inv

.subckt generic_ring_osc5 out vdd vss
X1 n1 n2 vdd vss sky130_inv
X2 n2 n3 vdd vss sky130_inv
X3 n3 n4 vdd vss sky130_inv
X4 n4 n5 vdd vss sky130_inv
X5 n5 n1 vdd vss sky130_inv
Eout out 0 n1 0 1
.ends generic_ring_osc5
""",
    test_bench="""\
.include generic_ring_osc5.cir
Vdd vdd 0 1.8
X1 out vdd 0 generic_ring_osc5
.ic v(n1)=0
.tran 10p 20n
.end
""",
)


ANALOG_IP_LIBRARY: dict[str, AnalogIp] = {
    ip.name: ip
    for ip in (
        _OTA_5T,
        _DIFF_AMP,
        _MILLER_OPAMP,
        _CASCODE_MIRROR,
        _BANDGAP,
        _LDO,
        _STRONG_ARM,
        _R2R_DAC,
        _SAR_ADC,
        _VCO,
        _CHARGE_PUMP,
        _RING_OSC,
    )
}


def list_ips(category: str | None = None) -> list[AnalogIp]:
    """Return all IPs, optionally filtered by category."""
    if category is None:
        return list(ANALOG_IP_LIBRARY.values())
    return [ip for ip in ANALOG_IP_LIBRARY.values() if ip.category == category]


__all__ = ["AnalogIp", "ANALOG_IP_LIBRARY", "list_ips"]
