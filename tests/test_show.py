"""pixera_call / pixera_describe and the show-setup tools, driven against the mock Pixera.

The mock validates every request against the rev 481 API index, so these tests
also prove that each tool sends method names and params that exist in rev 481.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import pytest  # noqa: E402

from pixera_mcp import tools_call as tcall  # noqa: E402
from pixera_mcp import tools_show as ts  # noqa: E402
from pixera_mcp.client import PixeraError, PixeraTCPClient  # noqa: E402
from pixera_mcp.config import Settings  # noqa: E402
from mock_pixera import MockPixeraServer  # noqa: E402


def _run(body):
    async def _impl():
        srv = await MockPixeraServer().start()
        c = PixeraTCPClient(Settings(host="127.0.0.1", port=srv.port, timeout=2.0))
        try:
            await c.connect()
            await body(srv, c)
        finally:
            await c.close()
            await srv.stop()

    asyncio.run(_impl())


# ------------------------------------------------------------------ pixera_call
def test_call_success_and_handle_class():
    async def body(srv, c):
        r = await tcall.call(c, "Pixera.Screens.getScreenWithName", {"name": "Object"})
        assert r["ok"] and isinstance(r["result"], int)
        assert r["result_handle_class"] == "Pixera.Screens.Screen"
        pos = await tcall.call(c, "Pixera.Screens.Screen.getPosition", {"handle": r["result"]})
        assert pos["result"] == {"x": 2.0, "y": 0.0, "z": -1.0}
    _run(body)


def test_call_validation_blocks_before_sending():
    async def body(srv, c):
        r = await tcall.call(c, "Pixera.Screens.setPosition", {"x": 1})
        assert not r["ok"] and r["stage"] == "validate"
        assert any("Pixera.Screens.Screen.setPosition" in e for e in r["errors"])
        assert not any(m == "Pixera.Screens.setPosition" for m, _ in srv.received)
        # validate=False sends anyway and reports Pixera's own error
        r2 = await tcall.call(c, "Pixera.Screens.setPosition", {"x": 1}, validate=False,
                              check_has_function=False)
        assert not r2["ok"] and r2["stage"] == "pixera"
    _run(body)


def test_call_has_function_gate():
    async def body(srv, c):
        srv.missing_functions.add("Pixera.Session.getProjectName")
        r = await tcall.call(c, "Pixera.Session.getProjectName")
        assert not r["ok"] and r["stage"] == "has_function"
        r2 = await tcall.call(c, "Pixera.Utility.noop")
        assert r2["ok"]
    _run(body)


def test_call_destructive_guard():
    async def body(srv, c):
        r = await tcall.call(c, "Pixera.Session.saveProject")
        assert not r["ok"] and r["stage"] == "guard"
        assert not any(m == "Pixera.Session.saveProject" for m, _ in srv.received)
        r2 = await tcall.call(c, "Pixera.Session.saveProject", allow_destructive=True)
        assert r2["ok"]
        assert tcall.is_destructive("Pixera.Resources.ResourceFolder.addResourcesFromDirectory",
                                    {"removeOthers": True})
        assert not tcall.is_destructive("Pixera.Resources.ResourceFolder.addResourcesFromDirectory",
                                        {"removeOthers": False})
    _run(body)


def test_call_protects_le_timelines_even_with_override():
    async def body(srv, c):
        le = srv.project.by_name(srv.project.timelines, "LE_CUES")
        for method, params in (("Pixera.Timelines.Timeline.setName", {"handle": le, "name": "x"}),
                               ("Pixera.Timelines.Timeline.removeThis", {"handle": le})):
            r = await tcall.call(c, method, params, allow_destructive=True)
            assert not r["ok"] and r["stage"] == "guard" and "LE_CUES" in r["errors"][0]
        layer = srv.project.objects[le]["layers"][0]
        r = await tcall.call(c, "Pixera.Timelines.Layer.removeThis", {"handle": layer},
                             allow_destructive=True)
        assert not r["ok"] and r["stage"] == "guard"
        assert srv.project.objects[le]["name"] == "LE_CUES"
        # other timelines can be renamed
        other = srv.project.by_name(srv.project.timelines, "Timeline 1")
        r = await tcall.call(c, "Pixera.Timelines.Timeline.setName", {"handle": other, "name": "T"})
        assert r["ok"]
    _run(body)


def test_describe_tool():
    d = tcall.describe("Pixera.Timelines.Layer.setScaleUnitMode")
    assert d["match"] == "exact" and d["api_source"].endswith(".json")


# ------------------------------------------------------------------ inspect
def test_list_screens_detailed():
    async def body(srv, c):
        r = await ts.list_screens_detailed(c)
        assert r["count"] == 2 and "errors" not in r
        obj = next(s for s in r["screens"] if s["name"] == "Object")
        assert obj["position_m"] == [2.0, 0.0, -1.0] and obj["rotation_deg"] == [0.0, 90.0, 0.0]
    _run(body)


def test_list_resources_tree():
    async def body(srv, c):
        r = await ts.list_resources(c)
        names = [f["name"] for f in r["folders"]]
        assert names == ["Media", "Live"] and "errors" not in r
        media = r["folders"][0]
        assert media["resources"][0]["id"] == 5001.0
        assert media["folders"][0]["name"] == "Screens"
        shallow = await ts.list_resources(c, max_depth=0)
        assert shallow["folders"][0]["folders_truncated"] == 1
        one = await ts.list_resources(c, folder_name_path="Media/Screens", detailed=True)
        assert one["folders"][0]["name"] == "Screens"
        with pytest.raises(PixeraError):
            await ts.list_resources(c, folder_name_path="Screens")
    _run(body)


def test_list_timelines_detailed_marks_protected():
    async def body(srv, c):
        r = await ts.list_timelines_detailed(c)
        by = {t["name"]: t for t in r["timelines"]}
        assert by["LE_CUES"]["protected"] and not by["Timeline 1"]["protected"]
        assert by["Timeline 1"]["layers"][0]["name"] == "Layer 1"
        assert by["Timeline 1"]["layers"][0]["resource"] is None
        lj = await ts.get_layer_json(c, "Timeline 1", "Layer 1")
        assert lj["layer_json"] == '{"name":"Layer 1"}'
    _run(body)


# ------------------------------------------------------------------ setup
def test_set_screen_pose_partial_and_readback():
    async def body(srv, c):
        r = await ts.set_screen_pose(c, "Object", rotation=[0.0, 45.0, 0.0])
        assert r["accepted"] is True
        assert r["rotation_deg"] == [0.0, 45.0, 0.0] and r["position_m"] == [2.0, 0.0, -1.0]
        sent = [p for m, p in srv.received if m.endswith("setPosRotScale")][0]
        assert set(sent) == {"handle", "xRot", "yRot", "zRot"}
        with pytest.raises(ValueError):
            await ts.set_screen_pose(c, "Object")
    _run(body)


def test_import_resource_file_and_directory():
    async def body(srv, c):
        r = await ts.import_resource(c, "C:/show/screen_a.obj", "Media/Screens")
        assert r["imported"][0]["type"] == "3DModel" and r["imported"][0]["name"] == "screen_a.obj"
        with tempfile.TemporaryDirectory() as d:
            for n in ("a.png", "b.png"):
                (pathlib.Path(d) / n).write_bytes(b"x")
            r2 = await ts.import_resource(c, d, "Media", directory=True)
            assert [x["name"] for x in r2["imported"]] == ["a.png", "b.png"]
        sent = [p for m, p in srv.received if m.endswith("addResourcesFromDirectory")][0]
        assert sent["removeOthers"] is False
    _run(body)


def test_create_timeline_and_setup_layer():
    async def body(srv, c):
        r = await ts.create_timeline(c, "PREVIEW")
        assert r["created"]
        with pytest.raises(PixeraError):
            await ts.create_timeline(c, "PREVIEW")
        with pytest.raises(PixeraError):
            await ts.create_timeline(c, "LE_NEW")
        lay = await ts.setup_layer(c, "PREVIEW", "Wall", resource_id=5001.0,
                                   home_screen="Object", scale_mode="fit",
                                   render_only_on_home_screen=True)
        assert lay["created"]
        info = lay["layer"]
        assert info["name"] == "Wall" and info["home_screen"] == "Object"
        assert info["scale_unit_mode"] == 2 and info["render_only_on_home_screen"] is True
        assert info["resource"]["name"] == "clip.mp4"
        model = await ts.import_resource(c, "C:/show/wall.obj", "Media/Screens")
        both = await ts.setup_layer(c, "PREVIEW", "Wall",
                                    model_resource_id=model["imported"][0]["id"])
        assert both["layer"]["model_resource"]["name"] == "wall.obj"
        assert both["layer"]["resource"]["name"] == "clip.mp4"
        again = await ts.setup_layer(c, "PREVIEW", "Wall", scale_mode="fill")
        assert not again["created"] and again["layer"]["scale_unit_mode"] == 1
        with pytest.raises(PixeraError):
            await ts.setup_layer(c, "LE_CUES", "LE Layer", scale_mode="fit")
        with pytest.raises(ValueError):
            await ts.setup_layer(c, "PREVIEW", "Wall", scale_mode="zoom")
    _run(body)


def test_set_live_input():
    async def body(srv, c):
        listing = await ts.set_live_input(c, "Live", "Live Input 1")
        assert listing["modes"] == ["1080p50", "1080p25", "720p50"] and "streams" not in listing
        r = await ts.set_live_input(c, "Live", "Live Input 1", mode_index=1)
        assert r["mode"] == "1080p25" and r["streams"][0]["active"] is True
        with pytest.raises(ValueError):
            await ts.set_live_input(c, "Live", "Live Input 1", mode_index=7)
    _run(body)


def test_set_screen_pose_blender_convention():
    async def body(srv, c):
        r = await ts.set_screen_pose(c, "Object", position=[1.0, 2.0, 3.0], convention="blender")
        assert r["position_m"] == [1.0, 3.0, -2.0]
        with pytest.raises(ValueError):
            await ts.set_screen_pose(c, "Object", rotation=[0, 0, 90], convention="blender")
        with pytest.raises(ValueError):
            await ts.set_screen_pose(c, "Object", position=[0, 0, 0], convention="maya")
    _run(body)


def test_outputs_and_mapping_round_trip():
    async def body(srv, c):
        outs = await ts.list_outputs(c)
        assert outs["live_system"] == "Local"
        assert [o["id_path"] for o in outs["outputs"]] == ["1/1", "1/2", "1/3"]
        assert outs["outputs"][0]["projectors"] == ["Projector 1"]
        with tempfile.TemporaryDirectory() as d:
            ex = await ts.export_mappings(c, d)
            assert any(f.endswith("mapping_001.axp") for f in ex["files"])
            moved = await ts.import_mappings(c, d, {"1/1": "1/2"})
            assert moved["output_id_path_map"] == "1/1:1/2"
            assert [o["id_path"] for o in moved["outputs"]] == ["1/2"]
    _run(body)

