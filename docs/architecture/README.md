# OpenForge Architecture

This document describes the internal architecture of the OpenForge EDA platform, covering the core library design patterns, tool integration strategy, data flow, and extension points.

## Table of Contents

- [System Overview](#system-overview)
- [Core Library Design](#core-library-design)
  - [Engine Pattern](#engine-pattern)
  - [Flow Pattern](#flow-pattern)
  - [Config Pattern](#config-pattern)
  - [Parser Pattern](#parser-pattern)
- [Synthesis Pipeline](#synthesis-pipeline)
- [Physical Design Pipeline](#physical-design-pipeline)
- [Crypto Verification Pipeline](#crypto-verification-pipeline)
- [Desktop Application](#desktop-application)
- [Web Application](#web-application)
- [Data Flow](#data-flow)
- [Extension Points](#extension-points)

## System Overview

```
                          +------------------+
                          |   openforge CLI  |  (Typer)
                          +--------+---------+
                                   |
            +----------------------+----------------------+
            |                      |                      |
    +-------v--------+    +-------v--------+    +--------v-------+
    | Desktop IDE    |    |  REST API      |    |  Web IDE       |
    | (PySide6/Qt)   |    |  (FastAPI)     |    |  (SvelteKit)   |
    +-------+--------+    +-------+--------+    +--------+-------+
            |                      |                      |
            +----------+-----------+----------+-----------+
                       |                      |
               +-------v--------+    +--------v-------+
               |  openforge     |    |  openforge     |
               |  core library  |    |  crypto suite  |
               +-------+--------+    +--------+-------+
                       |                      |
          +------------+-------------+        |
          |            |             |        |
   +------v--+  +-----v---+  +-----v---+    |
   | Engine  |  |  Flow   |  | Parser  |    |
   | Layer   |  |  Layer  |  | Layer   |    |
   +---------+  +---------+  +---------+    |
          |            |             |        |
   +------v------------v-------------v--------v------+
   |              EDA Tool Binaries                   |
   |  Verilator  Yosys  SymbiYosys  OpenSTA  ...     |
   |  (native or Docker execution)                    |
   +-------------------------------------------------+
```

The platform has three user-facing interfaces (CLI, Desktop IDE, Web IDE) that all call into the same core library. The core library handles tool orchestration, flow management, configuration, and file parsing. The crypto verification suite is a separate package with its own analysis engines.

## Core Library Design

The core library lives in `packages/core/src/openforge/` and is organized around four patterns.

### Engine Pattern

**Location**: `packages/core/src/openforge/engine/`

Every external EDA tool is wrapped by an engine class that inherits from `ToolEngine` (defined in `engine/base.py`).

```
ToolEngine (ABC)
├── BINARY: str              Class-level tool binary name
├── DOCKER_IMAGE: str        Default Docker image
├── backend: ExecutionBackend  NATIVE or DOCKER
├── check_installed() -> bool  [abstract] Is the tool available?
├── version() -> str           [abstract] Tool version string
├── run(args, ...) -> ToolResult        Synchronous execution
├── run_async(args, ...) -> ToolResult  Async execution
└── _build_command(args) -> list[str]   Builds argv (Docker wrapping)
```

**Execution backends**: Each engine supports two backends:

- `NATIVE` -- Invokes the binary directly from `$PATH`. The `_which()` helper checks availability.
- `DOCKER` -- Wraps the command in `docker run --rm`, mounting the working directory at `/work`.

**ToolResult**: Every invocation returns a `ToolResult` dataclass containing `returncode`, `stdout`, `stderr`, `duration`, and the full `command` list. The `.ok` property checks for exit code 0.

**Implemented engines** (14 total):

| Engine | Binary | Purpose |
|--------|--------|---------|
| `VerilatorEngine` | `verilator` | Cycle-accurate RTL simulation |
| `IcarusEngine` | `iverilog` | Event-driven Verilog simulation |
| `GHDLEngine` | `ghdl` | VHDL simulation |
| `YosysEngine` | `yosys` | Synthesis and formal backends |
| `SymbiYosysEngine` | `sby` | Formal verification (BMC, k-induction, PDR) |
| `VeribleEngine` | `verible-verilog-lint` | SystemVerilog lint and format |
| `OpenSTAEngine` | `sta` | Static timing analysis |
| `OpenROADEngine` | `openroad` | Physical design (floorplan through routing) |
| `CocotbEngine` | `cocotb` | Python testbench framework integration |
| `MagicEngine` | `magic` | DRC and parasitic extraction |
| `NetgenEngine` | `netgen` | LVS comparison |
| `KLayoutEngine` | `klayout` | Layout viewing and DRC |

### Flow Pattern

**Location**: `packages/core/src/openforge/flow/`

Verification and design flows are modeled as directed acyclic graphs (DAGs) using the `FlowEngine` class.

```
FlowEngine
├── steps: dict[str, FlowStep]       Registered steps
├── graph: nx.DiGraph                 Dependency graph (networkx)
├── add_step(step) -> None            Register a step with dependencies
├── get_execution_order() -> list     Topological sort
├── run(context) -> dict[str, FlowResult]     Execute all steps
└── run_step(name, context) -> FlowResult     Execute one step
```

**FlowStep** wraps a callable (`execute_fn`) with a name, description, and list of dependency names. The engine resolves execution order via topological sort and skips downstream steps if an upstream dependency fails.

**StepStatus**: `PENDING` -> `RUNNING` -> `PASSED` | `FAILED` | `SKIPPED`

**Pre-built flows**:
- `flow/lint.py` -- Verible lint flow
- `flow/simulate.py` -- Simulation compilation and execution
- `flow/formal.py` -- SymbiYosys formal verification
- `flow/synthesize.py` -- Yosys synthesis pipeline
- `flow/sta.py` -- Static timing analysis via OpenSTA
- `flow/signoff.py` -- DRC/LVS signoff flow

### Config Pattern

**Location**: `packages/core/src/openforge/config/`

All project configuration is defined by Pydantic v2 models in `config/schema.py` and loaded from `openforge.yaml` by `config/loader.py`.

```
OpenForgeConfig (root)
├── project: ProjectConfig         Name, top module, target PDK
├── design: DesignConfig           Source globs, includes, constraints
├── simulation: SimulationConfig   Sim tool, testbenches, coverage options
├── formal: FormalConfig           Formal tool, properties, depth, engines
├── crypto: CryptoVerificationConfig
│   ├── constant_time: ConstantTimeConfig
│   ├── side_channel: SideChannelConfig
│   ├── entropy_analysis: EntropyAnalysisConfig
│   ├── fips_compliance: FIPSComplianceConfig
│   └── ntt_validation: NTTValidationConfig
├── timing: TimingConfig           STA tool, clock period, SDC files
├── power: PowerConfig             Power tool, activity file, corner
└── ci: CIConfig                   GitHub Actions settings
```

The root model uses `extra = "forbid"` so typos in YAML keys are caught as validation errors. All enums use `StrEnum` for clean YAML serialization.

### Parser Pattern

**Location**: `packages/core/src/openforge/parsers/`

OpenForge includes production parsers for standard EDA file formats:

| Parser | Format | Key Data Structures |
|--------|--------|---------------------|
| `liberty.py` | Liberty (.lib) | `LibertyLibrary`, `Cell`, `Pin`, `TimingArc`, `LookupTable` |
| `lef.py` | LEF | `LEFLibrary`, `Layer`, `Via`, `Macro`, `Pin`, `Obstruction` |
| `def_parser.py` | DEF | `DEFDesign`, `Component`, `Net`, `SpecialNet`, `Row` |
| `sdc.py` | SDC | `SDCConstraints`, `ClockDef`, `IODelay`, `PathGroup` |
| `verilog_netlist.py` | Verilog netlist | `VerilogNetlist`, `Module`, `Instance`, `Net`, `Port` |

Design principles:
- Dataclass-based output models (not dicts) for type safety.
- Streaming/incremental parsing for large files (DEF files can be hundreds of MB).
- Parsers are pure functions with no side effects -- they take a `Path` and return structured data.

## Synthesis Pipeline

The synthesis pipeline in `packages/core/src/openforge/synthesis/` orchestrates Yosys:

1. **Script generation**: Build Yosys TCL scripts from the project config, including `read_verilog`, `hierarchy`, `proc`, `opt`, `techmap`, and `abc` commands.
2. **Optimization passes**: Configurable multi-pass ABC optimization with four recipes:
   - `area` -- Minimize cell count and total area
   - `speed` -- Minimize critical path delay
   - `balanced` -- Trade off between area and speed
   - `low-power` -- Minimize switching activity
3. **Liberty mapping**: Map to the target PDK's standard cell library using Liberty timing files.
4. **Netlist analysis**: Parse the output netlist to compute cell usage statistics, area breakdown, and hierarchical resource utilization.

The `synthesis/runner.py` module ties it all together as a `FlowStep` for the DAG engine.

## Physical Design Pipeline

The physical design pipeline in `packages/core/src/openforge/physical/` wraps OpenROAD:

1. **Floorplanning**: Define die area, row structure, and IO pad placement. PDK-specific configs in `share/pdk/` provide technology rules.
2. **Placement**: Global and detailed placement with density targets.
3. **Clock Tree Synthesis (CTS)**: Build balanced clock trees with skew constraints.
4. **Routing**: Global and detailed routing with DRC-clean targets.
5. **Timing** (`physical/timing.py`): Post-layout STA via OpenSTA with parasitic extraction. Slack histograms, critical path browsing, and multi-corner multi-mode (MCMM) analysis.
6. **DRC/LVS** (`physical/drc_lvs.py`): Design rule checking via Magic, layout vs. schematic via Netgen.

OpenROAD commands are generated as TCL scripts with PDK-specific configuration parameters.

## Crypto Verification Pipeline

The crypto verification suite (`packages/crypto/`) provides six analysis engines. See [docs/crypto/README.md](../crypto/README.md) for full details.

- **Constant-time analysis** -- Taint propagation through a dataflow graph to detect secret-dependent control flow.
- **Side-channel simulation** -- Hamming weight/distance power models with TVLA and CPA.
- **Entropy flow analysis** -- Source-to-sink path verification.
- **FIPS 140-3 compliance** -- Automated checks for key zeroization, self-tests, RNG health.
- **NTT validation** -- FIPS 203/204 reference comparison for lattice crypto.
- **Fault injection** -- Glitch, bit-flip, and laser fault models with resilience scoring.

## Desktop Application

**Location**: `packages/desktop/src/openforge_desktop/`

The desktop IDE is built with PySide6 (Qt 6 for Python). The architecture follows a Vivado-style dockable panel layout.

**MainWindow** (`mainwindow.py`):
- Central widget: `EditorPanel` (tabbed RTL editor with syntax highlighting).
- All other panels are `QDockWidget` subclasses that can be rearranged, tabified, floated, or hidden.
- Menus: File, Edit, View, Project, Verify, Synthesize, Analyze, Tools, Help.
- Toolbar: Quick access to New, Open, Save, Run Sim, Synthesize, Verify.
- State persistence: Window geometry and dock layout saved/restored via `QSettings`.

**Panel inventory**:

| Panel | Class | Dock Area | Purpose |
|-------|-------|-----------|---------|
| Editor | `EditorPanel` | Center | Tabbed RTL editor with syntax highlighting |
| Hierarchy | `HierarchyPanel` | Left | Module hierarchy browser |
| Project Explorer | `QDockWidget` | Left | File tree view |
| Console | `ConsolePanel` | Bottom | Command output and log viewer |
| Waveform | `WaveformPanel` | Bottom | Dual-cursor waveform viewer |
| Testbenches | `TestbenchPanel` | Bottom | Test discovery and run manager |
| Reports | `ReportsPanel` | Bottom | Verification/synthesis results |
| Timing | `TimingPanel` | Bottom | Slack histogram, critical paths |
| Properties | `PropertiesPanel` | Right | Signal/cell property inspector |
| Synthesis | `SynthesisPanel` | Right | Resource utilization, cell usage |
| Physical Design | `PhysicalDesignPanel` | Right | P&R flow control and metrics |
| Layout Viewer | `LayoutPanel` | Right | GDSII/DEF visualization |

**Theming**: A comprehensive dark theme (Catppuccin Mocha palette) is applied via QSS in `mainwindow.py`. The stylesheet covers all standard Qt widgets. Custom panels should use existing object names and QSS rules; additional styles can be appended to the `DARK_THEME_QSS` string.

**Dialogs**: `dialogs/new_project.py` (project creation wizard), `dialogs/settings.py` (preferences), `dialogs/signal_browser.py` (signal search and selection).

## Web Application

**Location**: `packages/web/`

The web IDE is a SvelteKit single-page application (SSR disabled) with Tailwind CSS.

**Architecture**:
- **Pages**: SvelteKit file-based routing in `src/routes/`.
- **Components**: Reusable UI components in `src/lib/components/` (Monaco editor, waveform canvas, dashboards).
- **State management**: Svelte stores for project state, WebSocket connection, and UI preferences.
- **API client**: Typed fetch wrapper communicating with the FastAPI backend.
- **Real-time updates**: WebSocket connection to `/ws` for live tool output streaming and job status notifications.

**Key frontend features**:
- Monaco-based RTL editor with tab management
- Canvas-based waveform viewer with zoom/pan/cursors
- Synthesis dashboard with cell usage charts
- Timing analysis with slack histograms
- Security score dashboard with ring charts
- Coverage visualization with annotated source

## Data Flow

A typical verification run flows through the system as follows:

```
User action (CLI / Desktop / Web)
        |
        v
  OpenForgeConfig loaded from openforge.yaml
        |
        v
  FlowEngine builds DAG of FlowSteps
        |
        v
  Topological sort determines execution order
        |
        v
  Each FlowStep invokes a ToolEngine
        |
        v
  ToolEngine.run() / run_async() executes the binary
        |
        v
  ToolResult (stdout, stderr, returncode, duration)
        |
        v
  FlowResult aggregated per step
        |
        v
  Parsers process output files (Liberty, VCD, netlists, etc.)
        |
        v
  Report generator produces HTML / JSON / SARIF / JUnit
        |
        v
  Results displayed in CLI output / Desktop panels / Web dashboards
```

For the web interface, the API server dispatches jobs asynchronously. Progress updates are broadcast via WebSocket to all subscribed clients.

## Extension Points

OpenForge is designed to be extended at multiple levels:

1. **New tool engines**: Subclass `ToolEngine`, implement `check_installed()` and `version()`, add high-level methods. See `CONTRIBUTING.md` for a step-by-step guide.

2. **New file parsers**: Add parser modules in `packages/core/src/openforge/parsers/` following the dataclass-based pattern.

3. **New flow steps**: Create a `FlowStep` with an `execute_fn` callable and register it with the `FlowEngine`. Steps can declare dependencies on other steps.

4. **New desktop panels**: Subclass `QDockWidget` and register in `MainWindow._build_panels()`. The dark theme QSS applies automatically.

5. **New web components**: Create Svelte components in `packages/web/src/lib/components/` with TypeScript and Tailwind.

6. **New crypto analyses**: Add analysis modules in `packages/crypto/` following the `ConstantTimeVerifier` / `SideChannelSimulator` patterns.

7. **Custom PDK support**: Add PDK configuration files in `share/pdk/` with Liberty, LEF, and technology rules. The PDK manager (`packages/core/src/openforge/pdk/manager.py`) handles discovery and loading.

8. **Third-party tool integration**: The engine pattern supports both native and Docker backends, making it straightforward to wrap commercial tools behind the same interface.

---

Copyright 2026 Dyber Inc. | [engineering@dyber.io](mailto:engineering@dyber.io)
