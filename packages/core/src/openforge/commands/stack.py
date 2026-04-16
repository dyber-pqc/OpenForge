"""Unified undo/redo command stack.

A lightweight implementation of the command pattern used across all
OpenForge panels: editing SDC, moving floorplan shapes, changing
constraints, etc. Every user action that should be reversible pushes a
:class:`Command` subclass onto the stack. The desktop main window wires
``Ctrl+Z`` / ``Ctrl+Shift+Z`` into :class:`GlobalCommandStack`.

Commands are not required to be pure — they simply must be able to undo
the mutation they performed. The stack preserves insertion order and
clamps at ``max_depth`` to bound memory.
"""

from __future__ import annotations

import contextlib
from abc import ABC, abstractmethod
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


class Command(ABC):
    """Reversible action."""

    @abstractmethod
    def execute(self) -> None: ...

    @abstractmethod
    def undo(self) -> None: ...

    @property
    def description(self) -> str:
        return self.__class__.__name__


class LambdaCommand(Command):
    """Ad-hoc command from a pair of callables.

    Useful when a panel wants to push a quick action without subclassing.
    """

    def __init__(
        self,
        do: Callable[[], None],
        undo: Callable[[], None],
        description: str = "Action",
    ) -> None:
        self._do = do
        self._undo = undo
        self._desc = description

    def execute(self) -> None:
        self._do()

    def undo(self) -> None:
        self._undo()

    @property
    def description(self) -> str:
        return self._desc


class CommandStack:
    """Bounded undo/redo stack."""

    def __init__(self, max_depth: int = 100) -> None:
        self.max_depth = max_depth
        self._undo: deque[Command] = deque(maxlen=max_depth)
        self._redo: deque[Command] = deque(maxlen=max_depth)

    def push(self, cmd: Command, execute: bool = True) -> None:
        """Push a command. If ``execute`` is True, runs ``cmd.execute()`` first."""
        if execute:
            cmd.execute()
        self._undo.append(cmd)
        self._redo.clear()

    def undo(self) -> bool:
        if not self._undo:
            return False
        cmd = self._undo.pop()
        try:
            cmd.undo()
        except Exception:
            # Defensive: keep stack consistent even if handler throws.
            pass
        self._redo.append(cmd)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        cmd = self._redo.pop()
        with contextlib.suppress(Exception):
            cmd.execute()
        self._undo.append(cmd)
        return True

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()

    def history(self) -> list[str]:
        return [c.description for c in self._undo]

    def __len__(self) -> int:
        return len(self._undo)


class GlobalCommandStack(CommandStack):
    """Process-wide singleton command stack used by the main window."""

    _instance: GlobalCommandStack | None = None

    @classmethod
    def instance(cls) -> GlobalCommandStack:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


__all__ = ["Command", "CommandStack", "GlobalCommandStack", "LambdaCommand"]
