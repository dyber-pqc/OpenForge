"""First-run / bootstrap utilities: tool installer and updater."""

from openforge.setup.tool_installer import KNOWN_TOOLS, Tool, ToolInstaller
from openforge.setup.updater import UpdateInfo, Updater

__all__ = ["KNOWN_TOOLS", "Tool", "ToolInstaller", "UpdateInfo", "Updater"]
