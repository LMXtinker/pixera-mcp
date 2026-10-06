"""Environment-driven configuration for the Pixera MCP server.

All settings can be overridden via environment variables (see ``.env.example``):

    PIXERA_HOST         Pixera Native API host           (default 127.0.0.1)
    PIXERA_PORT         JSON/TCP(dl) port set in Pixera   (default 1500)
    PIXERA_TIMEOUT      Per-request timeout, seconds      (default 5.0)
    PIXERA_AUTOCONNECT  Connect to Pixera on startup      (default true)

The ``0xPX`` delimiter is part of the Pixera protocol and is therefore a
constant rather than a setting. Note it is the literal four-character ASCII
string "0xPX" (bytes 30 78 50 58), NOT a hex byte value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

#: The Pixera JSON/TCP(dl) packet delimiter: the literal ASCII string "0xPX".
PIXERA_DELIMITER: bytes = b"0xPX"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    """Runtime configuration, normally built via :meth:`from_env`."""

    host: str = "127.0.0.1"
    port: int = 1500
    timeout: float = 5.0
    autoconnect: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.environ.get("PIXERA_HOST") or "127.0.0.1",
            port=int(float(os.environ.get("PIXERA_PORT") or "1500")),  # "1500.0" from extension UIs
            timeout=float(os.environ.get("PIXERA_TIMEOUT", "5.0")),
            autoconnect=_env_bool("PIXERA_AUTOCONNECT", True),
        )

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"
