"""Shared runtime holder so tools/resources can reach the live client.

``server.py`` creates one :class:`Runtime`, populates ``client`` in the FastMCP
lifespan, and passes it into the tool/resource/prompt registration functions.
"""

from __future__ import annotations

from .client import PixeraNotConnected, PixeraTCPClient
from .config import Settings


class Runtime:
    def __init__(self, settings: Settings, client: PixeraTCPClient | None = None):
        self.settings = settings
        self.client = client

    def require_client(self) -> PixeraTCPClient:
        """Return the client or raise an actionable error for offline-only tools."""
        if self.client is None:
            raise PixeraNotConnected(
                "No live Pixera connection is configured. This tool needs Pixera "
                "reachable over JSON/TCP(dl). Enable an API access port in Pixera "
                "settings and set PIXERA_HOST / PIXERA_PORT to match."
            )
        return self.client
