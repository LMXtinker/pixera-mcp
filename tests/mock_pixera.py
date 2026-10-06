"""A mock of Pixera's JSON/TCP(dl) Native API for offline testing.

Speaks the same framing as a real Pixera endpoint (JSON-RPC messages separated
by the literal ``0xPX`` delimiter). Behaviour modelled on Pixera 26.1 (API rev 481):

* Every request is validated against the rev 481 API index (local Pixera install): unknown
  methods, unknown params and missing required params get a JSON-RPC error, as a
  real Pixera would. This makes the mock a check on the method strings the server
  sends, not only on the transport.
* Getters return bare integer handles (``"result": 123456789``), as in the rev 481
  examples.
* A small in-memory project (screens, projectors, resource folders, timelines with
  layers, a live-input resource) supports the show-setup tools.

Two ways to use it:

* **In-process** (unit tests): construct :class:`MockPixeraServer`, ``await
  start()``, point a :class:`~pixera_mcp.client.PixeraTCPClient` at ``.port``,
  and inspect ``.received`` to assert what was sent.
* **Standalone** (manual / MCP Inspector smoke): ``python tests/mock_pixera.py``
  listens on 127.0.0.1:1500 so you can drive the real MCP server with no Pixera
  licence or hardware.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from pixera_mcp.api_index import default_index  # noqa: E402

DELIM = b"0xPX"
API_REVISION = 481

#: Methods that are not in the API JSON but the mock still answers (none for now).
_UNLISTED: set[str] = set()


class _Project:
    """In-memory Pixera project: objects keyed by integer handle."""

    def __init__(self) -> None:
        self._ids = itertools.count(100_001)
        self.objects: dict[int, dict[str, Any]] = {}
        self.projectors = [
            self._new("projector", name="Projector 1", position=[0.0, 2.0, 5.0],
                      rotation=[0.0, 180.0, 0.0]),
            self._new("projector", name="Projector 2", position=[3.0, 2.0, 5.0],
                      rotation=[0.0, 200.0, 0.0]),
        ]
        self.screens = [
            self._new("screen", name="Generic Flat Screen", position=[0.0, 1.0, 0.0],
                      rotation=[0.0, 0.0, 0.0], scale=[1.0, 1.0, 1.0], visible=True,
                      blackout=False),
            self._new("screen", name="Object", position=[2.0, 0.0, -1.0],
                      rotation=[0.0, 90.0, 0.0], scale=[1.0, 1.0, 1.0], visible=True,
                      blackout=False),
        ]
        cam = self._new("videostream", name="Capture 1", active=False, available=True)
        self.root_folders = [
            self._new("folder", name="Media", folders=[], resources=[
                self._new("resource", name="clip.mp4", id=5001.0, type="Video",
                          file_path="C:/media/clip.mp4", resolution=[1920.0, 1080.0]),
            ]),
            self._new("folder", name="Live", folders=[], resources=[
                self._new("resource", name="Live Input 1", id=5002.0, type="LiveInput",
                          file_path="", resolution=[1920.0, 1080.0],
                          modes=["1080p50", "1080p25", "720p50"], mode=0, streams=[cam]),
            ]),
        ]
        self.outputs = [self._new("output", name=f"Output {i}", id_path=f"1/{i}", projectors=[])
                        for i in (1, 2, 3)]
        self.objects[self.outputs[0]]["projectors"].append(self.projectors[0])
        self.live_system = self._new("livesystem", name="Local", ip="10.0.0.10")
        sub = self._new("folder", name="Screens", folders=[], resources=[])
        self.objects[self.root_folders[0]]["folders"].append(sub)
        self.timelines: list[int] = []
        le = self.add_timeline("LE_CUES")
        self.add_layer(le, "LE Layer")
        show = self.add_timeline("Timeline 1")
        self.add_layer(show, "Layer 1")

    def _new(self, kind: str, **fields: Any) -> int:
        h = next(self._ids)
        self.objects[h] = {"kind": kind, **fields}
        return h

    def add_timeline(self, name: str) -> int:
        h = self._new("timeline", name=name, fps=60.0, mode=3, layers=[])
        self.timelines.append(h)
        return h

    def add_layer(self, tl: int, name: str) -> int:
        h = self._new("layer", name=name, timeline=tl, resource=None, model=None,
                      home_screen="", scale_mode=1, only_home=False,
                      json='{"name":"%s"}' % name)
        self.objects[tl]["layers"].append(h)
        return h

    def get(self, h: Any, kind: str) -> dict[str, Any]:
        obj = self.objects.get(h)
        if obj is None or obj["kind"] != kind:
            raise ValueError(f"invalid {kind} handle {h!r}")
        return obj

    def by_name(self, handles: list[int], name: str) -> int:
        for h in handles:
            if self.objects[h]["name"] == name:
                return h
        return 0

    def all_folders(self) -> list[int]:
        out, stack = [], list(self.root_folders)
        while stack:
            h = stack.pop()
            out.append(h)
            stack.extend(self.objects[h]["folders"])
        return out

    def folder_by_path(self, name_path: str) -> int:
        parts = [p for p in name_path.replace(".", "/").split("/") if p]
        level, h = self.root_folders, 0
        for part in parts:
            h = self.by_name(level, part)
            if not h:
                return 0  # live Pixera returns 0 for an unknown folder path
            level = self.objects[h]["folders"]
        return h

    def resource_by_id(self, rid: float) -> int:
        for h, o in self.objects.items():
            if o["kind"] == "resource" and o["id"] == rid:
                return h
        raise ValueError(f"no resource with id {rid}")


class MockPixeraServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self._host = host
        self._req_port = port
        self._server: asyncio.AbstractServer | None = None
        self._index = default_index()
        self.project = _Project()
        #: list of (method, params) tuples received, for test assertions
        self.received: list[tuple[str, dict[str, Any]]] = []
        #: method names getHasFunction reports as missing
        self.missing_functions: set[str] = set()

    @property
    def port(self) -> int:
        assert self._server is not None, "server not started"
        return self._server.sockets[0].getsockname()[1]

    async def start(self) -> "MockPixeraServer":
        self._server = await asyncio.start_server(self._handle, self._host, self._req_port)
        return self

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                raw = await reader.readuntil(DELIM)
                payload = raw[: -len(DELIM)]
                if not payload.strip():
                    continue
                msg = json.loads(payload)
                response = self._respond(msg)
                if response is not None:
                    writer.write(json.dumps(response).encode("utf-8") + DELIM)
                    await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            try:
                writer.close()
            except Exception:  # noqa: BLE001
                pass

    def _respond(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = msg.get("method", "")
        params = msg.get("params", {}) or {}
        req_id = msg.get("id")
        self.received.append((method, params))

        def error(code: int, message: str) -> dict[str, Any]:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}

        if method not in _UNLISTED:
            check = self._index.check_call(method, params)
            if not check["ok"]:
                return error(-32601 if check["entry"] is None else -32602,
                             "; ".join(check["errors"]))
        try:
            result = self._dispatch(method, params)
        except KeyError as exc:
            return error(-32602, f"unknown name {exc}")
        except ValueError as exc:
            return error(-5, str(exc))
        if req_id is None:
            return None
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    # ------------------------------------------------------------------ dispatch
    def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        p = self.project
        h = params.get("handle")
        ns, _, short = method.rpartition(".")

        # --- Utility ---
        if method == "Pixera.Utility.getApiRevision":
            return API_REVISION
        if method == "Pixera.Utility.getCurrentTime":
            return 1_700_000_000_000.0
        if method == "Pixera.Utility.noop":
            return None
        if method == "Pixera.Utility.getHasFunction":
            name = params["functionName"]
            return name in self._index.entries and name not in self.missing_functions
        if method == "Pixera.Utility.pollMonitoring":
            return "{\"alerts\":[]}"
        # --- Compound ---
        if method in ("Pixera.Compound.setTransportModeOnTimelineAtIndex",):
            return True
        if method in ("Pixera.Compound.setTransportModeOnTimeline",
                      "Pixera.Compound.applyCueAtIndexOnTimelineAtIndex",
                      "Pixera.Compound.applyCueNumberOnTimelineAtIndex"):
            return None
        if method == "Pixera.Compound.getCurrentTimeOfTimelineInSeconds":
            return 12.5
        if method == "Pixera.Compound.addResourceToFolder":
            folder = p.folder_by_path(params["namePath"])
            return self._import_file(folder, params["filePath"])
        # --- Session ---
        if method in ("Pixera.Session.loadProject", "Pixera.Session.saveProject"):
            return None
        if method == "Pixera.Session.getProjectName":
            return "mock"
        # --- Calibration ---
        if method == "Pixera.Calibration.setMarkerPositions":
            if len(params["positions"]) != 3 * len(params["markerIds"]):
                raise ValueError("positions length must be 3 x markerIds length")
            return None
        # --- Projectors ---
        if method == "Pixera.Projectors.getProjectorNames":
            return [p.objects[x]["name"] for x in p.projectors]
        if method == "Pixera.Projectors.getProjectorWithName":
            return p.by_name(p.projectors, params["name"]) or self._missing(params["name"])
        if ns == "Pixera.Projectors.Projector":
            obj = p.get(h, "projector")
            if short == "getPosition":
                return dict(zip("xyz", obj["position"]))
            if short == "getRotation":
                return dict(zip("xyz", obj["rotation"]))
            if short == "setBlackout":
                return None
            if short == "getName":
                return obj["name"]
        # --- Screens ---
        if method == "Pixera.Screens.getScreens":
            return list(p.screens)
        if method == "Pixera.Screens.getScreenNames":
            return [p.objects[x]["name"] for x in p.screens]
        if method == "Pixera.Screens.getScreenWithName":
            return p.by_name(p.screens, params["name"]) or self._missing(params["name"])
        if ns == "Pixera.Screens.Screen":
            obj = p.get(h, "screen")
            if short == "getName":
                return obj["name"]
            if short in ("getPosition", "getRotation", "getScale"):
                return dict(zip("xyz", obj[short[3:].lower()]))
            if short == "getIsVisible":
                return obj["visible"]
            if short == "getBlackout":
                return obj["blackout"]
            if short == "setPosRotScale":
                for key, field in (("Pos", "position"), ("Rot", "rotation"), ("Scale", "scale")):
                    for i, axis in enumerate("xyz"):
                        if f"{axis}{key}" in params:
                            obj[field][i] = float(params[f"{axis}{key}"])
                return True
            if short == "triggerRefreshMapping":
                return None
        # --- Resources ---
        if method == "Pixera.Resources.getResourceFolders":
            return list(p.root_folders)
        if method == "Pixera.Resources.getResourceFolderWithNamePath":
            return p.folder_by_path(params["namePath"])
        if ns == "Pixera.Resources.ResourceFolder":
            obj = p.get(h, "folder")
            if short == "getName":
                return obj["name"]
            if short == "getResources":
                return list(obj["resources"])
            if short == "getResourceFolders":
                return list(obj["folders"])
            if short == "getResourceByName":
                return p.by_name(obj["resources"], params["name"])
            if short == "addResource":
                return self._import_file(h, params["path"])
            if short == "addResourcesFromDirectory":
                d = pathlib.Path(params["path"])
                return [self._import_file(h, str(f)) for f in sorted(d.iterdir()) if f.is_file()]
        if ns == "Pixera.Resources.Resource":
            obj = p.get(h, "resource")
            simple = {"getName": "name", "getId": "id", "getType": "type",
                      "getFilePath": "file_path", "getResolution": "resolution"}
            if short in simple:
                return obj[simple[short]]
            if short == "getVideoStreamModes":
                return obj.get("modes", [])
            if short == "setVideoStreamMode":
                if not 0 <= params["index"] < len(obj.get("modes", [])):
                    raise ValueError("mode index out of range")
                obj["mode"] = params["index"]
                return None
            if short == "getVideoStreamInputs":
                return list(obj.get("streams", []))
        if method == "Pixera.LiveSystems.getLiveSystems":
            return [p.live_system]
        if ns == "Pixera.LiveSystems.LiveSystem":
            obj = p.get(h, "livesystem")
            if short == "getName":
                return obj["name"]
            if short == "getAllOutputs":
                return list(p.outputs)
            if short == "getStructureJson":
                outs = [{"name": p.objects[o]["name"], "idPath": p.objects[o]["id_path"],
                         "resolution": [1920, 1080], "enabled": True} for o in p.outputs]
                return json.dumps({"name": obj["name"], "ip": obj["ip"],
                                   "graphicsDevices": [{"idPath": "1", "outputs": outs}]})
            if short == "exportMappings":
                d = pathlib.Path(params["path"]) / f"service_{obj['ip']}"
                d.mkdir(parents=True, exist_ok=True)
                (d / "original_output_structure.json").write_text("{}", encoding="utf-8")
                (d / "mapping_001.axp").write_bytes(b"@MuExport")
                return None
            if short == "importMappings":
                # Live 26.1: "src:dst" moves the mappings of output src to output dst.
                for pair in filter(None, params["outputIdPathMapStr"].split(",")):
                    src, dst = pair.split(":")
                    so = next(o for o in p.outputs if p.objects[o]["id_path"] == src)
                    do = next(o for o in p.outputs if p.objects[o]["id_path"] == dst)
                    p.objects[do]["projectors"] += p.objects[so]["projectors"]
                    p.objects[so]["projectors"] = []
                return None
        if ns == "Pixera.LiveSystems.Output":
            obj = p.get(h, "output")
            if short == "getName":
                return obj["name"]
            if short == "getAssignedProjectors":
                return list(obj["projectors"])
            if short == "getAssignedScreens":
                return []
        if ns == "Pixera.LiveSystems.VideoStream":
            obj = p.get(h, "videostream")
            if short == "setActive":
                obj["active"] = params["active"]
                return None
            if short == "getActive":
                return obj["active"]
            if short == "getAvailable":
                return obj["available"]
            if short == "getName":
                return obj["name"]
        # --- Timelines ---
        if method == "Pixera.Timelines.getTimelines":
            return list(p.timelines)
        if method == "Pixera.Timelines.getTimelineNames":
            return [p.objects[t]["name"] for t in p.timelines]
        if method == "Pixera.Timelines.getTimelineFromName":
            return p.by_name(p.timelines, params["name"])
        if method == "Pixera.Timelines.createTimeline":
            return p.add_timeline(f"Timeline {len(p.timelines) + 1}")
        if ns == "Pixera.Timelines.Timeline":
            obj = p.get(h, "timeline")
            if short == "getName":
                return obj["name"]
            if short == "setName":
                obj["name"] = params["name"]
                return None
            if short == "getFps":
                return obj["fps"]
            if short == "getTransportMode":
                return obj["mode"]
            if short == "getLayers":
                return list(obj["layers"])
            if short == "getLayerFromName":
                return p.by_name(obj["layers"], params["name"])
            if short == "createLayer":
                return p.add_layer(h, f"Layer {len(obj['layers']) + 1}")
            if short == "removeThis":
                p.timelines.remove(h)
                return None
        if ns == "Pixera.Timelines.Layer":
            obj = p.get(h, "layer")
            if short == "getName":
                return obj["name"]
            if short == "setName":
                obj["name"] = params["name"]
                return None
            if short == "getTimeline":
                return obj["timeline"]
            if short == "getAssignedResource":
                return obj["resource"] or 0
            if short == "getAssignedModelResource":
                return obj["model"] or 0
            if short == "assignResource":
                # Live 26.1: a 3DModel id fills the model slot, anything else the media slot.
                res = p.resource_by_id(params["id"])
                obj["model" if p.objects[res]["type"] == "3DModel" else "resource"] = res
                return None
            if short == "getHomeScreenName":
                return obj["home_screen"]
            if short == "setHomeScreenFromScreenName":
                if not p.by_name(p.screens, params["screenName"]):
                    raise ValueError(f"no screen {params['screenName']!r}")
                obj["home_screen"] = params["screenName"]
                return None
            if short == "getScaleUnitMode":
                return obj["scale_mode"]
            if short == "setScaleUnitMode":
                obj["scale_mode"] = params["mode"]
                return None
            if short == "getRenderOnlyOnHomeScreen":
                return obj["only_home"]
            if short == "setRenderOnlyOnHomeScreen":
                obj["only_home"] = params["onlyOnHomeScreen"]
                return None
            if short == "getLayerJsonDescrip":
                return obj["json"]
            if short == "removeThis":
                p.objects[obj["timeline"]]["layers"].remove(h)
                return None
        raise ValueError(f"mock has no canned response for method {method!r}")

    def _import_file(self, folder: int, path: str) -> int:
        name = pathlib.PurePath(path).name
        ext = pathlib.PurePath(path).suffix.lower()
        kind = {".obj": "3DModel", ".fbx": "3DModel", ".mp4": "Video", ".png": "Image"}.get(ext, "File")
        rid = float(9000 + len(self.project.objects))
        h = self.project._new("resource", name=name, id=rid, type=kind, file_path=path,
                              resolution=[0.0, 0.0])
        self.project.objects[folder]["resources"].append(h)
        return h

    @staticmethod
    def _missing(name: str) -> Any:
        raise ValueError(f"no object named {name!r}")


async def _main() -> None:
    server = await MockPixeraServer("127.0.0.1", 1500).start()
    print(f"Mock Pixera listening on 127.0.0.1:{server.port} (JSON/TCP(dl), 0xPX). Ctrl+C to stop.")
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await server.stop()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
