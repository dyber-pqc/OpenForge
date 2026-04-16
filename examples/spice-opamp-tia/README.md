# SPICE Op-Amp TIA - Transimpedance Amplifier Simulation

A transimpedance amplifier (TIA) built from a 5-transistor OTA using SkyWater sky130 MOSFET models, simulated with ngspice.

## Circuit Description

The TIA converts an input current to an output voltage using an operational transconductance amplifier (OTA) with resistive feedback.

### OTA Core (5-Transistor)

```
        VDD                    VDD
         |                      |
        M3 (PMOS)             M4 (PMOS)
         |                      |
    drain1 ---+--- drain1  drain2 (Vout)
         |                      |
        M1 (NMOS)             M2 (NMOS)
     inp-|                  inn-|
         |                      |
         +---------- tail ------+
                      |
                     M5 (NMOS)
                 vbias-|
                      |
                     VSS
```

- **M1, M2**: NMOS differential pair (W=2u, L=0.5u)
- **M3, M4**: PMOS active load / current mirror (W=4u, L=0.5u)
- **M5**: NMOS tail current source (W=4u, L=1u), biased at 0.6V

### Feedback Network

- **Rf**: 100 kohm feedback resistor (sets DC transimpedance gain)
- **Cc**: 1 pF compensation capacitor (ensures stability)

### Expected Performance

| Parameter             | Value      |
|-----------------------|------------|
| DC transimpedance     | ~100 kohm (100 dB-ohm) |
| Unity-gain bandwidth  | ~50 MHz    |
| Phase margin          | >60 deg    |
| Supply voltage        | 1.8V       |
| Input current (AC)    | 1 uA       |

## Prerequisites

- [ngspice](http://ngspice.sourceforge.net/) (version 40+)
- SkyWater sky130 PDK models (optional; simplified models included for standalone use)

To use the full sky130 models, download from [google/skywater-pdk](https://github.com/google/skywater-pdk) and uncomment the `.lib` line in `spice/tia.cir`.

## How to Run

### OpenForge CLI

```bash
cd examples/spice-opamp-tia
openforge run                # runs all analyses: OP, transient, AC
openforge run --stage ac     # AC analysis only
```

### OpenForge Desktop

1. File > Open Project and select this folder.
2. The Waveform panel will display simulation results.
3. Click **Run Flow** to execute all SPICE analyses.

### Standalone ngspice

```bash
mkdir -p build
ngspice -b spice/tia.cir
# Results written to build/tia_tran.csv and build/tia_ac.csv
```

### Testbench (pulse stimulus)

```bash
mkdir -p build
ngspice -b spice/tia_tb.cir
# Results written to build/tia_tb_tran.csv
```

## Expected Results

- **Operating point**: Output at ~0.9V (mid-rail), tail current ~20uA
- **Transient**: Output settles to ~1.0V (0.9V + 1uA x 100k = 0.1V swing) within ~1us
- **AC**: Flat gain of ~100 dB-ohm up to ~10 kHz, -20 dB/decade rolloff, crossing 0 dB near 50 MHz

Pre-generated expected waveform data is in the `expected/` directory for comparison.

## File Structure

```
spice-opamp-tia/
  openforge.yaml                  # Project configuration
  spice/tia.cir                   # Main TIA netlist with analyses
  spice/tia_tb.cir                # Testbench with pulse stimulus
  expected/tia_ac_expected.csv    # Reference AC response data
  expected/tia_tran_expected.csv  # Reference transient data
  build/                          # Simulation outputs (after running)
```

<!-- Screenshot placeholder: Bode plot of transimpedance gain -->
