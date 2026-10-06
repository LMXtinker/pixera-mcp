"""MCP resource registration: knowledge guides (offline) + live observable state.

Knowledge resources are static Markdown bundled under ``knowledge/`` and always
work. Live resources read the connected Pixera and degrade to a clear "offline"
message when no connection is available.
"""

from __future__ import annotations

import json
from pathlib import Path

from .client import PixeraError
from .runtime import Runtime

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"

# (uri-slug, filename, human title)
_GUIDES = [
    ("projection-mapping-101", "projection_mapping_101.md", "Projection Mapping 101 (Pixera)"),
    ("warping", "warping.md", "Warping tools and workflow"),
    ("softedge", "softedge.md", "Soft edge / edge blending"),
    ("marker-calibration", "marker_calibration.md", "Marker calibration (deep dive)"),
    ("calibration-algorithms", "calibration_algorithms.md", "Calibration algorithm taxonomy"),
    ("view-cone-methodology", "view_cone_methodology.md", "View-cone marker recommendation method"),
    ("camera-calibration", "camera_calibration_vioso.md", "Camera-based (VIOSO) calibration"),
]
_REFERENCES = [
    ("parameters", "parameter_reference.md", "Pixera parameter reference"),
    ("glossary", "glossary.md", "Glossary"),
    ("api-capabilities", "api_capabilities.md", "API: controllable vs UI-only"),
]


def read_guide(filename: str) -> str:
    return (KNOWLEDGE_DIR / filename).read_text(encoding="utf-8")


def _register_static(mcp, uri: str, title: str, filename: str) -> None:
    def reader() -> str:
        return read_guide(filename)

    reader.__name__ = "guide_" + filename.replace(".", "_")
    reader.__doc__ = title
    mcp.resource(uri, name=title, description=title, mime_type="text/markdown")(reader)


def register_resources(mcp, runtime: Runtime) -> None:
    for slug, filename, title in _GUIDES:
        _register_static(mcp, f"pixera://guide/{slug}", title, filename)
    for slug, filename, title in _REFERENCES:
        _register_static(mcp, f"pixera://reference/{slug}", title, filename)

    @mcp.resource("pixera://status", name="Pixera status",
                  description="Connection state and API revision", mime_type="application/json")
    async def status() -> str:
        client = runtime.client
        if client is None:
            return json.dumps({"connected": False, "reason": "no client configured"})
        try:
            revision = await client.request("Pixera.Utility.getApiRevision")
            return json.dumps({"connected": True, "address": client.address,
                               "api_revision": revision})
        except PixeraError as exc:
            return json.dumps({"connected": False, "address": client.address, "error": str(exc)})

    @mcp.resource("pixera://projectors", name="Projectors",
                  description="Names of projectors in the current project", mime_type="application/json")
    async def projectors() -> str:
        try:
            names = await runtime.require_client().request("Pixera.Projectors.getProjectorNames")
            return json.dumps({"projectors": names})
        except PixeraError as exc:
            return json.dumps({"error": str(exc)})

    @mcp.resource("pixera://screens", name="Screens",
                  description="Names of screens in the current project", mime_type="application/json")
    async def screens() -> str:
        try:
            names = await runtime.require_client().request("Pixera.Screens.getScreenNames")
            return json.dumps({"screens": names})
        except PixeraError as exc:
            return json.dumps({"error": str(exc)})

    @mcp.resource("pixera://timeline/{name}/time", name="Timeline playhead",
                  description="Current playhead time (seconds) of a timeline", mime_type="application/json")
    async def timeline_time(name: str) -> str:
        try:
            t = await runtime.require_client().request(
                "Pixera.Compound.getCurrentTimeOfTimelineInSeconds", {"name": name})
            return json.dumps({"timeline": name, "seconds": t})
        except PixeraError as exc:
            return json.dumps({"timeline": name, "error": str(exc)})
