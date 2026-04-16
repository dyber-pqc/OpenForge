# Activity Bar and Sidebar

The Activity Bar is the vertical strip on the left edge of the OpenForge window. It provides quick access to the major functional areas of the application: file exploration, module hierarchy, search, source control, and extensions.

## File Explorer

The File Explorer shows the project directory tree. It opens automatically when you load a project.

### Features

- **Directory tree**: Expandable tree view of all project files
- **File icons**: Icons differentiate Verilog (.v, .sv), VHDL (.vhd), constraint (.sdc, .pcf), testbench, and output files
- **Context menu**: Right-click for options:
    - New File / New Folder
    - Rename / Delete
    - Open in External Editor
    - Copy Path
    - Open in Terminal

### Opening Files

Double-click any file to open it in the Code Editor panel. Supported file types get syntax highlighting:

| Extension | Language |
|---|---|
| `.v` | Verilog |
| `.sv` | SystemVerilog |
| `.vhd`, `.vhdl` | VHDL |
| `.sdc` | SDC (TCL-based) |
| `.pcf` | iCE40 Constraints |
| `.xdc` | Xilinx Constraints |
| `.tcl` | TCL Script |
| `.spice`, `.sp` | SPICE Netlist |
| `.yaml`, `.yml` | YAML |
| `.py` | Python |

## Hierarchy Browser

The Hierarchy Browser displays the RTL module hierarchy as a tree. It parses the design sources and shows every module instantiation.

### Features

- **Module tree**: Top module at the root, sub-modules as children
- **Port information**: Expand a module to see its input/output ports
- **Instance names**: Shows both the module type and the instance name
- **Cross-probing**: Click a module to open its source file in the editor
- **Search**: Filter the hierarchy by module or instance name

### Tree Structure

```
counter (top)
  +-- dut: counter
       +-- clk (input wire)
       +-- rst_n (input wire)
       +-- enable (input wire)
       +-- count[7:0] (output reg)
       +-- overflow (output wire)
```

The hierarchy updates automatically when source files change or after elaboration.

### Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+H` | Toggle Hierarchy panel |
| `Enter` | Open selected module in editor |
| `Ctrl+F` | Search hierarchy |

## Properties Panel

The Properties panel shows attributes of the currently selected object, whether it is a file, a module, a standard cell, or a timing path.

### Context-Dependent Properties

| Selected Object | Properties Shown |
|---|---|
| Module | Name, port count, instance count, source file |
| Standard cell | Cell name, area, pin list, function |
| Timing path | Slack, depth, startpoint, endpoint |
| Net | Name, driver, fanout, capacitance |
| File | Path, size, last modified, language |

## Source Control (Git)

The Git panel provides built-in source control integration.

### Features

- **Changed files**: List of modified, added, and deleted files
- **Diff viewer**: Side-by-side diff for any changed file
- **Stage/unstage**: Select files to include in the next commit
- **Commit**: Enter a commit message and commit staged changes
- **Branch management**: Create, switch, and merge branches
- **Remote sync**: Push and pull from remote repositories

### Usage

1. Click the Git icon in the Activity Bar
2. Changed files appear in the sidebar
3. Click a file to see its diff
4. Stage files by clicking the `+` icon
5. Enter a commit message and click the checkmark to commit
