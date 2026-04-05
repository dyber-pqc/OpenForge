"""Desktop project state manager -- single source of truth for the open project."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from PySide6.QtCore import QFileSystemWatcher, QObject, QSettings, Signal

from openforge.config.loader import load_config
from openforge.config.schema import OpenForgeConfig
from openforge.project.manager import Project
from openforge.synthesis.runner import SynthesisResult
from openforge.runner.simulation import SimResult


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_RECENT: Final[int] = 10
_BUILD_SUBDIR: Final[str] = ".openforge/build"
_SETTINGS_KEY_RECENT: Final[str] = "recent_projects"

_HDL_GLOBS: Final[tuple[str, ...]] = ("*.v", "*.sv", "*.svh", "*.vhd", "*.vhdl")
_CONSTRAINT_GLOBS: Final[tuple[str, ...]] = ("*.sdc", "*.xdc")


class DesktopProjectManager(QObject):
    """Manages the currently open project and its state.

    Emits signals when the project changes so that the UI can react
    without polling.  Stores recent-project history in QSettings and
    watches the source tree for external modifications.
    """

    # Signals
    project_opened = Signal(str)          # project path
    project_closed = Signal()
    build_state_changed = Signal(str)     # idle / synthesizing / simulating / ...
    source_files_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._project: Project | None = None
        self._config: OpenForgeConfig | None = None
        self._build_dir: Path | None = None
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._watcher.directoryChanged.connect(self._on_dir_changed)
        self._recent: list[str] = []
        self._settings = QSettings("Dyber", "OpenForge EDA")
        self._build_state: str = "idle"

        # Cached results from the last successful run
        self._last_synth: SynthesisResult | None = None
        self._last_sim: SimResult | None = None

        self._load_recent()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open_project(self, path: Path | str) -> None:
        """Open an OpenForge project rooted at *path*."""
        path = Path(path).resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"Project directory does not exist: {path}")

        # Close any existing project first
        if self._project is not None:
            self.close_project()

        config = load_config(search_dir=path)
        self._project = Project(path=path, config=config)
        self._config = config
        self._build_dir = None
        self._last_synth = None
        self._last_sim = None

        # Watch the project directory for changes
        self._setup_watcher(path)

        # Update recent list
        path_str = str(path)
        if path_str in self._recent:
            self._recent.remove(path_str)
        self._recent.insert(0, path_str)
        self._recent = self._recent[:_MAX_RECENT]
        self._save_recent()

        self.project_opened.emit(path_str)

    def close_project(self) -> None:
        """Close the currently open project."""
        if self._project is None:
            return

        # Remove file watches
        watched_files = self._watcher.files()
        if watched_files:
            self._watcher.removePaths(watched_files)
        watched_dirs = self._watcher.directories()
        if watched_dirs:
            self._watcher.removePaths(watched_dirs)

        self._project = None
        self._config = None
        self._build_dir = None
        self._last_synth = None
        self._last_sim = None
        self._build_state = "idle"

        self.project_closed.emit()

    def is_open(self) -> bool:
        """Return True if a project is currently open."""
        return self._project is not None

    @property
    def project(self) -> Project | None:
        """The currently loaded Project, or None."""
        return self._project

    @property
    def config(self) -> OpenForgeConfig | None:
        """The active project configuration, or None."""
        return self._config

    @property
    def project_path(self) -> Path | None:
        """Root directory of the current project."""
        return self._project.path if self._project else None

    @property
    def build_state(self) -> str:
        return self._build_state

    @build_state.setter
    def build_state(self, value: str) -> None:
        if value != self._build_state:
            self._build_state = value
            self.build_state_changed.emit(value)

    @property
    def last_synth(self) -> SynthesisResult | None:
        return self._last_synth

    @property
    def last_sim(self) -> SimResult | None:
        return self._last_sim

    def source_files(self) -> list[Path]:
        """Return resolved HDL source files from the project config."""
        if self._project is None:
            return []
        return self._project.source_files()

    def constraint_files(self) -> list[Path]:
        """Return resolved constraint files from the project config."""
        if self._project is None:
            return []
        return self._project.constraint_files()

    def build_dir(self) -> Path:
        """Return the build output directory, creating it if needed."""
        if self._build_dir is not None:
            return self._build_dir

        if self._project is None:
            raise RuntimeError("No project is open")

        bd = self._project.path / _BUILD_SUBDIR
        bd.mkdir(parents=True, exist_ok=True)
        self._build_dir = bd
        return bd

    def netlist_path(self) -> Path | None:
        """Return the path to the last synthesis netlist, if available."""
        if self._last_synth and self._last_synth.netlist_path:
            p = Path(self._last_synth.netlist_path)
            return p if p.exists() else None
        return None

    def liberty_path(self) -> Path | None:
        """Resolve the Liberty file from the project PDK setting."""
        if self._config is None:
            return None
        pdk = self._config.project.target_pdk
        if not pdk:
            return None

        from openforge.synthesis.runner import _PDK_LIBERTY

        lib_name = _PDK_LIBERTY.get(pdk)
        if lib_name is None:
            return None

        # Try common PDK install locations
        if self._project is not None:
            candidate = self._project.path / "libs" / lib_name
            if candidate.exists():
                return candidate
        return Path(lib_name)

    def recent_projects(self) -> list[str]:
        """Return list of recently opened project paths."""
        return list(self._recent)

    def store_synth_result(self, result: SynthesisResult) -> None:
        """Cache the latest synthesis result."""
        self._last_synth = result

    def store_sim_result(self, result: SimResult) -> None:
        """Cache the latest simulation result."""
        self._last_sim = result

    def top_module(self) -> str:
        """Return the top module name from config, defaulting to 'top'."""
        if self._config:
            return self._config.project.top_module
        return "top"

    def target_pdk(self) -> str:
        """Return the target PDK name, defaulting to 'sky130'."""
        if self._config and self._config.project.target_pdk:
            return self._config.project.target_pdk
        return "sky130"

    # ------------------------------------------------------------------
    # File watching
    # ------------------------------------------------------------------

    def _setup_watcher(self, root: Path) -> None:
        """Watch the project source directories for changes."""
        dirs_to_watch: list[str] = [str(root)]
        for subdir in ("rtl", "src", "hdl", "tb", "testbench", "tests"):
            d = root / subdir
            if d.is_dir():
                dirs_to_watch.append(str(d))
        self._watcher.addPaths(dirs_to_watch)

    def _on_file_changed(self, path: str) -> None:
        self.source_files_changed.emit()

    def _on_dir_changed(self, path: str) -> None:
        self.source_files_changed.emit()

    # ------------------------------------------------------------------
    # Recent projects persistence
    # ------------------------------------------------------------------

    def _load_recent(self) -> None:
        raw = self._settings.value(_SETTINGS_KEY_RECENT)
        if isinstance(raw, list):
            self._recent = [str(p) for p in raw if p]
        elif isinstance(raw, str) and raw:
            self._recent = [raw]
        else:
            self._recent = []

    def _save_recent(self) -> None:
        self._settings.setValue(_SETTINGS_KEY_RECENT, self._recent)
