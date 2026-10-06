"""Tests for 0xPX framing, id-correlation, and the pose/handle helpers.

Written as plain (sync) functions that drive an asyncio body via ``asyncio.run``
so they need no pytest-asyncio plugin. A ``__main__`` block runs them directly.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from pixera_mcp.client import PixeraError, PixeraTCPClient, _parse_vec3  # noqa: E402
from pixera_mcp.config import PIXERA_DELIMITER, Settings  # noqa: E402
from mock_pixera import MockPixeraServer  # noqa: E402


# ----------------------------------------------------------------- pure units
def test_delimiter_is_literal_ascii():
    # The delimiter is the four ASCII chars "0xPX", not a hex byte.
    assert PIXERA_DELIMITER == b"0xPX"
    assert list(PIXERA_DELIMITER) == [0x30, 0x78, 0x50, 0x58]


def test_parse_vec3_object_and_array():
    assert _parse_vec3({"x": 1.0, "y": 2.0, "z": 3.0}) == (1.0, 2.0, 3.0)
    assert _parse_vec3([4, 5, 6]) == (4.0, 5.0, 6.0)


# --------------------------------------------------- read loop framing (no IO)
def test_read_loop_splits_concatenated_frames():
    async def _impl():
        c = PixeraTCPClient(Settings(timeout=2.0))
        reader = asyncio.StreamReader()
        c._reader = reader
        loop = asyncio.get_running_loop()
        f1, f2 = loop.create_future(), loop.create_future()
        c._pending[1], c._pending[2] = f1, f2
        task = asyncio.ensure_future(c._read_loop())

        # Two complete frames delivered in a single chunk.
        reader.feed_data(
            b'{"jsonrpc":"2.0","id":1,"result":204}0xPX'
            b'{"jsonrpc":"2.0","id":2,"result":"ok"}0xPX'
        )
        assert await asyncio.wait_for(f1, 1) == 204
        assert await asyncio.wait_for(f2, 1) == "ok"

        reader.feed_eof()
        await asyncio.wait_for(task, 1)

    asyncio.run(_impl())


def test_read_loop_reassembles_split_frame():
    async def _impl():
        c = PixeraTCPClient(Settings(timeout=2.0))
        reader = asyncio.StreamReader()
        c._reader = reader
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        c._pending[7] = fut
        task = asyncio.ensure_future(c._read_loop())

        # One frame fragmented across two TCP chunks (delimiter arrives later).
        reader.feed_data(b'{"jsonrpc":"2.0","id":7,')
        await asyncio.sleep(0.01)
        assert not fut.done()
        reader.feed_data(b'"result":42}0xPX')
        assert await asyncio.wait_for(fut, 1) == 42

        reader.feed_eof()
        await asyncio.wait_for(task, 1)

    asyncio.run(_impl())


# -------------------------------------------------------- against the mock IO
def _client_for(server: MockPixeraServer, timeout: float = 2.0) -> PixeraTCPClient:
    return PixeraTCPClient(Settings(host="127.0.0.1", port=server.port, timeout=timeout))


def test_request_response_roundtrip():
    async def _impl():
        srv = await MockPixeraServer().start()
        c = _client_for(srv)
        try:
            await c.connect()
            assert await c.request("Pixera.Utility.getApiRevision") == 481
        finally:
            await c.close()
            await srv.stop()

    asyncio.run(_impl())


def test_concurrent_requests_correlate():
    async def _impl():
        srv = await MockPixeraServer().start()
        c = _client_for(srv)
        try:
            await c.connect()
            rev, t, names = await asyncio.gather(
                c.request("Pixera.Utility.getApiRevision"),
                c.request("Pixera.Compound.getCurrentTimeOfTimelineInSeconds", {"name": "T"}),
                c.request("Pixera.Projectors.getProjectorNames"),
            )
            assert rev == 481
            assert t == 12.5
            assert names == ["Projector 1", "Projector 2"]
        finally:
            await c.close()
            await srv.stop()

    asyncio.run(_impl())


def test_error_response_raises():
    async def _impl():
        srv = await MockPixeraServer().start()
        c = _client_for(srv)
        try:
            await c.connect()
            raised = False
            try:
                await c.request("Pixera.Does.Not.Exist")
            except PixeraError:
                raised = True
            assert raised
        finally:
            await c.close()
            await srv.stop()

    asyncio.run(_impl())


def test_projector_pose_and_handle_cache():
    async def _impl():
        srv = await MockPixeraServer().start()
        c = _client_for(srv)
        try:
            await c.connect()
            pose = await c.get_projector_pose("Projector 1")
            assert pose["position"] == (0.0, 2.0, 5.0)
            assert pose["rotation"] == (0.0, 180.0, 0.0)

            # Second pose fetch should reuse the cached handle (one name lookup).
            await c.get_projector_pose("Projector 1")
            lookups = [m for m, _ in srv.received
                       if m == "Pixera.Projectors.getProjectorWithName"]
            assert len(lookups) == 1

            # After invalidation the handle is fetched again.
            c.invalidate_handles()
            await c.get_projector_handle("Projector 1")
            lookups = [m for m, _ in srv.received
                       if m == "Pixera.Projectors.getProjectorWithName"]
            assert len(lookups) == 2
        finally:
            await c.close()
            await srv.stop()

    asyncio.run(_impl())


def test_request_times_out_when_silent():
    async def _impl():
        async def _silent(reader, writer):
            try:
                await reader.read()  # consume; never reply
            except Exception:  # noqa: BLE001
                pass
            finally:
                writer.close()  # else Server.wait_closed() blocks on some Python versions

        server = await asyncio.start_server(_silent, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        c = PixeraTCPClient(Settings(host="127.0.0.1", port=port, timeout=0.3))
        try:
            await c.connect()
            raised = False
            try:
                await c.request("Pixera.Utility.getApiRevision")
            except PixeraError:
                raised = True
            assert raised
        finally:
            await c.close()
            server.close()
            await server.wait_closed()

    asyncio.run(_impl())


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("framing: all passed")


if __name__ == "__main__":
    _run_all()
