"""Command pattern package.

Re-exports the command stack primitives for convenience.
"""

from openforge.commands.stack import (
    Command,
    CommandStack,
    GlobalCommandStack,
    LambdaCommand,
)

__all__ = ["Command", "CommandStack", "GlobalCommandStack", "LambdaCommand"]
