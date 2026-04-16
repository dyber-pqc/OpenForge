# Code Editor

The OpenForge code editor is a tabbed text editor with Verilog/SystemVerilog/VHDL syntax highlighting, auto-completion, bracket matching, and a minimap. It uses QScintilla when available for enhanced editing features, with a built-in fallback for basic editing.

## Features

### Syntax Highlighting

The editor provides language-aware syntax highlighting with the Catppuccin Mocha color scheme:

| Token Type | Color | Example |
|---|---|---|
| Keywords | Mauve (`#cba6f7`) | `module`, `always`, `assign`, `if`, `else` |
| Types | Yellow (`#f9e2af`) | `wire`, `reg`, `input`, `output`, `integer` |
| Numbers | Peach (`#fab387`) | `8'hFF`, `32'd100`, `1'b0` |
| Strings | Green (`#a6e3a1`) | `"hello"` |
| Comments | Gray (`#6c7086`) | `// comment`, `/* block */` |
| System tasks | Blue (`#89b4fa`) | `$display`, `$finish`, `$dumpvars` |
| Preprocessor | Teal (`#94e2d5`) | `` `define``, `` `include``, `` `timescale`` |

### Auto-Completion

When QScintilla is available, the editor provides context-aware auto-completion:

- **Module names**: Complete module names when typing instance declarations
- **Port names**: Suggest port names during module instantiation
- **Keywords**: Complete Verilog/SystemVerilog keywords
- **Signal names**: Suggest declared signal and variable names

Trigger auto-completion with `Ctrl+Space` or it activates automatically after typing 3 characters.

### Bracket Matching

Matching brackets, parentheses, and begin/end blocks are highlighted when the cursor is adjacent:

- `(` matches `)` 
- `[` matches `]`
- `{` matches `}`
- `begin` matches `end`
- `module` matches `endmodule`

### Line Numbers and Gutter

The left gutter shows:

- **Line numbers** with the current line highlighted
- **Fold markers** for collapsible blocks (modules, always blocks, functions)
- **Breakpoint indicators** (for use with simulation debugging)

### Minimap

A minimap on the right edge provides an overview of the entire file. Click or drag on the minimap to navigate quickly through large files.

## Editing Operations

### Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+S` | Save current file |
| `Ctrl+Z` / `Ctrl+Y` | Undo / Redo |
| `Ctrl+C` / `Ctrl+V` / `Ctrl+X` | Copy / Paste / Cut |
| `Ctrl+A` | Select all |
| `Ctrl+D` | Duplicate line |
| `Ctrl+/` | Toggle line comment |
| `Ctrl+Shift+/` | Toggle block comment |
| `Tab` / `Shift+Tab` | Indent / Unindent selection |
| `Ctrl+G` | Go to line number |
| `Ctrl+F` | Find |
| `Ctrl+H` | Find and replace |
| `Ctrl+Space` | Trigger auto-completion |
| `Ctrl+W` | Close current tab |
| `Ctrl+Shift+W` | Word wrap toggle |
| `F5` | Run simulation (if testbench is open) |

### Context Menu

Right-click in the editor for:

- **Cut / Copy / Paste**
- **Go to Definition** -- jump to the declaration of a module, signal, or parameter
- **Find All References** -- locate all uses of a symbol
- **Rename Symbol** -- rename a signal or parameter across the file
- **Format Document** -- auto-indent the current file
- **Open in External Editor** -- launch the file in your system editor

### Multi-Tab Editing

- Open multiple files simultaneously in tabs
- Drag tabs to reorder them
- Right-click a tab for options: Close, Close Others, Close All, Copy Path
- Modified files show a dot indicator on the tab

## Supported File Types

| Language | Extensions | Features |
|---|---|---|
| Verilog | `.v` | Full highlighting, auto-complete, fold |
| SystemVerilog | `.sv`, `.svh` | Full highlighting, auto-complete, fold |
| VHDL | `.vhd`, `.vhdl` | Highlighting |
| SDC | `.sdc` | TCL highlighting |
| TCL | `.tcl` | TCL highlighting |
| SPICE | `.spice`, `.sp`, `.cir` | SPICE highlighting |
| Python | `.py` | Python highlighting |
| YAML | `.yaml`, `.yml` | YAML highlighting |
| JSON | `.json` | JSON highlighting |

## Configuration

Editor settings are accessible via **Edit > Preferences > Editor**:

| Setting | Default | Description |
|---|---|---|
| Font family | JetBrains Mono | Monospace font for code |
| Font size | 11 pt | Text size |
| Tab size | 4 | Spaces per tab |
| Use spaces | Yes | Insert spaces instead of tabs |
| Word wrap | Off | Wrap long lines |
| Show minimap | Yes | Display the minimap |
| Auto-complete | On | Enable auto-completion |
| Bracket matching | On | Highlight matching brackets |

## Tips

!!! tip "Fast navigation"
    Use `Ctrl+G` to jump to a specific line number. This is especially useful when navigating to error locations reported by Yosys or the simulator.

!!! tip "Multi-cursor editing"
    Hold `Alt` and click to place multiple cursors. Type to edit at all cursor positions simultaneously.

!!! tip "Find in project"
    Use `Ctrl+Shift+F` to search across all files in the project, not just the current file.
