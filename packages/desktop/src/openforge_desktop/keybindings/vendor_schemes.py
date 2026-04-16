"""Keybinding schemes emulating popular vendor EDA tools.

Each :class:`KeyScheme` is a list of :class:`KeyBinding` entries mapping an
OpenForge action identifier (e.g. ``run_synthesis``, ``run_simulation``)
to one or more keyboard shortcut strings in ``QKeySequence`` syntax.

``apply_scheme`` walks the main window's child ``QAction`` instances and overrides
their shortcuts for any action whose ``objectName()`` or ``text()`` matches
a binding's ``action`` field. Unknown actions are silently skipped so
partial schemes are safe.

Shortcuts for Vivado, Innovus and KiCad are taken from their respective
documented defaults; the baseline OpenForge scheme is VS Code-flavoured.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class KeyBinding(BaseModel):
    action: str
    keys: list[str]
    description: str = ""
    contexts: list[str] = Field(default_factory=list)


class KeyScheme(BaseModel):
    name: str
    description: str = ""
    bindings: list[KeyBinding] = Field(default_factory=list)

    def find(self, action: str) -> KeyBinding | None:
        for b in self.bindings:
            if b.action == action:
                return b
        return None


# ---------------------------------------------------------------------------
# Schemes
# ---------------------------------------------------------------------------


DEFAULT_SCHEME = KeyScheme(
    name="OpenForge Default",
    description="VS Code-inspired default bindings.",
    bindings=[
        KeyBinding(action="new_project", keys=["Ctrl+N"], description="New project"),
        KeyBinding(action="open_project", keys=["Ctrl+O"], description="Open project"),
        KeyBinding(action="save", keys=["Ctrl+S"], description="Save"),
        KeyBinding(action="save_all", keys=["Ctrl+Shift+S"], description="Save all"),
        KeyBinding(action="undo", keys=["Ctrl+Z"], description="Undo"),
        KeyBinding(action="redo", keys=["Ctrl+Shift+Z", "Ctrl+Y"], description="Redo"),
        KeyBinding(action="find", keys=["Ctrl+F"], description="Find"),
        KeyBinding(action="command_palette", keys=["Ctrl+Shift+P"], description="Command palette"),
        KeyBinding(action="run_synthesis", keys=["F6"], description="Run synthesis"),
        KeyBinding(action="run_simulation", keys=["F5"], description="Run simulation"),
        KeyBinding(action="run_implementation", keys=["F7"], description="Run implementation"),
        KeyBinding(action="run_bitstream", keys=["F8"], description="Generate bitstream"),
        KeyBinding(action="run_timing", keys=["Ctrl+T"], description="Run timing analysis"),
        KeyBinding(action="toggle_theme", keys=["Ctrl+Shift+T"], description="Toggle theme"),
        KeyBinding(action="preferences", keys=["Ctrl+,"], description="Preferences"),
    ],
)


VIVADO_SCHEME = KeyScheme(
    name="Vivado",
    description="Xilinx Vivado default shortcuts.",
    bindings=[
        KeyBinding(action="new_project", keys=["Ctrl+N"], description="New project"),
        KeyBinding(action="open_project", keys=["Ctrl+O"], description="Open project"),
        KeyBinding(action="save", keys=["Ctrl+S"], description="Save"),
        KeyBinding(action="undo", keys=["Ctrl+Z"], description="Undo"),
        KeyBinding(action="redo", keys=["Ctrl+Y"], description="Redo"),
        KeyBinding(action="run_synthesis", keys=["F11"], description="Run synthesis"),
        KeyBinding(action="run_simulation", keys=["F5"], description="Run behavioral simulation"),
        KeyBinding(action="run_implementation", keys=["Shift+F7"], description="Run implementation"),
        KeyBinding(action="run_bitstream", keys=["Ctrl+B"], description="Generate bitstream"),
        KeyBinding(action="build_all", keys=["Ctrl+Shift+B"], description="Build all"),
        KeyBinding(action="run_timing", keys=["Ctrl+Shift+T"], description="Report timing"),
        KeyBinding(action="find", keys=["Ctrl+F"], description="Find"),
        KeyBinding(action="elaborate", keys=["F4"], description="Elaborate design"),
    ],
)


INNOVUS_SCHEME = KeyScheme(
    name="Innovus",
    description="Cadence Innovus default shortcuts.",
    bindings=[
        KeyBinding(action="run_place", keys=["P"], description="Run placement"),
        KeyBinding(action="run_route", keys=["R"], description="Run routing"),
        KeyBinding(action="run_timing", keys=["T"], description="Report timing"),
        KeyBinding(action="gui_refresh", keys=["G"], description="Refresh GUI"),
        KeyBinding(action="zoom_fit", keys=["F"], description="Fit to window"),
        KeyBinding(action="zoom_in", keys=["Z"], description="Zoom in"),
        KeyBinding(action="zoom_out", keys=["Shift+Z"], description="Zoom out"),
        KeyBinding(action="save", keys=["Ctrl+S"], description="Save design"),
        KeyBinding(action="undo", keys=["Ctrl+Z"], description="Undo"),
        KeyBinding(action="redo", keys=["Ctrl+Shift+Z"], description="Redo"),
        KeyBinding(action="toggle_ruler", keys=["K"], description="Toggle ruler"),
        KeyBinding(action="select_net", keys=["N"], description="Select net"),
    ],
)


KICAD_SCHEME = KeyScheme(
    name="KiCad",
    description="KiCad default shortcuts.",
    bindings=[
        KeyBinding(action="move", keys=["M"], description="Move"),
        KeyBinding(action="rotate", keys=["R"], description="Rotate"),
        KeyBinding(action="edit", keys=["E"], description="Edit properties"),
        KeyBinding(action="draw_wire", keys=["W"], description="Draw wire"),
        KeyBinding(action="place_component", keys=["P"], description="Place component"),
        KeyBinding(action="delete", keys=["Delete"], description="Delete"),
        KeyBinding(action="zoom_in", keys=["+"], description="Zoom in"),
        KeyBinding(action="zoom_out", keys=["-"], description="Zoom out"),
        KeyBinding(action="zoom_fit", keys=["Home"], description="Zoom fit"),
        KeyBinding(action="save", keys=["Ctrl+S"], description="Save"),
        KeyBinding(action="undo", keys=["Ctrl+Z"], description="Undo"),
        KeyBinding(action="redo", keys=["Ctrl+Y"], description="Redo"),
        KeyBinding(action="find", keys=["Ctrl+F"], description="Find"),
    ],
)


ALL_SCHEMES: dict[str, KeyScheme] = {
    s.name: s
    for s in (DEFAULT_SCHEME, VIVADO_SCHEME, INNOVUS_SCHEME, KICAD_SCHEME)
}


# ---------------------------------------------------------------------------
# Apply / load / save
# ---------------------------------------------------------------------------


def apply_scheme(main_window, scheme: KeyScheme) -> int:
    """Apply ``scheme`` to the given main window.

    Returns the number of shortcuts that were actually rebound.
    """
    try:
        from PySide6.QtGui import QAction, QKeySequence
    except Exception:
        return 0
    try:
        actions = main_window.findChildren(QAction)
    except Exception:
        return 0

    bindings_by_key: dict[str, KeyBinding] = {}
    for b in scheme.bindings:
        bindings_by_key[b.action.lower()] = b
        bindings_by_key[b.description.lower()] = b

    rebound = 0
    for act in actions:
        try:
            name = (act.objectName() or "").lower()
            text = (act.text() or "").replace("&", "").lower().strip().rstrip(".")
        except Exception:
            continue
        bnd = bindings_by_key.get(name) or bindings_by_key.get(text)
        if bnd is None:
            continue
        try:
            act.setShortcuts([QKeySequence(k) for k in bnd.keys])
            rebound += 1
        except Exception:
            continue
    return rebound


def load_user_scheme(path: str | Path) -> KeyScheme:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    return KeyScheme(**data)


def save_user_scheme(scheme: KeyScheme, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(scheme.model_dump_json(indent=2), encoding="utf-8")
    return p


__all__ = [
    "ALL_SCHEMES",
    "DEFAULT_SCHEME",
    "INNOVUS_SCHEME",
    "KICAD_SCHEME",
    "VIVADO_SCHEME",
    "KeyBinding",
    "KeyScheme",
    "apply_scheme",
    "load_user_scheme",
    "save_user_scheme",
]
