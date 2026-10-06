"""Tests for the view-cone culling + marker-placement geometry (numpy, offline)."""

from __future__ import annotations

import math
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from pixera_mcp.geometry import (  # noqa: E402
    ProjectorFrustum, calibratability, condition_number, filter_visible_faces,
    select_markers, spread_3d,
)
from pixera_mcp.lens import LensSpec  # noqa: E402
from pixera_mcp.meshio import Mesh, box_mesh  # noqa: E402
from pixera_mcp.tools_geometry import _apply_transform, compute_from_mesh  # noqa: E402


def _quad(z: float, n: int = 0) -> tuple[np.ndarray, np.ndarray]:
    verts = np.array([[-1, -1, z], [1, -1, z], [1, 1, z], [-1, 1, z]], float)
    faces = np.array([[0, 1, 2], [0, 2, 3]], int) + n
    return verts, faces


# ------------------------------------------------------------------ lens math
def test_fov_from_throw_ratio():
    # throw_ratio 0.5 -> very wide; FOV_h = 2*atan(0.5/0.5) = 90 deg
    lens = LensSpec(throw_ratio=0.5, aspect=1.0)
    assert abs(lens.horizontal_fov_deg - 90.0) < 1e-6
    assert abs(lens.vertical_fov_deg - 90.0) < 1e-6
    # aspect from resolution
    lens2 = LensSpec(fov_h_deg=60.0, resolution=(1920, 1080))
    assert abs(lens2.aspect - 16 / 9) < 1e-6


def test_box_mesh_outward_normals():
    mesh = box_mesh(size=(2, 2, 2))
    assert mesh.num_faces == 12
    # each face normal should point away from the origin (outward)
    outward = np.sum(mesh.face_normals * mesh.face_centers, axis=1)
    assert np.all(outward > 0)


# ------------------------------------------------- frustum + back-face culling
def test_corner_view_sees_three_faces():
    mesh = box_mesh(size=(2, 2, 2))
    lens = LensSpec(fov_h_deg=60.0, aspect=1.0)
    frustum = ProjectorFrustum.from_look_at((5, 5, 5), (0, 0, 0), (0, 1, 0), lens)
    visible, info = filter_visible_faces(mesh, frustum)
    # A corner view illuminates exactly the +X, +Y, +Z faces (2 triangles each).
    assert len(visible) == 6
    # All visible faces face outward toward the projector (normal sum > 0 here).
    assert np.all(mesh.face_normals[visible].sum(axis=1) > 0)
    assert info["in_frustum"] >= 6 and info["after_grazing"] == 6


def test_back_faces_culled():
    mesh = box_mesh(size=(2, 2, 2))
    lens = LensSpec(fov_h_deg=90.0, aspect=1.0)
    frustum = ProjectorFrustum.from_look_at((0, 0, 8), (0, 0, 0), (0, 1, 0), lens)
    visible, _ = filter_visible_faces(mesh, frustum)
    # Looking straight down -Z: only the +Z face (2 triangles) is front-facing.
    assert len(visible) == 2
    assert np.allclose(mesh.face_normals[visible], np.array([0, 0, 1.0]))


# --------------------------------------------------------- grazing-angle gate
def test_grazing_faces_rejected():
    verts, faces = _quad(0.0)
    mesh = Mesh(verts, faces)  # normal +Z
    lens = LensSpec(fov_h_deg=120.0, aspect=1.0)
    # Projector almost in the plane of the face -> ~87 deg incidence (grazing).
    frustum = ProjectorFrustum.from_look_at((10, 0, 0.5), (0, 0, 0), (0, 1, 0), lens)
    strict, _ = filter_visible_faces(mesh, frustum, grazing_deg=75.0)
    lenient, _ = filter_visible_faces(mesh, frustum, grazing_deg=89.0)
    assert len(strict) == 0          # rejected as grazing
    assert len(lenient) == 2         # accepted when threshold relaxed


# --------------------------------------------------------------- occlusion
def test_occlusion_culls_hidden_quad():
    vn, fn = _quad(0.0, 0)        # near quad at z=0
    vf, ff = _quad(-5.0, 4)       # far quad at z=-5 (behind, from projector at +z)
    mesh = Mesh(np.vstack([vn, vf]), np.vstack([fn, ff]))
    lens = LensSpec(fov_h_deg=60.0, aspect=1.0)
    frustum = ProjectorFrustum.from_look_at((0, 0, 10), (0, 0, 0), (0, 1, 0), lens)

    without, info0 = filter_visible_faces(mesh, frustum, do_occlusion=False)
    withocc, info1 = filter_visible_faces(mesh, frustum, do_occlusion=True)
    assert len(without) == 4 and info0["occlusion_run"] is False
    assert len(withocc) == 2 and info1["occlusion_run"] is True
    # Surviving faces are the near quad (z == 0).
    assert np.allclose(mesh.face_centers[withocc][:, 2], 0.0)


# ----------------------------------------------------- marker selection/metrics
def test_marker_selection_spreads():
    mesh = box_mesh(size=(2, 2, 2))
    lens = LensSpec(fov_h_deg=60.0, aspect=1.0)
    frustum = ProjectorFrustum.from_look_at((5, 5, 5), (0, 0, 0), (0, 1, 0), lens)
    visible, _ = filter_visible_faces(mesh, frustum)
    centers = mesh.face_centers[visible]
    pick = select_markers(centers, 4)
    assert len(pick) == 4 and len(set(pick.tolist())) == 4
    extent = centers[pick].max(axis=0) - centers[pick].min(axis=0)
    assert np.all(extent > 1.0)  # spread across the three visible faces


def test_condition_and_spread():
    collinear = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0]], float)
    assert spread_3d(collinear) < 1e-6
    assert math.isinf(condition_number(collinear))
    cube = box_mesh(size=(2, 2, 2)).vertices
    assert spread_3d(cube) > 0.3
    assert math.isfinite(condition_number(cube))


def test_vqi_in_range():
    mesh = box_mesh(size=(2, 2, 2))
    lens = LensSpec(fov_h_deg=60.0, aspect=1.0)
    frustum = ProjectorFrustum.from_look_at((5, 5, 5), (0, 0, 0), (0, 1, 0), lens)
    visible, _ = filter_visible_faces(mesh, frustum)
    score = calibratability(mesh, frustum, visible)
    assert 0.0 < score["vqi"] <= 1.0
    assert score["visible_faces"] == 6
    # Empty visibility scores zero.
    empty = calibratability(mesh, frustum, np.array([], dtype=int))
    assert empty["vqi"] == 0.0


def test_from_euler_builds_basis():
    # Identity rotation: forward axis (+Z) maps to +Z, basis stays orthonormal.
    lens = LensSpec(fov_h_deg=60.0, aspect=1.0)
    fr = ProjectorFrustum.from_euler((0, 0, 0), (0, 0, 0), lens)
    assert np.allclose(fr.forward, [0, 0, 1])
    assert abs(np.dot(fr.forward, fr.right)) < 1e-9
    assert abs(np.dot(fr.right, fr.up)) < 1e-9


def test_compute_from_mesh_end_to_end():
    mesh = box_mesh(size=(2, 2, 2))
    lens = LensSpec(fov_h_deg=90.0, aspect=1.0)
    # Projector at +Z looking back toward origin (rotation 180 about Y -> forward -Z).
    pose = {"position": (0, 0, 8), "rotation": (0, 180, 0)}
    out = compute_from_mesh(mesh, pose, lens, num_markers=6)
    assert out["marker_count"] == 2                      # only the +Z face is visible (2 tris)
    assert len(out["positions_flat"]) == 3 * out["marker_count"]
    assert out["vqi"] > 0.0
    assert all(abs(m["position"][2] - 1.0) < 1e-6 for m in out["markers"])  # on the +Z face
    assert isinstance(out["warnings"], list)


def test_apply_transform_translates_vertices():
    mesh = box_mesh(size=(2, 2, 2))
    moved = _apply_transform(mesh, {"position": [10, 0, 0]})
    assert np.allclose(moved.face_centers[:, 0] - mesh.face_centers[:, 0], 10.0)


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("geometry: all passed")


if __name__ == "__main__":
    _run_all()
