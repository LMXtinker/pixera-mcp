"""Async TCP client for the Pixera Native API (JSON-RPC 2.0 over JSON/TCP(dl)).

Framing
-------
Pixera's JSON/TCP(dl) transport separates messages with a delimiter: the literal
four-character ASCII string ``0xPX`` (bytes ``30 78 50 58``) appended directly
after each JSON message, with no spacing. This is NOT a hex byte value. Outgoing
frames are ``json_bytes + b"0xPX"``; incoming frames are read with
``StreamReader.readuntil(b"0xPX")``.

Correlation
-----------
Every request carries an integer ``id``; Pixera echoes the same ``id`` on the
response. A single background reader task resolves the matching
``asyncio.Future`` from the ``_pending`` map, so many requests can be in flight
concurrently over the one socket.

Handles
-------
Many Pixera methods operate on object *handles* obtained from a getter (e.g.
``getProjectorWithName``). Handles become invalid when the project reloads, so
the handle cache is cleared by :meth:`invalidate_handles` (called after
``loadProject``).

.. note::
   Pixera's published docs are inconsistent about handle-scoped method strings:
   some show the class-qualified form (``Pixera.Projectors.Projector.getPosition``)
   and some the short form (``Pixera.Projectors.getPosition``). We use the
   class-qualified form from the rev204 reference. If a live install rejects a
   method, the strings live in the ``get_*`` helpers below — adjust them there.
   This cannot be verified offline, so it is a documented integration risk.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .config import PIXERA_DELIMITER, Settings

log = logging.getLogger("pixera_mcp.client")

# Generous read buffer: monitoring/handle-list responses can be large.
_READ_LIMIT = 16 * 1024 * 1024


class PixeraError(RuntimeError):
    """A JSON-RPC error returned by Pixera, or a transport failure."""

    def __init__(self, message: str, *, code: int | None = None, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


class PixeraNotConnected(PixeraError):
    """Raised when a live call is attempted but no connection is available."""


def _parse_vec3(result: Any) -> tuple[float, float, float]:
    """Coerce a Pixera position/rotation result into an (x, y, z) tuple.

    Handles both the object form ``{"x":..,"y":..,"z":..}`` and the array form
    ``[x, y, z]`` since Pixera's docs disagree on which is returned.
    """
    if isinstance(result, dict):
        return (float(result["x"]), float(result["y"]), float(result["z"]))
    if isinstance(result, (list, tuple)) and len(result) >= 3:
        return (float(result[0]), float(result[1]), float(result[2]))
    raise PixeraError(f"Expected a vec3 result, got: {result!r}")


class PixeraTCPClient:
    """A persistent, reconnecting JSON/TCP(dl) client for one Pixera endpoint."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._id_counter = 0
        self._connect_lock = asyncio.Lock()
        self._handles: dict[str, int] = {}
        self._has_function: dict[str, bool] = {}
        self._closed = False

    # ------------------------------------------------------------------ state
    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    @property
    def address(self) -> str:
        return self._settings.address

    # ------------------------------------------------------------- lifecycle
    async def connect(self) -> None:
        """Open the socket and start the reader. Idempotent."""
        async with self._connect_lock:
            if self.connected:
                return
            self._closed = False
            try:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        self._settings.host, self._settings.port, limit=_READ_LIMIT
                    ),
                    timeout=self._settings.timeout,
                )
            except (OSError, asyncio.TimeoutError) as exc:
                raise PixeraNotConnected(
                    f"Could not connect to Pixera at {self.address}: {exc}. "
                    "In Pixera, open Settings, add an API access port with protocol "
                    "JSON/TCP(dl) on the desired network adapter, and set PIXERA_HOST/"
                    "PIXERA_PORT to match."
                ) from exc
            self._reader_task = asyncio.ensure_future(self._read_loop())
            log.info("Connected to Pixera at %s", self.address)

    async def close(self) -> None:
        """Close the socket and cancel the reader. Safe to call repeatedly."""
        self._closed = True
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._reader_task = None
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
        self._reader = None
        self._writer = None
        self._fail_pending(PixeraNotConnected("Connection closed"))

    async def _ensure_connected(self) -> None:
        if not self.connected:
            if self._closed:
                raise PixeraNotConnected("Client has been closed")
            await self.connect()

    # --------------------------------------------------------------- reading
    async def _read_loop(self) -> None:
        assert self._reader is not None
        reader = self._reader
        try:
            while True:
                raw = await reader.readuntil(PIXERA_DELIMITER)
                payload = raw[: -len(PIXERA_DELIMITER)]
                if not payload.strip():
                    continue
                try:
                    msg = json.loads(payload)
                except json.JSONDecodeError:
                    log.warning("Discarding non-JSON frame: %r", payload[:200])
                    continue
                self._dispatch(msg)
        except asyncio.IncompleteReadError:
            log.info("Pixera closed the connection")
        except asyncio.LimitOverrunError as exc:
            log.error("Frame exceeded read buffer (%s bytes); resetting connection", exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("Reader loop error: %s", exc)
        finally:
            # Mark disconnected; the next request will lazily reconnect.
            if self._writer is not None:
                try:
                    self._writer.close()
                except Exception:  # noqa: BLE001
                    pass
            self._writer = None
            self._reader = None
            self._fail_pending(PixeraNotConnected("Connection lost"))

    def _dispatch(self, msg: dict[str, Any]) -> None:
        msg_id = msg.get("id")
        if msg_id is None:
            log.debug("Ignoring id-less message: %r", msg)
            return
        fut = self._pending.pop(msg_id, None)
        if fut is None or fut.done():
            return
        if "error" in msg and msg["error"] is not None:
            err = msg["error"]
            if isinstance(err, dict):
                message = err.get("message", "Pixera error")
                if "not authorized" in str(message).lower():
                    message += (" Pixera rejected the call. In Pixera's API settings, switch off "
                                "'Restrict Web Access To Actions That Match Allowlist' or add "
                                "this method to the allowlist.")
                fut.set_exception(
                    PixeraError(message, code=err.get("code"), data=err.get("data"))
                )
            else:
                fut.set_exception(PixeraError(str(err)))
        else:
            fut.set_result(msg.get("result"))

    def _fail_pending(self, exc: Exception) -> None:
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(exc)
        self._pending.clear()

    # --------------------------------------------------------------- writing
    async def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send a JSON-RPC request and await its correlated result.

        Raises :class:`PixeraError` on a JSON-RPC error or timeout, and
        :class:`PixeraNotConnected` if the socket is unavailable.
        """
        await self._ensure_connected()
        assert self._writer is not None

        self._id_counter += 1
        req_id = self._id_counter
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params:
            payload["params"] = params

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending[req_id] = fut

        frame = json.dumps(payload, separators=(",", ":")).encode("utf-8") + PIXERA_DELIMITER
        try:
            self._writer.write(frame)
            await self._writer.drain()
        except Exception as exc:  # noqa: BLE001
            self._pending.pop(req_id, None)
            raise PixeraNotConnected(f"Write failed: {exc}") from exc

        try:
            return await asyncio.wait_for(fut, timeout=self._settings.timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(req_id, None)
            raise PixeraError(
                f"Timed out after {self._settings.timeout}s waiting for '{method}'. "
                "Note: JSON/UDP and OSC transports do not reply — ensure the Pixera "
                "port is JSON/TCP(dl)."
            ) from exc

    # --------------------------------------------------------------- handles
    def invalidate_handles(self) -> None:
        """Drop the handle cache. Call after a project reload."""
        self._handles.clear()

    async def has_function(self, name: str) -> bool:
        """``Pixera.Utility.getHasFunction`` with a per-client cache (the set is fixed per build)."""
        if name not in self._has_function:
            self._has_function[name] = bool(
                await self.request("Pixera.Utility.getHasFunction", {"functionName": name}))
        return self._has_function[name]

    async def _handle_for(self, cache_key: str, getter: str, name: str) -> int:
        if cache_key in self._handles:
            return self._handles[cache_key]
        result = await self.request(getter, {"name": name})
        handle = result.get("handle") if isinstance(result, dict) else result
        if handle is None:
            raise PixeraError(f"No handle returned by {getter} for {name!r}")
        self._handles[cache_key] = int(handle)
        return int(handle)

    async def get_projector_handle(self, name: str) -> int:
        return await self._handle_for(
            f"projector:{name}", "Pixera.Projectors.getProjectorWithName", name
        )

    async def get_screen_handle(self, name: str) -> int:
        return await self._handle_for(
            f"screen:{name}", "Pixera.Screens.getScreenWithName", name
        )

    async def get_projector_pose(self, name: str) -> dict[str, tuple[float, float, float]]:
        """Return ``{"position": (x,y,z), "rotation": (x,y,z)}`` for a projector.

        Position is in metres; rotation is Euler angles in degrees (Pixera
        convention). Used by the view-cone marker recommender.
        """
        handle = await self.get_projector_handle(name)
        pos = await self.request("Pixera.Projectors.Projector.getPosition", {"handle": handle})
        rot = await self.request("Pixera.Projectors.Projector.getRotation", {"handle": handle})
        return {"position": _parse_vec3(pos), "rotation": _parse_vec3(rot)}
