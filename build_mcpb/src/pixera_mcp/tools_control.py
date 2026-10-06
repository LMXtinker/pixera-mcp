"""Live control tools — the subset of Pixera actions the Native API exposes.

Each function takes the connected :class:`PixeraTCPClient`. ``server.py`` wraps
them as MCP tools.
"""

from __future__ import annotations

from typing import Any

from .client import PixeraTCPClient

_TRANSPORT = {"play": 1, "pause": 2, "stop": 3}


def _mode(action: str) -> int:
    a = action.lower()
    if a not in _TRANSPORT:
        raise ValueError(f"action must be one of {list(_TRANSPORT)}, got {action!r}")
    return _TRANSPORT[a]


async def get_api_revision(client: PixeraTCPClient) -> dict[str, Any]:
    return {"api_revision": await client.request("Pixera.Utility.getApiRevision")}


async def ping(client: PixeraTCPClient) -> dict[str, Any]:
    revision = await client.request("Pixera.Utility.getApiRevision")
    await client.request("Pixera.Utility.noop")
    return {"alive": True, "address": client.address, "api_revision": revision}


async def has_function(client: PixeraTCPClient, name: str) -> dict[str, Any]:
    available = await client.request("Pixera.Utility.getHasFunction", {"functionName": name})
    return {"name": name, "available": available}


async def set_timeline_transport(client: PixeraTCPClient, timeline_index: int,
                                 action: str) -> dict[str, Any]:
    mode = _mode(action)
    result = await client.request("Pixera.Compound.setTransportModeOnTimelineAtIndex",
                                  {"index": timeline_index, "mode": mode})
    return {"ok": True, "timeline_index": timeline_index, "action": action, "mode": mode,
            "result": result}


async def set_timeline_transport_by_name(client: PixeraTCPClient, timeline_name: str,
                                         action: str) -> dict[str, Any]:
    mode = _mode(action)
    await client.request("Pixera.Compound.setTransportModeOnTimeline",
                         {"timelineName": timeline_name, "mode": mode})
    return {"ok": True, "timeline": timeline_name, "action": action, "mode": mode}


async def apply_cue(client: PixeraTCPClient, timeline_index: int, cue_index: int) -> dict[str, Any]:
    await client.request("Pixera.Compound.applyCueAtIndexOnTimelineAtIndex",
                         {"cueIndex": cue_index, "timelineIndex": timeline_index})
    return {"ok": True, "timeline_index": timeline_index, "cue_index": cue_index}


async def apply_cue_by_number(client: PixeraTCPClient, timeline_index: int,
                              cue_number: int) -> dict[str, Any]:
    await client.request("Pixera.Compound.applyCueNumberOnTimelineAtIndex",
                         {"cueNumber": cue_number, "timelineIndex": timeline_index})
    return {"ok": True, "timeline_index": timeline_index, "cue_number": cue_number}


async def set_projector_blackout(client: PixeraTCPClient, projector_name: str,
                                 on: bool) -> dict[str, Any]:
    handle = await client.get_projector_handle(projector_name)
    await client.request("Pixera.Projectors.Projector.setBlackout",
                         {"handle": handle, "isActive": on})
    return {"ok": True, "projector": projector_name, "blackout": on}


async def run_calibration(client: PixeraTCPClient, screen_name: str, mode: str = "newCalib",
                          tool: str = "vioso") -> dict[str, Any]:
    handle = await client.get_screen_handle(screen_name)
    await client.request("Pixera.Screens.Screen.runCalibration",
                         {"handle": handle, "mode": mode, "diff": tool})
    return {"ok": True, "screen": screen_name, "mode": mode, "tool": tool}


async def load_warp_file(client: PixeraTCPClient, screen_name: str, path: str,
                         mpcdi: bool = True) -> dict[str, Any]:
    handle = await client.get_screen_handle(screen_name)
    if mpcdi:
        await client.request("Pixera.Screens.Screen.loadWarpFileWithDiff",
                             {"handle": handle, "filePath": path, "diff": "mpcdi"})
    else:
        await client.request("Pixera.Screens.Screen.loadWarpFile",
                             {"handle": handle, "filePath": path})
    return {"ok": True, "screen": screen_name, "path": path, "mpcdi": mpcdi}


async def load_project(client: PixeraTCPClient, path: str) -> dict[str, Any]:
    await client.request("Pixera.Session.loadProject", {"path": path})
    client.invalidate_handles()  # handles are stale after a reload
    return {"ok": True, "path": path, "note": "Handle cache cleared (handles invalidate on reload)."}


async def save_project(client: PixeraTCPClient) -> dict[str, Any]:
    await client.request("Pixera.Session.saveProject")
    return {"ok": True}


async def refresh_mapping(client: PixeraTCPClient, screen_name: str) -> dict[str, Any]:
    handle = await client.get_screen_handle(screen_name)
    await client.request("Pixera.Screens.Screen.triggerRefreshMapping", {"handle": handle})
    return {"ok": True, "screen": screen_name}
