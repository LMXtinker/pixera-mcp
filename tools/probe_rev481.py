"""Live probes for Pixera API rev 481: what can the show setup automate?

Read phase (always safe, any project):
  * API revision, project name, getHasFunction for every method the server uses.
  * Screens with pose, resource folders, timelines with layers.
  * For every layer that has a model resource: its getLayerJsonDescrip, saved to --out.
    (Input for probe B: can setLayerJsonDescrip assign a model?)

Write phase (``--write``, scratch project only):
  The script refuses unless Session.getProjectName equals --scratch-project.
  It never saves the project.
  A. ResourceFolder.addResource on an OBJ (--obj): does it create a model resource,
     and which type does Resource.getType report?
  B. setLayerJsonDescrip: copy the JSON of a layer that has a model (from the read
     phase) onto a new layer in a new timeline PROBE_<time>; check getAssignedModelResource.
  C. LiveSystem.exportMappings to --out/mappings_<n>: what does Pixera write? Then
     importMappings of the same file back (round trip, no edits) to learn the
     outputIdPathMapStr format and whether import works at all.

Usage:
  python tools/probe_rev481.py --port 1500 --out probe_out
  python tools/probe_rev481.py --port 1500 --out probe_out --write \
      --scratch-project scratch_probe --obj C:/path/screen.obj

Results go to --out/probe_report.json. Read the report, then record findings in
docs/live_probes.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import time
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from pixera_mcp import tools_show as ts  # noqa: E402
from pixera_mcp.client import PixeraError, PixeraTCPClient  # noqa: E402
from pixera_mcp.config import Settings  # noqa: E402

USED_METHODS = [
    "Pixera.Screens.Screen.setPosRotScale", "Pixera.Screens.Screen.getPosition",
    "Pixera.Resources.getResourceFolderWithNamePath", "Pixera.Compound.addResourceToFolder",
    "Pixera.Resources.ResourceFolder.addResource",
    "Pixera.Resources.ResourceFolder.addResourcesFromDirectory",
    "Pixera.Timelines.createTimeline", "Pixera.Timelines.Timeline.createLayer",
    "Pixera.Timelines.Layer.assignResource", "Pixera.Timelines.Layer.setHomeScreenFromScreenName",
    "Pixera.Timelines.Layer.setScaleUnitMode", "Pixera.Timelines.Layer.getLayerJsonDescrip",
    "Pixera.Timelines.Layer.setLayerJsonDescrip", "Pixera.Timelines.Layer.getAssignedModelResource",
    "Pixera.Resources.Resource.setVideoStreamMode", "Pixera.LiveSystems.VideoStream.setActive",
    "Pixera.LiveSystems.LiveSystem.exportMappings", "Pixera.LiveSystems.LiveSystem.importMappings",
    "Pixera.Calibration.setMarkerPositions",
]


async def _try(report: dict[str, Any], key: str, coro) -> Any:
    try:
        value = await coro
        report[key] = value
        return value
    except (PixeraError, ValueError) as exc:
        report[key] = {"error": str(exc), "code": getattr(exc, "code", None)}
        return None


async def read_phase(c: PixeraTCPClient, out: pathlib.Path, report: dict[str, Any]) -> None:
    report["api_revision"] = await c.request("Pixera.Utility.getApiRevision")
    report["project_name"] = await c.request("Pixera.Session.getProjectName")
    report["has_function"] = {m: await c.has_function(m) for m in USED_METHODS}
    await _try(report, "screens", ts.list_screens_detailed(c))
    await _try(report, "resources", ts.list_resources(c, detailed=True))
    timelines = await _try(report, "timelines", ts.list_timelines_detailed(c))
    model_layers = []
    for tl in (timelines or {}).get("timelines", []):
        for layer in tl.get("layers", []):
            if layer.get("model_resource"):
                descrip = await c.request("Pixera.Timelines.Layer.getLayerJsonDescrip",
                                          {"handle": layer["handle"]})
                path = out / f"layer_json_{tl['name']}_{layer['name']}.json".replace(" ", "_")
                path.write_text(str(descrip), encoding="utf-8")
                model_layers.append({"timeline": tl["name"], "layer": layer["name"],
                                     "file": str(path)})
    report["layers_with_model"] = model_layers


async def write_phase(c: PixeraTCPClient, args: argparse.Namespace, out: pathlib.Path,
                      report: dict[str, Any]) -> None:
    w: dict[str, Any] = {}
    report["write"] = w
    for name, probe in (("A", probe_obj_import), ("B", probe_layer_json_model),
                        ("C", probe_mappings)):
        try:
            await probe(c, args, out, report, w)
        except (PixeraError, ValueError, OSError) as exc:
            w[f"{name}_aborted"] = str(exc)


async def probe_obj_import(c, args, out, report, w) -> None:
    if args.obj:
        folders = await c.request("Pixera.Resources.getResourceFolders") or []
        if folders:
            h = await _try(w, "A_addResource_handle", c.request(
                "Pixera.Resources.ResourceFolder.addResource",
                {"handle": folders[0], "path": args.obj}))
            if h:
                for getter in ("getName", "getType", "getId", "getFilePath"):
                    await _try(w, f"A_{getter}", c.request(
                        f"Pixera.Resources.Resource.{getter}", {"handle": h}))


async def probe_layer_json_model(c, args, out, report, w) -> None:
    src_layers = report.get("layers_with_model") or []
    if src_layers:
        tl_name = f"PROBE_{int(time.time())}"
        await _try(w, "B_timeline", ts.create_timeline(c, tl_name))
        tl = await c.request("Pixera.Timelines.getTimelineFromName", {"name": tl_name})
        layer = await c.request("Pixera.Timelines.Timeline.createLayer", {"handle": tl})
        descrip = pathlib.Path(src_layers[0]["file"]).read_text(encoding="utf-8")
        for dominant in (False, True):
            await _try(w, f"B_setLayerJsonDescrip_dominant_{dominant}", c.request(
                "Pixera.Timelines.Layer.setLayerJsonDescrip",
                {"handle": layer, "descrip": descrip, "makeAllDominant": dominant}))
            await _try(w, f"B_model_after_dominant_{dominant}", c.request(
                "Pixera.Timelines.Layer.getAssignedModelResource", {"handle": layer}))
    else:
        w["B"] = "skipped: no layer with a model resource in the project (assign one by drag-drop)"


async def probe_mappings(c, args, out, report, w) -> None:
    systems = await c.request("Pixera.LiveSystems.getLiveSystems") or []
    for i, ls in enumerate(systems):
        target = out / f"mappings_{i}"
        target.mkdir(exist_ok=True)
        await _try(w, f"C_{i}_name", c.request("Pixera.LiveSystems.LiveSystem.getName",
                                               {"handle": ls}))
        await _try(w, f"C_{i}_export", c.request("Pixera.LiveSystems.LiveSystem.exportMappings",
                                                 {"handle": ls, "path": str(target)}))
        w[f"C_{i}_files"] = sorted(str(p.relative_to(target)) for p in target.rglob("*"))
        if args.import_mappings:
            await _try(w, f"C_{i}_import", c.request(
                "Pixera.LiveSystems.LiveSystem.importMappings",
                {"handle": ls, "path": str(target), "outputIdPathMapStr": ""}))


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1500)
    ap.add_argument("--out", default="probe_out")
    ap.add_argument("--write", action="store_true", help="run write probes (scratch project only)")
    ap.add_argument("--scratch-project", help="required with --write; must equal getProjectName")
    ap.add_argument("--obj", help="OBJ file for probe A")
    ap.add_argument("--import-mappings", action="store_true",
                    help="probe C: also re-import the exported mappings (overwrites mappings)")
    args = ap.parse_args()

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    c = PixeraTCPClient(Settings(host=args.host, port=args.port, timeout=10.0))
    report: dict[str, Any] = {"started": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        await c.connect()
        await read_phase(c, out, report)
        if args.write:
            if not args.scratch_project or report["project_name"] != args.scratch_project:
                raise SystemExit(f"Refusing write probes: project is {report['project_name']!r}, "
                                 f"--scratch-project is {args.scratch_project!r}.")
            await write_phase(c, args, out, report)
    finally:
        await c.close()
        path = out / "probe_report.json"
        path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"Report: {path}")


if __name__ == "__main__":
    asyncio.run(main())
