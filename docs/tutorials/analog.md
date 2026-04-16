# Tutorial: Analog Simulation -- Op-Amp SPICE Circuit

This tutorial demonstrates analog circuit simulation in OpenForge using ngspice. You will create a simple non-inverting op-amp amplifier, run DC, AC, and transient analyses, and view the results in the waveform panel.

## Prerequisites

- OpenForge installed ([Installation guide](../getting-started/installation.md))
- ngspice installed: `apt install ngspice` (Linux) or `brew install ngspice` (macOS)
- Basic understanding of SPICE netlisting

## Step 1: Create the Project

=== "GUI"

    1. **File > New Project**
    2. Name: `opamp-demo`
    3. Type: **Analog/Mixed-Signal**
    4. Click **Create**

=== "CLI"

    ```bash
    openforge init opamp-demo --type analog
    cd opamp-demo
    ```

## Step 2: Write the SPICE Netlist

Create `src/opamp_amp.spice` with a non-inverting amplifier circuit using an ideal op-amp model:

```spice
* Non-inverting op-amp amplifier
* Gain = 1 + R2/R1 = 1 + 9k/1k = 10 V/V

.title Non-Inverting Amplifier

* Power supplies
VDD vdd gnd DC 5
VSS vss gnd DC -5

* Input signal: 100mV amplitude sine wave at 1kHz
Vin inp gnd SIN(0 0.1 1k)

* Op-amp (ideal subcircuit)
.subckt ideal_opamp inp inn out vdd vss
  Rin inp inn 1G
  Eout out gnd inp inn 100k
  Rout out gnd 1
.ends

X1 inp fb out vdd vss ideal_opamp

* Feedback network
R1 fb gnd 1k
R2 out fb 9k

* Load
RL out gnd 10k

.end
```

This circuit implements:

- A non-inverting amplifier with gain = 1 + R2/R1 = 10 V/V
- Input: 100 mV sine wave at 1 kHz
- Expected output: 1 V sine wave at 1 kHz
- Power rails at +/-5 V

## Step 3: DC Analysis

DC analysis finds the operating point and sweeps a DC parameter.

### Operating Point

=== "GUI"

    1. Open the **SPICE Simulator** panel (**View > SPICE Simulator**)
    2. Load `src/opamp_amp.spice`
    3. Select **Analysis > Operating Point**
    4. Click **Run**
    5. The results table shows DC voltages at all nodes:
        - `inp` = 0 V (DC component of sine input)
        - `out` = 0 V (no DC offset with symmetric supply)
        - `fb` = 0 V

=== "CLI"

    Add to the SPICE file:

    ```spice
    .op
    ```

    ```bash
    openforge spice run src/opamp_amp.spice
    ```

### DC Sweep

Sweep the input voltage and observe the output:

```spice
.dc Vin -0.5 0.5 0.01
```

=== "GUI"

    1. Select **Analysis > DC Sweep**
    2. Set source: `Vin`, start: `-0.5`, stop: `0.5`, step: `0.01`
    3. Click **Run**
    4. The waveform panel plots `v(out)` vs `v(inp)` -- a straight line with slope 10 (the amplifier gain), clipping at the supply rails

## Step 4: AC Analysis

AC analysis determines the frequency response (Bode plot) of the amplifier.

Add to the netlist:

```spice
.ac dec 100 1 10Meg
```

This sweeps frequency from 1 Hz to 10 MHz with 100 points per decade.

=== "GUI"

    1. Select **Analysis > AC Sweep**
    2. Set: logarithmic sweep, 1 Hz to 10 MHz, 100 points/decade
    3. Click **Run**
    4. The waveform panel shows the Bode plot:
        - **Magnitude**: flat at 20 dB (gain of 10) from DC to the bandwidth limit, then rolling off at -20 dB/decade
        - **Phase**: 0 degrees at low frequency, shifting toward -90 degrees at the bandwidth limit

=== "CLI"

    ```bash
    openforge spice run src/opamp_amp.spice --analysis ac
    ```

The ideal op-amp model has no bandwidth limit, so you will see flat gain across the entire frequency range. With a real op-amp model (e.g., LM741 or OPA340), you would see the gain-bandwidth product limiting the response.

## Step 5: Transient Analysis

Transient analysis simulates the circuit over time.

Add to the netlist:

```spice
.tran 1u 5m
```

This simulates 5 ms with a maximum timestep of 1 us.

=== "GUI"

    1. Select **Analysis > Transient**
    2. Set: stop time = `5ms`, max step = `1us`
    3. Click **Run**
    4. The waveform panel shows time-domain signals:
        - `v(inp)`: 100 mV sine wave at 1 kHz
        - `v(out)`: 1 V sine wave at 1 kHz (amplified by 10x)
        - `v(fb)`: feedback node voltage

    Add signals to the waveform viewer by selecting them from the signal tree on the left.

=== "CLI"

    ```bash
    openforge spice run src/opamp_amp.spice --analysis tran --stop 5ms
    ```

## Step 6: Measuring Results

=== "GUI"

    Use the waveform viewer's measurement tools:

    1. Place cursors on the output waveform by clicking
    2. Read peak-to-peak voltage from the cursor delta display
    3. Use **Measure > Frequency** to verify the output frequency matches the input
    4. Use **Measure > Amplitude** to verify the gain

    Expected measurements:

    | Parameter | Input | Output | Ratio |
    |---|---|---|---|
    | Amplitude | 100 mV | 1.0 V | 10x |
    | Frequency | 1 kHz | 1 kHz | 1x |
    | Phase | 0 deg | 0 deg | -- |

## Step 7: Using Real Op-Amp Models

Replace the ideal subcircuit with a real SPICE model. Download a model file (e.g., `LM741.mod` from Texas Instruments) and update the netlist:

```spice
.include models/LM741.mod

* Replace X1 line with:
X1 inp fb out vdd vss LM741
```

With a real model, you will observe:

- **Finite bandwidth**: gain rolls off above the unity-gain bandwidth / closed-loop gain
- **Slew rate limiting**: output distortion at high frequencies
- **Input offset voltage**: small DC offset at the output
- **Input bias current**: affects feedback resistor sizing

## Saving and Exporting

=== "GUI"

    - **File > Save Waveform** exports waveform data as CSV for external analysis
    - **File > Export Plot** saves the waveform view as PNG or SVG
    - Raw SPICE output is saved to `sim_build/opamp_amp.raw`

## Troubleshooting

**ngspice not found**
:   Install ngspice and ensure it is on your PATH. On Windows/WSL2, OpenForge calls ngspice via WSL.

**"Singular matrix" error**
:   The circuit has a topology issue (floating node, shorted voltage sources). Check all nodes have a DC path to ground.

**Unexpected DC offset**
:   With an ideal op-amp, the output should have zero DC offset. With real models, check input bias currents and offset voltage specifications.

**Oscillation in transient analysis**
:   May indicate insufficient decoupling or a feedback stability issue. Add `.options reltol=0.001` to tighten convergence, or check your feedback network.

## Next Steps

- Design a Sallen-Key active filter and simulate its frequency response
- Use the [Transistor Layout](../panels/signoff.md) panel to create custom analog cells
- Explore mixed-signal simulation: combine digital RTL with analog SPICE blocks
- Try Monte Carlo analysis with component tolerances for statistical design
