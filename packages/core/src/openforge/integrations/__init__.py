"""Third-party EDA tool integrations.

Adapters that map external project formats (OpenLane, Vivado, Quartus, KiCad)
into OpenForge's native ``OpenForgeConfig`` and back out to the external
tool's expected report layout.
"""

from openforge.integrations.openlane import (
    OpenLaneConfig,
    export_openlane_reports,
    import_openlane,
)

__all__ = ["OpenLaneConfig", "export_openlane_reports", "import_openlane"]
