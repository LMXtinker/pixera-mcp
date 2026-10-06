"""Live read-only inspection tools. Feed validation/recommendation with real values."""

from __future__ import annotations

from typing import Any

from .client import PixeraTCPClient


async def list_projectors(client: PixeraTCPClient) -> dict[str, Any]:
    return {"projectors": await client.request("Pixera.Projectors.getProjectorNames")}


async def get_projector_pose(client: PixeraTCPClient, name: str) -> dict[str, Any]:
    pose = await client.get_projector_pose(name)
    return {"projector": name, "position": list(pose["position"]),
            "rotation_deg": list(pose["rotation"])}


async def list_screens(client: PixeraTCPClient) -> dict[str, Any]:
    return {"screens": await client.request("Pixera.Screens.getScreenNames")}


async def list_timelines(client: PixeraTCPClient) -> dict[str, Any]:
    timelines = await client.request("Pixera.Timelines.getTimelines")
    count = len(timelines) if isinstance(timelines, list) else None
    return {"count": count, "timelines": timelines}


async def get_param(client: PixeraTCPClient, path: str) -> dict[str, Any]:
    value = await client.request("Pixera.Compound.getParamValue", {"path": path})
    return {"path": path, "value": value}


async def get_timeline_time(client: PixeraTCPClient, name: str) -> dict[str, Any]:
    seconds = await client.request("Pixera.Compound.getCurrentTimeOfTimelineInSeconds",
                                   {"name": name})
    return {"timeline": name, "seconds": seconds}


async def poll_monitoring(client: PixeraTCPClient) -> dict[str, Any]:
    return {"monitoring": await client.request("Pixera.Utility.pollMonitoring")}
