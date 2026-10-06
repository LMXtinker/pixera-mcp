"""Show-setup tools: inspect and build screens, resources, timelines and layers.

Method names and params follow the rev 481 API JSON (see ``api_index.py``). All
handle-scoped calls use the class-qualified form with a ``handle`` param, which is
the form confirmed live on Pixera 26.1.

Units are Pixera-native: positions in metres, rotations in degrees, as shown in
the Pixera inspector. Pixera is right-handed and Y-up (confirmed live, see
``axes.py``). ``set_screen_pose(convention="blender")`` converts a Blender (Z-up)
position; rotations are always Pixera-native because the Euler order is unknown.

Live findings (Pixera 26.1, rev 481): ``Layer.assignResource`` with the id of a
``3DModel`` resource sets the layer's model (``getAssignedModelResource``) and leaves
the media resource alone, so one layer can carry both. Screen names need not be
unique, so listings go by handle.

Setup tools refuse to modify protected timelines (see ``tools_call.protected_prefixes``).
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from .axes import blender_to_pixera_position
from .client import PixeraError, PixeraTCPClient, _parse_vec3
from .tools_call import is_protected_timeline, protected_prefixes

#: ``Layer.setScaleUnitMode`` values (from the API comment).
SCALE_MODES = {"fill": 1, "fit": 2, "stretch": 3, "resource": 4, "model_1to1": 5}

_TS = "Pixera.Timelines"
_RS = "Pixera.Resources"
_SC = "Pixera.Screens"


def _vec(value: Any) -> list[float] | Any:
    try:
        return list(_parse_vec3(value))
    except (PixeraError, KeyError, TypeError, ValueError):
        return value


async def _safe(client: PixeraTCPClient, method: str, params: dict[str, Any] | None = None,
                errors: list[str] | None = None) -> Any:
    """Request that records a failure in ``errors`` instead of aborting a listing."""
    try:
        return await client.request(method, params)
    except PixeraError as exc:
        if errors is not None:
            errors.append(f"{method}: {exc}")
        return None


def _guard_timeline_name(name: str) -> None:
    if is_protected_timeline(name):
        raise PixeraError(f"Timeline {name!r} is protected (prefix in {list(protected_prefixes())}); "
                          "setup tools do not modify it.")


# ======================================================================= screens
async def list_screens_detailed(client: PixeraTCPClient) -> dict[str, Any]:
    """Every screen with handle, position (m), rotation (deg), scale, visibility, blackout."""
    errors: list[str] = []
    screens = []
    for h in await client.request(f"{_SC}.getScreens") or []:
        hp = {"handle": h}
        screens.append({
            "name": await _safe(client, f"{_SC}.Screen.getName", hp, errors),
            "handle": h,
            "position_m": _vec(await _safe(client, f"{_SC}.Screen.getPosition", hp, errors)),
            "rotation_deg": _vec(await _safe(client, f"{_SC}.Screen.getRotation", hp, errors)),
            "scale": _vec(await _safe(client, f"{_SC}.Screen.getScale", hp, errors)),
            "visible": await _safe(client, f"{_SC}.Screen.getIsVisible", hp, errors),
            "blackout": await _safe(client, f"{_SC}.Screen.getBlackout", hp, errors),
        })
    out: dict[str, Any] = {"count": len(screens), "screens": screens}
    names = [s["name"] for s in screens]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        out["duplicate_names"] = dupes
        out["note"] = ("Name lookups (getScreenWithName, setHomeScreenFromScreenName) are "
                       "ambiguous for duplicate names; rename the screens in Pixera.")
    if errors:
        out["errors"] = errors
    return out


async def set_screen_pose(client: PixeraTCPClient, screen_name: str,
                          position: list[float] | None = None,
                          rotation: list[float] | None = None,
                          scale: list[float] | None = None,
                          convention: str = "pixera") -> dict[str, Any]:
    """Set any of position (m), rotation (deg), scale on a screen; read the pose back.

    Omitted vectors stay unchanged (``setPosRotScale`` takes optional params).
    ``convention="blender"`` treats ``position`` as Blender Z-up coordinates and
    converts it with :func:`~pixera_mcp.axes.blender_to_pixera_position`. Rotation is
    refused with that convention, since Pixera's Euler order is not confirmed.
    """
    if convention not in ("pixera", "blender"):
        raise ValueError(f"convention must be 'pixera' or 'blender', got {convention!r}")
    if convention == "blender":
        if rotation is not None:
            raise ValueError("rotation cannot be converted from Blender yet; pass it in Pixera "
                             "degrees with convention='pixera'")
        if position is not None:
            position = blender_to_pixera_position(position)
    params: dict[str, Any] = {}
    for vec, keys in ((position, ("xPos", "yPos", "zPos")),
                      (rotation, ("xRot", "yRot", "zRot")),
                      (scale, ("xScale", "yScale", "zScale"))):
        if vec is None:
            continue
        if len(vec) != 3:
            raise ValueError(f"expected 3 values for {keys[0][1:]}, got {len(vec)}")
        params.update({k: float(v) for k, v in zip(keys, vec)})
    if not params:
        raise ValueError("give at least one of position, rotation, scale")
    h = await client.get_screen_handle(screen_name)
    ok = await client.request(f"{_SC}.Screen.setPosRotScale", {"handle": h, **params})
    hp = {"handle": h}
    return {
        "screen": screen_name,
        "accepted": ok,
        "position_m": _vec(await client.request(f"{_SC}.Screen.getPosition", hp)),
        "rotation_deg": _vec(await client.request(f"{_SC}.Screen.getRotation", hp)),
        "scale": _vec(await client.request(f"{_SC}.Screen.getScale", hp)),
    }


# ===================================================================== resources
async def _folder_handle(client: PixeraTCPClient, name_path: str) -> Any:
    """Resolve a resource folder by name path, e.g. ``"Media/Live Inputs"``.

    Pixera returns 0 for a path that does not exist; separators are ``/`` or ``.``,
    and the path starts at a top-level folder (usually ``Media``).
    """
    h = await client.request(f"{_RS}.getResourceFolderWithNamePath", {"namePath": name_path})
    if not h:
        raise PixeraError(f"No resource folder {name_path!r}. Paths start at a top-level folder "
                          "and use '/' (e.g. 'Media/Live Inputs'); see pixera_list_resources.")
    return h


async def _resource_info(client: PixeraTCPClient, h: Any, errors: list[str],
                         detailed: bool) -> dict[str, Any]:
    hp = {"handle": h}
    info: dict[str, Any] = {
        "handle": h,
        "name": await _safe(client, f"{_RS}.Resource.getName", hp, errors),
        "id": await _safe(client, f"{_RS}.Resource.getId", hp, errors),
        "type": await _safe(client, f"{_RS}.Resource.getType", hp, errors),
    }
    if detailed:
        info["file_path"] = await _safe(client, f"{_RS}.Resource.getFilePath", hp, errors)
        info["resolution"] = await _safe(client, f"{_RS}.Resource.getResolution", hp, errors)
    return info


async def _folder_tree(client: PixeraTCPClient, h: Any, depth: int, max_depth: int,
                       errors: list[str], detailed: bool) -> dict[str, Any]:
    hp = {"handle": h}
    node: dict[str, Any] = {
        "handle": h,
        "name": await _safe(client, f"{_RS}.ResourceFolder.getName", hp, errors),
        "resources": [await _resource_info(client, r, errors, detailed)
                      for r in (await _safe(client, f"{_RS}.ResourceFolder.getResources",
                                            hp, errors) or [])],
    }
    subs = await _safe(client, f"{_RS}.ResourceFolder.getResourceFolders", hp, errors) or []
    if depth < max_depth:
        node["folders"] = [await _folder_tree(client, s, depth + 1, max_depth, errors, detailed)
                           for s in subs]
    elif subs:
        node["folders_truncated"] = len(subs)
    return node


async def list_resources(client: PixeraTCPClient, folder_name_path: str | None = None,
                         max_depth: int = 4, detailed: bool = False) -> dict[str, Any]:
    """Resource folder tree with each resource's name, id and type.

    ``folder_name_path`` starts at one folder (e.g. ``"Media/Screens"``); default is
    all top-level folders. ``detailed`` adds file path and resolution.
    """
    errors: list[str] = []
    if folder_name_path:
        h = await _folder_handle(client, folder_name_path)
        roots = [h]
    else:
        roots = await client.request(f"{_RS}.getResourceFolders") or []
    tree = [await _folder_tree(client, r, 0, max_depth, errors, detailed) for r in roots]
    out: dict[str, Any] = {"folders": tree}
    if errors:
        out["errors"] = errors
    return out


async def find_resource(client: PixeraTCPClient, folder_name_path: str,
                        resource_name: str) -> dict[str, Any]:
    folder = await _folder_handle(client, folder_name_path)
    h = await client.request(f"{_RS}.ResourceFolder.getResourceByName",
                             {"handle": folder, "name": resource_name})
    if not h:
        raise PixeraError(f"No resource {resource_name!r} in folder {folder_name_path!r}.")
    return await _resource_info(client, h, [], detailed=True)


async def import_resource(client: PixeraTCPClient, path: str, folder_name_path: str,
                          directory: bool = False) -> dict[str, Any]:
    """Import a file (``Compound.addResourceToFolder``) or every file in a directory.

    Directory import uses ``ResourceFolder.addResourcesFromDirectory`` with
    ``removeOthers=false`` and ``checkRedundancy=true``, so nothing is removed.
    """
    if directory:
        folder = await _folder_handle(client, folder_name_path)
        handles = await client.request(
            f"{_RS}.ResourceFolder.addResourcesFromDirectory",
            {"handle": folder, "path": path, "removeOthers": False, "checkRedundancy": True},
        ) or []
    else:
        h = await client.request("Pixera.Compound.addResourceToFolder",
                                 {"namePath": folder_name_path, "filePath": path})
        handles = [h] if h else []
    errors: list[str] = []
    resources = [await _resource_info(client, h, errors, detailed=True) for h in handles]
    out: dict[str, Any] = {"folder": folder_name_path, "path": path, "imported": resources}
    if not handles:
        out["warning"] = "Pixera returned no resource handle; check the path and file type."
    if errors:
        out["errors"] = errors
    return out


# ===================================================================== timelines
async def _layer_info(client: PixeraTCPClient, h: Any, errors: list[str]) -> dict[str, Any]:
    hp = {"handle": h}
    res = await _safe(client, f"{_TS}.Layer.getAssignedResource", hp, errors)
    model = await _safe(client, f"{_TS}.Layer.getAssignedModelResource", hp, errors)
    info: dict[str, Any] = {
        "handle": h,
        "name": await _safe(client, f"{_TS}.Layer.getName", hp, errors),
        "home_screen": await _safe(client, f"{_TS}.Layer.getHomeScreenName", hp, errors),
        "scale_unit_mode": await _safe(client, f"{_TS}.Layer.getScaleUnitMode", hp, errors),
        "render_only_on_home_screen":
            await _safe(client, f"{_TS}.Layer.getRenderOnlyOnHomeScreen", hp, errors),
        "resource": None,
        "model_resource": None,
    }
    if res:
        info["resource"] = {"handle": res, "name": await _safe(
            client, f"{_RS}.Resource.getName", {"handle": res}, errors)}
    if model:
        info["model_resource"] = {"handle": model, "name": await _safe(
            client, f"{_RS}.Resource.getName", {"handle": model}, errors)}
    return info


async def list_timelines_detailed(client: PixeraTCPClient,
                                  include_layers: bool = True) -> dict[str, Any]:
    """Timelines with name, fps, transport mode and (optionally) each layer's setup."""
    errors: list[str] = []
    timelines = []
    for h in await client.request(f"{_TS}.getTimelines") or []:
        hp = {"handle": h}
        name = await _safe(client, f"{_TS}.Timeline.getName", hp, errors)
        tl: dict[str, Any] = {
            "handle": h,
            "name": name,
            "fps": await _safe(client, f"{_TS}.Timeline.getFps", hp, errors),
            "transport_mode": await _safe(client, f"{_TS}.Timeline.getTransportMode", hp, errors),
            "protected": is_protected_timeline(name),
        }
        if include_layers:
            layers = await _safe(client, f"{_TS}.Timeline.getLayers", hp, errors) or []
            tl["layers"] = [await _layer_info(client, lh, errors) for lh in layers]
        timelines.append(tl)
    out: dict[str, Any] = {"count": len(timelines), "timelines": timelines}
    if errors:
        out["errors"] = errors
    return out


async def _timeline_handle(client: PixeraTCPClient, name: str) -> Any:
    h = await client.request(f"{_TS}.getTimelineFromName", {"name": name})
    if not h:
        raise PixeraError(f"No timeline named {name!r}.")
    return h


async def _layer_handle(client: PixeraTCPClient, timeline: str, layer: str) -> Any:
    tl = await _timeline_handle(client, timeline)
    h = await client.request(f"{_TS}.Timeline.getLayerFromName", {"handle": tl, "name": layer})
    if not h:
        raise PixeraError(f"No layer named {layer!r} in timeline {timeline!r}.")
    return h


async def get_layer_json(client: PixeraTCPClient, timeline: str, layer: str) -> dict[str, Any]:
    """``Layer.getLayerJsonDescrip`` for one layer (raw string as returned by Pixera)."""
    h = await _layer_handle(client, timeline, layer)
    descrip = await client.request(f"{_TS}.Layer.getLayerJsonDescrip", {"handle": h})
    return {"timeline": timeline, "layer": layer, "handle": h, "layer_json": descrip}


async def create_timeline(client: PixeraTCPClient, name: str) -> dict[str, Any]:
    _guard_timeline_name(name)
    existing = await client.request(f"{_TS}.getTimelineNames") or []
    if name in existing:
        raise PixeraError(f"Timeline {name!r} already exists.")
    h = await client.request(f"{_TS}.createTimeline")
    await client.request(f"{_TS}.Timeline.setName", {"handle": h, "name": name})
    return {"timeline": name, "handle": h, "created": True}


async def setup_layer(client: PixeraTCPClient, timeline: str, layer: str, *,
                      create: bool = True, resource_id: float | None = None,
                      model_resource_id: float | None = None, home_screen: str | None = None, scale_mode: str | None = None,
                      render_only_on_home_screen: bool | None = None) -> dict[str, Any]:
    """Find or create a layer, then apply any of: resource, home screen, scale mode.

    ``resource_id`` (media) and ``model_resource_id`` (a ``3DModel`` resource) are ids from
    ``pixera_list_resources`` / ``pixera_find_resource``; both go through
    ``Layer.assignResource``, which routes a model to the layer's model slot.
    ``scale_mode`` is one of :data:`SCALE_MODES`.
    """
    _guard_timeline_name(timeline)
    if scale_mode is not None and scale_mode not in SCALE_MODES:
        raise ValueError(f"scale_mode must be one of {list(SCALE_MODES)}, got {scale_mode!r}")
    tl = await _timeline_handle(client, timeline)
    h = await client.request(f"{_TS}.Timeline.getLayerFromName", {"handle": tl, "name": layer})
    created = False
    if not h:
        if not create:
            raise PixeraError(f"No layer named {layer!r} in timeline {timeline!r}.")
        h = await client.request(f"{_TS}.Timeline.createLayer", {"handle": tl})
        await client.request(f"{_TS}.Layer.setName", {"handle": h, "name": layer})
        created = True
    hp = {"handle": h}
    for rid in (model_resource_id, resource_id):
        if rid is not None:
            await client.request(f"{_TS}.Layer.assignResource", {**hp, "id": float(rid)})
    if home_screen is not None:
        await client.request(f"{_TS}.Layer.setHomeScreenFromScreenName",
                             {**hp, "screenName": home_screen})
    if scale_mode is not None:
        await client.request(f"{_TS}.Layer.setScaleUnitMode", {**hp, "mode": SCALE_MODES[scale_mode]})
    if render_only_on_home_screen is not None:
        await client.request(f"{_TS}.Layer.setRenderOnlyOnHomeScreen",
                             {**hp, "onlyOnHomeScreen": render_only_on_home_screen})
    errors: list[str] = []
    out = {"timeline": timeline, "created": created, "layer": await _layer_info(client, h, errors)}
    if errors:
        out["errors"] = errors
    return out


# ==================================================================== live input
async def set_live_input(client: PixeraTCPClient, folder_name_path: str, resource_name: str,
                         mode_index: int | None = None, activate: bool = True) -> dict[str, Any]:
    """Pick a stream mode on an existing Live Input resource and (de)activate its streams.

    With ``mode_index`` omitted, only lists the available modes.
    """
    res = await find_resource(client, folder_name_path, resource_name)
    hp = {"handle": res["handle"]}
    modes = await client.request(f"{_RS}.Resource.getVideoStreamModes", hp) or []
    out: dict[str, Any] = {"resource": res["name"], "modes": modes}
    if mode_index is None:
        return out
    if not 0 <= mode_index < len(modes):
        raise ValueError(f"mode_index {mode_index} out of range 0..{len(modes) - 1}")
    await client.request(f"{_RS}.Resource.setVideoStreamMode", {**hp, "index": mode_index})
    streams = []
    for s in await client.request(f"{_RS}.Resource.getVideoStreamInputs", hp) or []:
        sp = {"handle": s}
        await client.request("Pixera.LiveSystems.VideoStream.setActive", {**sp, "active": activate})
        streams.append({
            "handle": s,
            "name": await client.request("Pixera.LiveSystems.VideoStream.getName", sp),
            "active": await client.request("Pixera.LiveSystems.VideoStream.getActive", sp),
            "available": await client.request("Pixera.LiveSystems.VideoStream.getAvailable", sp),
        })
    out.update(mode_index=mode_index, mode=modes[mode_index], streams=streams)
    return out


# ====================================================================== mappings
async def _live_system(client: PixeraTCPClient, name: str | None) -> Any:
    systems = await client.request("Pixera.LiveSystems.getLiveSystems") or []
    if not systems:
        raise PixeraError("Pixera reports no live systems.")
    if name is None:
        return systems[0]
    for h in systems:
        if await client.request("Pixera.LiveSystems.LiveSystem.getName", {"handle": h}) == name:
            return h
    raise PixeraError(f"No live system named {name!r}.")


async def list_outputs(client: PixeraTCPClient, live_system: str | None = None) -> dict[str, Any]:
    """Outputs of a live system with idPath, resolution and assigned projectors/screens.

    ``idPath`` (e.g. ``"1/2"`` = graphics card 1, output 2) is what
    :func:`import_mappings` uses to retarget mappings.
    """
    ls = await _live_system(client, live_system)
    structure = await client.request("Pixera.LiveSystems.LiveSystem.getStructureJson",
                                     {"handle": ls})
    info = json.loads(structure) if isinstance(structure, str) and structure else {}
    by_name = {o["name"]: o for gd in info.get("graphicsDevices", []) for o in gd.get("outputs", [])}
    outputs = []
    for h in await client.request("Pixera.LiveSystems.LiveSystem.getAllOutputs", {"handle": ls}) or []:
        hp = {"handle": h}
        name = await client.request("Pixera.LiveSystems.Output.getName", hp)
        projectors = await client.request("Pixera.LiveSystems.Output.getAssignedProjectors", hp)
        meta = by_name.get(name, {})
        outputs.append({
            "name": name,
            "handle": h,
            "id_path": meta.get("idPath"),
            "resolution": meta.get("resolution"),
            "enabled": meta.get("enabled"),
            "projectors": [await client.request("Pixera.Projectors.Projector.getName",
                                                {"handle": p}) for p in projectors or []],
            "screens": await client.request("Pixera.LiveSystems.Output.getAssignedScreens", hp),
        })
    return {"live_system": info.get("name"), "ip": info.get("ip"), "outputs": outputs}


async def export_mappings(client: PixeraTCPClient, path: str,
                          live_system: str | None = None) -> dict[str, Any]:
    """``LiveSystem.exportMappings``: writes ``service_<ip>/mapping_NNN.axp`` (one file per
    projector-to-screen mapping: warp modifiers, soft edge, color correction) plus
    ``original_output_structure.json`` under ``path``."""
    ls = await _live_system(client, live_system)
    await client.request("Pixera.LiveSystems.LiveSystem.exportMappings",
                         {"handle": ls, "path": path})
    root = pathlib.Path(path)
    files = sorted(str(f.relative_to(root)) for f in root.rglob("*") if f.is_file()) \
        if root.exists() else []
    return {"path": path, "files": files,
            "note": None if root.exists() else "Path is not visible from this machine."}


async def import_mappings(client: PixeraTCPClient, path: str,
                          output_map: dict[str, str] | None = None,
                          live_system: str | None = None) -> dict[str, Any]:
    """``LiveSystem.importMappings`` from a folder written by :func:`export_mappings`.

    ``output_map`` retargets mappings by output idPath, e.g. ``{"1/1": "1/2"}`` moves
    what was on output 1/1 onto output 1/2 (sent as ``"1/1:1/2"``; confirmed live).
    Without it, each mapping returns to the output it was exported from. Overwrites
    the current mappings of the affected outputs. Only a single ``src:dst`` pair is
    confirmed live; several pairs are joined with ``,`` (unconfirmed).
    """
    ls = await _live_system(client, live_system)
    map_str = ",".join(f"{src}:{dst}" for src, dst in (output_map or {}).items())
    await client.request("Pixera.LiveSystems.LiveSystem.importMappings",
                         {"handle": ls, "path": path, "outputIdPathMapStr": map_str})
    after = await list_outputs(client, live_system)
    return {"path": path, "output_id_path_map": map_str,
            "outputs": [o for o in after["outputs"] if o["projectors"] or o["screens"]]}

