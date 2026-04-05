# Contributing to OpenForge EDA

Thank you for your interest in contributing to OpenForge. This guide covers everything you need to get started, from setting up your development environment to submitting pull requests.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Coding Standards](#coding-standards)
- [Project Structure](#project-structure)
- [Testing](#testing)
- [Adding a New EDA Tool Engine](#adding-a-new-eda-tool-engine)
- [Adding a New File Parser](#adding-a-new-file-parser)
- [Adding a New Desktop Panel](#adding-a-new-desktop-panel)
- [Adding a New Web Component](#adding-a-new-web-component)
- [Documentation Standards](#documentation-standards)
- [Issue Reporting and Feature Requests](#issue-reporting-and-feature-requests)
- [Code of Conduct](#code-of-conduct)

## Getting Started

### Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.12+ | Core library, CLI, API, desktop, crypto |
| Rust | 1.75+ | Performance tools (openforge-ct, openforge-sca, etc.) |
| Node.js | 20+ | Web frontend (SvelteKit) |
| uv | latest | Python workspace and dependency management |
| PySide6 | 6.6+ | Desktop application (Qt bindings) |

Optional EDA tools for runtime testing: Verilator, Yosys, SymbiYosys, Icarus Verilog, GHDL, OpenSTA, OpenROAD, Verible, KLayout, Magic, Netgen.

### Clone and Setup

```bash
# Clone the repository
git clone https://github.com/dyber-pqc/OpenForge.git
cd OpenForge

# Install Python packages in development mode (uv workspace)
uv pip install -e "packages/core[dev]" -e "packages/cli" -e "packages/api" -e "packages/desktop" -e "packages/crypto"

# Build Rust performance tools
cargo build --release

# Install web frontend dependencies
cd packages/web && npm install && cd ../..

# Verify your setup
openforge tools
pytest tests/ -x --tb=short
cargo test --all
```

## Development Workflow

### Branch Naming

Create branches from `dev` (active development) or `main` (hotfixes):

| Prefix | Purpose | Example |
|--------|---------|---------|
| `feature/` | New functionality | `feature/cocotb-runner` |
| `fix/` | Bug fixes | `fix/liberty-parser-escape` |
| `docs/` | Documentation only | `docs/api-websocket` |
| `refactor/` | Code restructuring | `refactor/engine-base` |
| `test/` | Test additions | `test/formal-flow-e2e` |

### Commit Conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `ci`, `chore`.
Scopes: `core`, `cli`, `api`, `web`, `desktop`, `crypto`, `tools`.

Examples:
```
feat(core): add OpenROAD CTS engine wrapper
fix(cli): handle missing openforge.yaml gracefully
docs(api): document WebSocket message format
```

### Pull Request Process

1. Create a branch following the naming conventions above.
2. Make your changes, ensuring all tests pass locally.
3. Run linters: `ruff check packages/` and `cargo clippy --all`.
4. Push your branch and open a PR against `dev`.
5. Fill out the PR template with a summary, testing notes, and screenshots if applicable.
6. At least one maintainer review is required before merge.
7. Squash-merge is the default strategy.

## Coding Standards

### Python

- **Version**: 3.12+ (use modern syntax: `X | Y` unions, `match` statements).
- **Type hints**: Required on all function signatures.
- **Data models**: Pydantic v2 (`BaseModel` with `model_config`) for all configuration and API schemas.
- **Linting/formatting**: `ruff check` and `ruff format`. Configuration lives in `pyproject.toml`.
- **Docstrings**: Google style on public APIs only. Internal helpers do not require docstrings.
- **Imports**: Use `from __future__ import annotations` at the top of every module.

```python
from __future__ import annotations

from pydantic import BaseModel, Field

class SomeConfig(BaseModel):
    """Short description of the config (Google style)."""

    name: str = Field(..., description="Human-readable name")
    timeout: int = Field(default=300, ge=1)
```

### Rust

- **Edition**: Rust 2021.
- **Error handling**: Use `thiserror` for library error types; `anyhow` for binaries.
- **CLI parsing**: `clap` with derive macros.
- **Linting**: `cargo clippy -- -D warnings` must pass.
- **Formatting**: `cargo fmt` with default settings.

### TypeScript / Svelte

- **Strict TypeScript**: Enable `strict: true` in `tsconfig.json`.
- **Framework**: SvelteKit with SSR disabled (SPA mode).
- **Styling**: Tailwind CSS utility classes. No inline styles or CSS modules.
- **State management**: Svelte stores for shared state.
- **Testing**: Vitest for unit tests; Playwright for E2E.

### Qt / PySide6

- **Theme**: Dark theme (Catppuccin Mocha palette) applied via QSS in `mainwindow.py`.
- **Layout**: All panels are `QDockWidget` subclasses so users can rearrange them freely.
- **Naming**: Follow Qt naming conventions -- camelCase for signals/slots, PascalCase for classes.
- **Persistence**: Use `QSettings("Dyber", "OpenForge EDA")` for window geometry and dock state.

## Project Structure

```
openforge/
├── packages/
│   ├── core/           Core orchestration library (engine wrappers, flows, parsers, config)
│   ├── cli/            Typer-based CLI (`openforge` command)
│   ├── api/            FastAPI REST API with WebSocket support
│   ├── web/            SvelteKit + Tailwind web IDE frontend
│   ├── desktop/        PySide6/Qt desktop IDE application
│   └── crypto/         Crypto verification suite (constant-time, SCA, FIPS)
├── tools/              Rust performance tools
│   ├── openforge-ct/     Constant-time analyzer (native speed)
│   ├── openforge-sca/    Side-channel analysis engine
│   ├── openforge-entropy/ Entropy flow analyzer
│   ├── openforge-lint/   Fast RTL linter
│   └── openforge-wave/   High-performance VCD/FST parser
├── share/              SVA libraries, project templates, PDK configs
├── docker/             Container definitions and docker-compose
├── examples/           Example projects (used as smoke tests)
└── tests/              Unit and integration test suites
```

## Testing

### Running Tests

```bash
# Python unit tests
pytest tests/ -v

# Run a specific test module
pytest tests/unit/test_engine_base.py -v

# Rust tests
cargo test --all

# Web frontend tests
cd packages/web && npm test

# Desktop tests (requires display or Xvfb)
pytest tests/unit/ -k "qt" --tb=short
```

### Integration Tests

Integration tests require Docker and external EDA tools:

```bash
# Start tool containers
docker compose -f docker/compose.yml up -d

# Run integration suite
pytest tests/integration/ -v --timeout=120
```

### E2E Tests

- **Web**: Playwright tests in `packages/web/tests/`.
- **Desktop**: pytest-qt tests alongside desktop panel unit tests.

### Example Projects as Smoke Tests

The `examples/` directory contains working projects. CI runs `openforge verify --all` on each:

```bash
cd examples/simple-counter && openforge lint
```

## Adding a New EDA Tool Engine

Tool engines live in `packages/core/src/openforge/engine/`. Every engine subclasses `ToolEngine`.

### Step 1: Create the engine module

Create `packages/core/src/openforge/engine/mytool.py`:

```python
from __future__ import annotations

import re
from openforge.engine.base import ExecutionBackend, ToolEngine, ToolResult

class MyToolEngine(ToolEngine):
    """Wraps the mytool binary."""

    BINARY = "mytool"
    DOCKER_IMAGE = "ghcr.io/example/mytool:latest"

    def check_installed(self) -> bool:
        if self.backend == ExecutionBackend.DOCKER:
            return self.run(["--version"]).ok
        return self._which() is not None

    def version(self) -> str:
        result = self.run(["--version"])
        if result.ok:
            if m := re.search(r"mytool\s+([\d.]+)", result.stdout):
                return m.group(1)
        return "unknown"

    # Add high-level methods (compile, analyze, etc.)
    def analyze(self, sources: list[str], *, cwd: str | None = None) -> ToolResult:
        args = ["--analyze", *sources]
        return self.run(args, cwd=cwd)
```

### Step 2: Implement required abstract methods

- `check_installed() -> bool` -- Return `True` if the binary is available.
- `version() -> str` -- Parse and return the tool version string.

### Step 3: Add high-level convenience methods

Provide domain-specific methods (e.g., `compile`, `simulate`, `synthesize`) that build argument lists and call `self.run()` or `self.run_async()`.

### Step 4: Register in the tools command

Add your engine to `packages/cli/src/openforge_cli/main.py` in the `tools()` function so `openforge tools` reports its status.

### Step 5: Write tests

Add unit tests in `tests/unit/test_engine_mytool.py` that mock subprocess calls and verify argument construction.

## Adding a New File Parser

File parsers live in `packages/core/src/openforge/parsers/`. Follow the existing patterns (Liberty, LEF, DEF, SDC, Verilog netlist).

1. Create `packages/core/src/openforge/parsers/myformat.py`.
2. Define dataclass models for the parsed data structures.
3. Implement a `parse(path: Path) -> MyFormatData` function or class.
4. For large files, use streaming/incremental parsing to avoid loading everything into memory.
5. Export your parser in `packages/core/src/openforge/parsers/__init__.py`.
6. Add tests in `tests/unit/test_parser_myformat.py` with sample fixture files.

## Adding a New Desktop Panel

Desktop panels live in `packages/desktop/src/openforge_desktop/panels/`.

1. Create `packages/desktop/src/openforge_desktop/panels/mypanel.py`.
2. Subclass `QDockWidget`:

```python
from __future__ import annotations
from PySide6.QtWidgets import QDockWidget, QWidget, QVBoxLayout, QLabel

class MyPanel(QDockWidget):
    """My custom panel for OpenForge desktop."""

    def __init__(self, title: str = "My Panel", parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.setObjectName("my_panel_dock")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("Panel content here"))
        self.setWidget(container)
```

3. The dark theme QSS in `mainwindow.py` applies automatically. For custom styling, use object names and add rules to the QSS block.
4. Register the panel in `MainWindow._build_panels()` in `mainwindow.py`.
5. Add a View menu toggle action in `MainWindow._build_menu_bar()`.
6. Set an `objectName` on the dock so `QSettings` can persist its position.

## Adding a New Web Component

Web components live in `packages/web/src/lib/components/`.

1. Create a `.svelte` file following the existing naming convention (PascalCase).
2. Use TypeScript `<script lang="ts">` blocks with strict typing.
3. Style with Tailwind CSS utility classes in the template, not `<style>` blocks.
4. Accept data via props; use Svelte stores for shared state.
5. Export the component from `packages/web/src/lib/components/index.ts` if it is reusable.
6. Add a Vitest test in `packages/web/src/lib/components/__tests__/`.

## Documentation Standards

- Public Python APIs: Google-style docstrings.
- CLI commands: `help` text via Typer annotations.
- API endpoints: FastAPI auto-generates OpenAPI docs at `/docs`.
- Architecture decisions: Record in `docs/architecture/`.
- Keep documentation close to the code it describes.

## Issue Reporting and Feature Requests

- **Bugs**: Open an issue with the `bug` label. Include steps to reproduce, expected vs. actual behavior, and your environment (OS, Python version, tool versions from `openforge tools`).
- **Features**: Open an issue with the `enhancement` label. Describe the use case, proposed solution, and any alternatives considered.
- **Questions**: Use the `question` label or start a GitHub Discussion.

## Code of Conduct

All contributors are expected to follow the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). Be respectful, constructive, and professional in all interactions.

---

Copyright 2026 Dyber Inc. | [engineering@dyber.io](mailto:engineering@dyber.io)
