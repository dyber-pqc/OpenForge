# Formal FIFO Proof - Synchronous FIFO Verification

Formal verification of a parameterized synchronous FIFO, proving that it can never overflow or underflow using bounded model checking (BMC) and inductive proof via SymbiYosys.

## What It Proves

### Safety Assertions (must always hold)

| ID | Property | Description |
|----|----------|-------------|
| A1 | Count bounded | `count <= DEPTH` at all times |
| A3 | Full consistent | `full == (count == DEPTH)` |
| A4 | Empty consistent | `empty == (count == 0)` |
| A5 | Mutual exclusion | `full` and `empty` never both asserted |
| A6 | Reset correct | After reset, FIFO is empty with count = 0 |

### Cover Properties (reachability)

| ID | Property | Description |
|----|----------|-------------|
| C1 | Reach full | The FIFO can be filled completely |
| C2 | Recover from full | After full, a read makes it not-full |
| C3 | Reach empty | A non-empty FIFO can be drained to empty |
| C4 | Recover from empty | After empty, a write makes it not-empty |
| C5 | Simultaneous R/W | Read and write occur in the same cycle |
| C6 | Half capacity | FIFO reaches exactly half full |

## Design

- **Module**: `sync_fifo` -- parameterized (default DEPTH=8, WIDTH=8)
- **Architecture**: Binary read/write pointers with extra MSB for full/empty disambiguation
- **Safety**: Writes are silently dropped when full; reads are ignored when empty
- **Count**: Maintained separately for easy formal reasoning

## Prerequisites

- [SymbiYosys](https://github.com/YosysHQ/sby) (formal verification frontend)
- [Yosys](https://github.com/YosysHQ/yosys) (synthesis/elaboration)
- [Z3](https://github.com/Z3Prover/z3) (SMT solver, used as the proof engine)
- [Icarus Verilog](http://iverilog.icarus.com/) (for directed simulation testbench)

Install all via [oss-cad-suite](https://github.com/YosysHQ/oss-cad-suite-build/releases).

## How to Run

### OpenForge CLI

```bash
cd examples/formal-fifo-proof
openforge run                       # full flow: lint -> sim -> BMC -> prove
openforge run --stage formal_bmc    # bounded model checking only
openforge run --stage formal_prove  # inductive proof
```

### OpenForge Desktop

1. File > Open Project and select this folder.
2. The Hierarchy panel shows the `sync_fifo` module.
3. Click **Run Flow** to execute lint, simulation, and formal verification.
4. Results appear in the Reports panel.

### Standalone SymbiYosys

```bash
# Run all tasks (BMC + prove + cover)
sby fifo.sby

# Run specific task
sby fifo.sby bmc
sby fifo.sby prove
sby fifo.sby cover
```

### Directed simulation

```bash
iverilog -o build/fifo_tb.vvp rtl/sync_fifo.v tb/fifo_tb.v
vvp build/fifo_tb.vvp
# View waveforms: gtkwave fifo_tb.vcd
```

## Expected Results

### BMC (Bounded Model Checking, depth=20)

```
SBY  [fifo_bmc] engine_0: Status returned by engine: pass
SBY  [fifo_bmc] DONE (PASS, rc=0)
```

All assertions hold for 20 clock cycles from any reachable state.

### Prove (Inductive proof)

```
SBY  [fifo_prove] engine_0: Status returned by engine: pass
SBY  [fifo_prove] DONE (PASS, rc=0)
```

All assertions hold for all reachable states (unbounded proof).

### Cover

```
SBY  [fifo_cover] engine_0: Status returned by engine: pass
SBY  [fifo_cover] DONE (PASS, rc=0)
```

All cover properties are reachable, confirming the design is not vacuously correct.

### Simulation

```
PASS: all FIFO tests passed
```

## File Structure

```
formal-fifo-proof/
  openforge.yaml       # Project configuration
  rtl/sync_fifo.v      # Synchronous FIFO RTL
  rtl/fifo_props.sv    # SystemVerilog assertions and covers
  fifo.sby             # SymbiYosys configuration
  tb/fifo_tb.v         # Directed simulation testbench
  build/               # Outputs (after running)
```

<!-- Screenshot placeholder: SymbiYosys pass output -->
