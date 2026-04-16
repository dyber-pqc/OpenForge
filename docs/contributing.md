# Contributing to OpenForge

Thank you for your interest in contributing to OpenForge. This guide covers setting up the development environment, code style expectations, testing procedures, and the pull request process.

## Development Environment Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Rust toolchain (for `tools/` crate development)
- Node.js 20+ (for `packages/web/` development)
- Git

### Clone and Install

```bash
git clone https://github.com/openforge/openforge.git
cd openforge

# Install all Python packages in editable mode
uv sync

# Verify installation
uv run openforge --version
uv run openforge-cli --help
```

### Rust Tools (Optional)

If you are working on the Rust performance tools in `tools/`:

```bash
cd tools
cargo build
cargo test
```

### Web Frontend (Optional)

If you are working on the SvelteKit web frontend:

```bash
cd packages/web
npm install
npm run dev
```

## Repository Structure

```
openforge/
  packages/
    core/       # Core Python library (engines, config, PDK, runners)
    cli/        # CLI application (Typer)
    api/        # REST API server (FastAPI)
    desktop/    # Desktop application (PySide6/Qt)
    web/        # Web frontend (SvelteKit)
    crypto/     # Crypto verification suite
  tools/        # Rust performance tools
    openforge-ct/       # Constant-time verifier
    openforge-sca/      # Side-channel analyzer
    openforge-wave/     # Waveform parser
    openforge-lint/     # HDL linter
    openforge-entropy/  # Entropy flow tracker
  examples/     # Example projects (used as smoke tests)
  installer/    # Build scripts, Docker, platform installers
  docs/         # Documentation (MkDocs)
  tests/        # Integration and E2E tests
```

## Architecture Patterns

Understanding these patterns is essential for contributing effectively.

### Engine Pattern

Each external EDA tool is wrapped by an engine class in `packages/core/src/openforge/engine/`:

```python
from openforge.engine.base import ToolEngine, ExecutionBackend

class YosysEngine(ToolEngine):
    """Wraps the Yosys synthesis tool."""

    name = "yosys"
    binary = "yosys"

    def check_installed(self) -> bool:
        """Return True if yosys is found on PATH."""
        ...

    def run(self, args: list[str], **kwargs) -> ProcessResult:
        """Execute yosys with the given arguments."""
        ...
```

Engines handle:

- Tool binary detection (native and Docker backends)
- Command-line argument construction
- Output parsing
- Error handling and logging

### Flow Pattern

Verification and design flows are DAG-based pipelines defined in `packages/core/src/openforge/flow/`. Each flow step declares its inputs, outputs, and dependencies.

### Config-Driven Design

All operations are configurable via `openforge.yaml`, parsed by Pydantic v2 models in `packages/core/src/openforge/config/schema.py`. The configuration schema is the source of truth for what options exist and their validation rules.

### Worker Pattern (Desktop)

The desktop app runs long-running operations (synthesis, simulation, P&R) in background QThread workers defined in `packages/desktop/src/openforge_desktop/workers.py`. Workers:

- Emit `output_line` signals for real-time console streaming
- Support cancellation via a `_cancelled` flag
- Report results via completion signals

## Code Style

### Python

- **Formatter/Linter**: `ruff` (configured in `pyproject.toml`)
- **Type hints**: Required on all function signatures
- **Docstrings**: Google style, required on public APIs only
- **Pydantic v2**: All data models and configuration

Run the linter:

```bash
uv run ruff check .
uv run ruff format .
```

### Rust

- **Edition**: 2021
- **Linter**: `clippy`
- **Error handling**: `thiserror` for error types
- **CLI parsing**: `clap`

```bash
cd tools
cargo clippy
cargo fmt
```

### TypeScript/Svelte

- **Strict TypeScript** enabled
- **SvelteKit** with SPA mode (SSR disabled)
- **Tailwind CSS** for styling

```bash
cd packages/web
npm run lint
npm run check
```

### Qt/PySide6 (Desktop)

- Follow Qt naming conventions for widgets
- Use QSS for theming (Catppuccin Mocha dark theme)
- All panels are QDockWidget subclasses
- Catppuccin color constants defined per panel file

## Testing

### Python Unit Tests

```bash
uv run pytest packages/core/tests/
uv run pytest packages/api/tests/
uv run pytest packages/cli/tests/
```

### Desktop Tests (pytest-qt)

```bash
uv run pytest packages/desktop/tests/ --qt-api pyside6
```

### Rust Tests

```bash
cd tools
cargo test
```

### Web Tests (Vitest)

```bash
cd packages/web
npm test
```

### Integration Tests

Integration tests use Docker to run full EDA flows:

```bash
uv run pytest tests/integration/ --docker
```

### Smoke Tests

The example projects in `examples/` serve as end-to-end smoke tests:

```bash
cd examples/simple-counter
uv run openforge synth
uv run openforge sim
```

## Pull Request Process

### Branch Naming

- Feature branches: `feature/<name>` (e.g., `feature/spice-simulator`)
- Bug fixes: `fix/<name>` (e.g., `fix/waveform-crash`)
- Branch from: `dev` (active development)
- Merge target: `dev` (PRs to `main` are release merges only)

### PR Checklist

Before submitting a PR:

- [ ] Code passes `ruff check` and `ruff format` with no issues
- [ ] All existing tests pass (`uv run pytest`)
- [ ] New features have corresponding tests
- [ ] New public APIs have docstrings
- [ ] `openforge.yaml` schema changes update the Pydantic models
- [ ] Desktop panel changes follow the Catppuccin Mocha theme
- [ ] Commit messages are descriptive and reference issue numbers

### PR Description

Include:

1. **What** the change does (feature, fix, refactor)
2. **Why** it is needed (context, motivation, issue link)
3. **How** to test it (steps, commands, screenshots for UI changes)
4. **Breaking changes** if any

### Code Review

- All PRs require at least one approval
- CI must pass (lint, test, build)
- Desktop UI changes should include before/after screenshots
- Performance-sensitive changes should include benchmarks

## Adding a New Panel

To add a new panel to the desktop application:

1. Create `packages/desktop/src/openforge_desktop/panels/<name>.py`
2. Define a `QDockWidget` subclass
3. Use the Catppuccin Mocha color constants from `_theme.py`
4. Import the panel in `mainwindow.py` with a try/except guard:

    ```python
    try:
        from openforge_desktop.panels.my_panel import MyPanel
    except ImportError:
        MyPanel = None
    ```

5. Add the panel to the dock layout in `MainWindow._create_dock_widgets()`
6. Add a View menu entry
7. Write tests in `packages/desktop/tests/`

## Adding a New Engine

To wrap a new EDA tool:

1. Create `packages/core/src/openforge/engine/<tool>.py`
2. Subclass `ToolEngine` with `check_installed()` and `run()` methods
3. Add a worker in `packages/desktop/src/openforge_desktop/workers.py`
4. Add a CLI command in `packages/cli/`
5. Add an API endpoint in `packages/api/src/openforge_api/routes/`
6. Write unit tests for parsing and error handling

## Questions?

Open an issue on GitHub or join the discussion in the project's issue tracker. We welcome contributions of all sizes, from documentation fixes to new EDA tool integrations.
