"""pixera-mcp: an MCP server for AV Stumpfl Pixera.

A projection-mapping learning companion and marker-calibration advisor that
exposes Pixera domain knowledge, parameter validation, and a live-hybrid
view-cone marker recommender over the Pixera Native API (JSON-RPC, JSON/TCP(dl)).
"""

__version__ = "0.2.0"

from .config import Settings

__all__ = ["Settings", "__version__"]
