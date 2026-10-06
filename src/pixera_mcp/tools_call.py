"""Raw API access: ``pixera_call`` (validated escape hatch) and ``pixera_describe`` (offline docs).

``pixera_call`` checks every call against the API index before sending it:

1. The method must exist in the index, with all required params and no unknown ones.
2. Destructive calls (remove/delete, load/save project, import mappings, engine
   shutdown, ...) are refused unless ``allow_destructive`` is true.
3. Protected timelines (name starts with a prefix from ``PIXERA_PROTECTED_PREFIXES``,
   default ``LE_``) belong to another tool, e.g. an external cue sync. Removing or
   renaming them (or removing their layers) is always refused.
4. ``Pixera.Utility.getHasFunction`` must confirm the connected build has the method.
"""

from __future__ import annotations

import os
from typing import Any

from .api_index import ApiIndex, ApiIndexUnavailable, default_index
from .client import PixeraError, PixeraTCPClient

#: Default prefixes of protected timelines; override with PIXERA_PROTECTED_PREFIXES="A_,B_"
#: (an empty value protects nothing).
DEFAULT_PROTECTED_PREFIXES = "LE_"


def protected_prefixes() -> tuple[str, ...]:
    raw = os.environ.get("PIXERA_PROTECTED_PREFIXES", DEFAULT_PROTECTED_PREFIXES)
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def is_protected_timeline(name: Any) -> bool:
    return isinstance(name, str) and name.startswith(protected_prefixes())

#: Method short names that lose data, change the project file, or stop systems.
DESTRUCTIVE = frozenset({
    # remove / delete
    "removeThis", "removeThisIncludingAssets", "removeAllContents",
    "removeAllContentsIncludingAssets", "deleteAllContentsAssetsFromLiveSystem",
    "deleteFilesOnSystems", "deleteAssetFromLiveSystem", "deleteUnusedFilesFromCache",
    "removeCues", "removeClips", "removeClipsFromJsonString", "removeClipOnLayerWithIndex",
    "removeAllClipsOnLayer", "removeMultiresourceIndex",
    # overwrite / reset
    "replace", "replaceResourcesByString", "resetLayer", "reset", "resetWarpFile",
    "resetAllColorCorrections", "clearExportedMappings", "clearExportedMappingsAtLiveSystemPath",
    "importMappings", "importMappingsDirectly", "importMappingsFromLiveSystemPath",
    "moveMappingsToOutputs", "importUsagePreset", "applyUsagePreset", "applyUsagePresetWithName",
    "addResourcesFromDirectoryRemoveAssets",
    # project file
    "loadProject", "saveProject", "saveProjectAs", "setProjectName", "closeApp",
    # systems
    "shutdownSystem", "shutdownLiveSystem", "shutDown", "restartLiveSystem",
    "restartLiveSystems", "stopLiveSystem", "stopLiveSystems", "resetEngine",
    "restartEngine", "closeEngine",
})

_PROTECTED_TIMELINE_METHODS = frozenset({
    "Pixera.Timelines.Timeline.removeThis",
    "Pixera.Timelines.Timeline.setName",
})
_PROTECTED_LAYER_METHODS = frozenset({
    "Pixera.Timelines.Layer.removeThis",
})


def is_destructive(method: str, params: dict[str, Any] | None = None) -> bool:
    short = method.rsplit(".", 1)[-1]
    if short in DESTRUCTIVE:
        return True
    if short == "addResourcesFromDirectory" and (params or {}).get("removeOthers"):
        return True
    return False


async def protected_timeline_name(client: PixeraTCPClient, method: str,
                                  params: dict[str, Any]) -> str | None:
    """Return the protected timeline name a call would remove or rename, else None."""
    handle = params.get("handle")
    if handle is None:
        return None
    if method in _PROTECTED_TIMELINE_METHODS:
        tl_handle = handle
    elif method in _PROTECTED_LAYER_METHODS:
        tl_handle = await client.request("Pixera.Timelines.Layer.getTimeline", {"handle": handle})
    else:
        return None
    name = await client.request("Pixera.Timelines.Timeline.getName", {"handle": tl_handle})
    if is_protected_timeline(name):
        return name
    return None


def describe(query: str, limit: int = 40, index: ApiIndex | None = None) -> dict[str, Any]:
    try:
        idx = index or default_index()
    except ApiIndexUnavailable as exc:
        return {"match": "unavailable", "query": query, "error": str(exc)}
    out = idx.describe(query, limit=limit)
    out["api_source"] = idx.source.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    return out


async def call(client: PixeraTCPClient, method: str, params: dict[str, Any] | None = None, *,
               allow_destructive: bool = False, validate: bool = True,
               check_has_function: bool = True, index: ApiIndex | None = None) -> dict[str, Any]:
    params = dict(params or {})
    out: dict[str, Any] = {"method": method}
    try:
        idx = index or default_index()
        check = idx.check_call(method, params)
    except ApiIndexUnavailable as exc:
        check = {"ok": True, "errors": [], "entry": None,
                 "warnings": [f"Offline validation skipped: {exc}"]}

    if check["warnings"]:
        out["warnings"] = check["warnings"]
    if not check["ok"]:
        if validate:
            return {**out, "ok": False, "stage": "validate", "errors": check["errors"],
                    "hint": "Use pixera_describe to look up the signature, or pass "
                            "validate=false to send anyway."}
        out.setdefault("warnings", []).extend(check["errors"])

    if is_destructive(method, params) and not allow_destructive:
        return {**out, "ok": False, "stage": "guard",
                "errors": [f"{method} is destructive (removes data, overwrites, touches the "
                           "project file or stops a system). Pass allow_destructive=true only "
                           "on a scratch project or when the user asked for it."]}

    try:
        protected = await protected_timeline_name(client, method, params)
        if protected is not None:
            return {**out, "ok": False, "stage": "guard",
                    "errors": [f"Timeline {protected!r} is protected (prefix in "
                               f"{list(protected_prefixes())}, set by PIXERA_PROTECTED_PREFIXES). "
                               "Removing or renaming it, or removing its layers, is not allowed."]}

        if check_has_function and not await client.has_function(method):
            return {**out, "ok": False, "stage": "has_function",
                    "errors": [f"Connected Pixera reports getHasFunction({method!r}) = false."]}

        result = await client.request(method, params or None)
    except PixeraError as exc:
        err: dict[str, Any] = {**out, "ok": False, "stage": "pixera", "errors": [str(exc)]}
        if exc.code is not None:
            err["code"] = exc.code
        return err

    out.update(ok=True, result=result)
    entry = check["entry"]
    if entry is not None and entry.deliver:
        out["result_handle_class"] = entry.deliver
    return out
