"""Blender <-> Pixera axis conversion (Pixera: right-handed, Y-up; confirmed live)."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from pixera_mcp.axes import blender_to_pixera_position, pixera_to_blender_position  # noqa: E402


def test_blender_up_becomes_pixera_y():
    assert blender_to_pixera_position([0, 0, 13]) == [0.0, 13.0, 0.0]


def test_basis_change_keeps_handedness():
    import numpy as np
    m = np.array([blender_to_pixera_position(v) for v in np.eye(3)]).T
    assert round(float(np.linalg.det(m)), 6) == 1.0


def test_round_trip():
    p = [1.5, -2.0, 3.25]
    assert pixera_to_blender_position(blender_to_pixera_position(p)) == p
