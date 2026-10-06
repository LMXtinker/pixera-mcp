"""Tests for the .avp warp-context extractor.

A synthetic fixture exercises the tag decoder deterministically; a guarded check
runs against the real sample project when present.
"""

from __future__ import annotations

import pathlib
import struct
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from pixera_mcp.avp import extract_warp_context  # noqa: E402

_REAL = pathlib.Path(__file__).resolve().parents[2] / "Pixera_Test" / "TestForBerlin.avp"


def _tok(s: str) -> bytes:
    return bytes([len(s)]) + s.encode()


def _i32(v: int) -> bytes:
    return b"\x07" + struct.pack("<i", v)


def _vec3(x: float, y: float, z: float) -> bytes:
    return b"\x0d" + struct.pack("<3d", x, y, z)


def _synthetic_avp() -> bytes:
    buf = b"\x40\x00\x00\x00\x00" + b"build_26-1_R_1/pixera.exe"
    buf += _tok("Projector") + _tok("PT-RQ18K") + _tok("Panasonic")
    buf += _tok("ObjectBaseTransform") + _vec3(1, 2, 3) + _vec3(0, 180, 0) + _vec3(1, 1, 1)
    buf += _tok("FFD Modifier") + _i32(3) + _i32(3) + _i32(3)
    buf += _vec3(-16.0, 0.1, -13.0) + _vec3(13.0, 20.0, 13.0) + _vec3(29.0, 20.0, 26.0)
    buf += _tok("SoftedgeWarp")
    return buf


def test_extract_synthetic():
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "synthetic.avp"
        p.write_bytes(_synthetic_avp())
        ctx = extract_warp_context(p)

    assert ctx["pixera_build"] == "26-1_R_1"
    assert ctx["projectors"], "expected a projector"
    proj = ctx["projectors"][0]
    assert proj["model"] == "PT-RQ18K"
    assert proj["brand"] == "Panasonic"
    assert proj["pose"]["position"] == [1.0, 2.0, 3.0]
    assert proj["pose"]["rotation"] == [0.0, 180.0, 0.0]
    assert proj["pose"]["scale"] == [1.0, 1.0, 1.0]

    assert ctx["ffd_modifiers"], "expected an FFD modifier"
    ffd = ctx["ffd_modifiers"][0]
    assert ffd["grid_dims"] == [3, 3, 3]
    assert ffd["value_count"] == 3
    assert ffd["control_points_sample"][0] == [-16.0, 0.1, -13.0]
    assert ctx["softedge"]["present"] is True


def test_extract_real_project_if_present():
    if not _REAL.exists():
        print(f"  (skip: {_REAL} not present)")
        return
    ctx = extract_warp_context(_REAL)
    assert ctx["pixera_build"] == "26-1_R_1"
    assert any(p["model"] == "PT-RQ18K" for p in ctx["projectors"])
    assert any(f["grid_dims"] == [3, 3, 3] for f in ctx["ffd_modifiers"])


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("avp: all passed")


if __name__ == "__main__":
    _run_all()
