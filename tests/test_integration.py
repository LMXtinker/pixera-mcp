"""End-to-end: live control/inspect/geometry tools driven against the mock Pixera.

This is the offline equivalent of the MCP Inspector smoke test - it exercises the
full path (tool -> client -> 0xPX framing -> mock -> response) without a Pixera licence.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from pixera_mcp import tools_control as tc  # noqa: E402
from pixera_mcp import tools_geometry as tg  # noqa: E402
from pixera_mcp import tools_inspect as ti  # noqa: E402
from pixera_mcp.client import PixeraTCPClient  # noqa: E402
from pixera_mcp.config import Settings  # noqa: E402
from pixera_mcp.meshio import box_mesh  # noqa: E402
from mock_pixera import MockPixeraServer  # noqa: E402


def _write_cube_obj(path: pathlib.Path, size: float = 2.0) -> None:
    mesh = box_mesh(size=(size, size, size))
    lines = [f"v {v[0]} {v[1]} {v[2]}" for v in mesh.vertices]
    lines += [f"f {f[0] + 1} {f[1] + 1} {f[2] + 1}" for f in mesh.faces]
    path.write_text("\n".join(lines), encoding="utf-8")


def test_control_and_inspect_via_mock():
    async def _impl():
        srv = await MockPixeraServer().start()
        c = PixeraTCPClient(Settings(host="127.0.0.1", port=srv.port, timeout=2.0))
        try:
            await c.connect()
            assert (await tc.get_api_revision(c))["api_revision"] == 481
            assert (await tc.ping(c))["alive"] is True
            tr = await tc.set_timeline_transport(c, 0, "play")
            assert tr["mode"] == 1 and tr["ok"]
            assert (await tc.apply_cue(c, 0, 0))["ok"]
            assert "Projector 1" in (await ti.list_projectors(c))["projectors"]
            pose = await ti.get_projector_pose(c, "Projector 1")
            assert pose["position"] == [0.0, 2.0, 5.0]
            assert (await tc.load_project(c, "demo.pxr"))["ok"]
        finally:
            await c.close()
            await srv.stop()

    asyncio.run(_impl())


def test_recommend_and_apply_markers_via_mock():
    async def _impl():
        srv = await MockPixeraServer().start()
        c = PixeraTCPClient(Settings(host="127.0.0.1", port=srv.port, timeout=2.0))
        with tempfile.TemporaryDirectory() as d:
            cube = pathlib.Path(d) / "cube.obj"
            _write_cube_obj(cube)
            try:
                await c.connect()
                lens = {"fov_h_deg": 90.0, "aspect": 1.0}
                rec = await tg.recommend_markers_for_projector(
                    c, "Projector 1", lens, str(cube), num_markers=6)
                assert rec["pose"]["position"] == [0.0, 2.0, 5.0]
                assert rec["marker_count"] >= 1
                assert len(rec["positions_flat"]) == 3 * rec["marker_count"]
                assert rec["vqi"] >= 0.0

                applied = await tg.apply_markers(
                    c, "Generic Flat Screen", rec["positions_flat"], rec["marker_ids"])
                assert applied["applied"] is True
                # The mock recorded the setMarkerPositions write with the right payload size.
                writes = [p for m, p in srv.received if m.endswith("setMarkerPositions")]
                assert writes and len(writes[0]["positions"]) == len(rec["positions_flat"])
            finally:
                await c.close()
                await srv.stop()

    asyncio.run(_impl())


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("integration: all passed")


if __name__ == "__main__":
    _run_all()
