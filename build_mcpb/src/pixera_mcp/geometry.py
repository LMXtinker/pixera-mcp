"""Projector view-cone culling and marker-placement heuristics (pure numpy).

Given a projector pose + lens and a mesh, determine which faces the projector
can usefully illuminate, then propose well-distributed marker positions for
point-correspondence (PnP) calibration.

Pipeline (per face, using the face centroid + normal):
  A. **Frustum cull**   - centroid inside the projector's view cone.
  B. **Back-face cull**  - outward normal points back toward the projector.
  C. **Occlusion**       - optional ray test against the rest of the mesh.
  D. **Grazing reject**  - incidence angle below threshold (default 75 deg);
                           grazing faces get stretched, low-res pixels.

This module is dependency-light (numpy only) and fully offline-testable; the
live MCP tool wraps it with a projector pose fetched from the Pixera API.

Convention note
---------------
:meth:`ProjectorFrustum.from_look_at` is convention-free and used in tests.
:meth:`ProjectorFrustum.from_euler` interprets the API rotation (Euler degrees)
with a documented axis/order that may need field tuning per Pixera's convention
- a flagged integration risk. The culling math only needs the orthonormal basis,
so it is independent of how that basis was derived.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    if n < 1e-12:
        raise ValueError("cannot normalize a zero-length vector")
    return v / n


def _normalize_rows(a: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(a, axis=1, keepdims=True)
    return a / np.where(n > 1e-12, n, 1.0)


def _euler_to_matrix(rx: float, ry: float, rz: float, order: str = "ZYX") -> np.ndarray:
    """Rotation matrix from Euler angles in **degrees**. Default intrinsic ZYX."""
    rx, ry, rz = math.radians(rx), math.radians(ry), math.radians(rz)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], float)
    my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], float)
    mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], float)
    mats = {"X": mx, "Y": my, "Z": mz}
    r = np.eye(3)
    for axis in order:  # left-to-right multiply => first listed is outermost
        r = r @ mats[axis]
    return r


@dataclass
class ProjectorFrustum:
    position: np.ndarray
    forward: np.ndarray
    up: np.ndarray
    fov_h_deg: float
    fov_v_deg: float
    near: float = 0.05
    far: float = 1000.0
    shift_h: float = 0.0
    shift_v: float = 0.0
    right: np.ndarray = field(init=False)
    _hh: float = field(init=False)
    _hv: float = field(init=False)

    def __post_init__(self) -> None:
        self.position = np.asarray(self.position, float).reshape(3)
        self.forward = _normalize(np.asarray(self.forward, float).reshape(3))
        up = np.asarray(self.up, float).reshape(3)
        self.right = _normalize(np.cross(self.forward, up))
        self.up = np.cross(self.right, self.forward)  # re-orthogonalize
        self._hh = math.tan(math.radians(self.fov_h_deg) / 2.0)
        self._hv = math.tan(math.radians(self.fov_v_deg) / 2.0)

    # --------------------------------------------------------- constructors
    @classmethod
    def from_look_at(cls, position, target, up, lens, near=0.05, far=1000.0) -> "ProjectorFrustum":
        position = np.asarray(position, float).reshape(3)
        forward = np.asarray(target, float).reshape(3) - position
        return cls(position, forward, up, lens.horizontal_fov_deg, lens.vertical_fov_deg,
                   near, far, lens.shift_h, lens.shift_v)

    @classmethod
    def from_euler(cls, position, rotation_deg, lens, *, order="ZYX",
                   forward_axis=(0, 0, 1), up_axis=(0, 1, 0),
                   near=0.05, far=1000.0) -> "ProjectorFrustum":
        r = _euler_to_matrix(*rotation_deg, order=order)
        forward = r @ np.asarray(forward_axis, float)
        up = r @ np.asarray(up_axis, float)
        return cls(np.asarray(position, float), forward, up,
                   lens.horizontal_fov_deg, lens.vertical_fov_deg,
                   near, far, lens.shift_h, lens.shift_v)

    # --------------------------------------------------------------- testing
    def _camera_coords(self, pts: np.ndarray):
        rel = pts - self.position
        depth = rel @ self.forward
        x = rel @ self.right
        y = rel @ self.up
        return x, y, depth

    def contains(self, pts: np.ndarray) -> np.ndarray:
        """Boolean mask: which points lie inside the view cone."""
        pts = np.asarray(pts, float).reshape(-1, 3)
        x, y, d = self._camera_coords(pts)
        in_depth = (d >= self.near) & (d <= self.far)
        safe_d = np.where(d > 1e-9, d, 1e-9)
        in_h = np.abs(x / safe_d - self.shift_h * self._hh) <= self._hh
        in_v = np.abs(y / safe_d - self.shift_v * self._hv) <= self._hv
        return in_depth & in_h & in_v


def filter_visible_faces(mesh, frustum: ProjectorFrustum, *, grazing_deg: float = 75.0,
                         do_occlusion: bool = False, max_occlusion_faces: int = 20000):
    """Return (visible_face_indices, info). Runs cull stages A, B, D (and C if asked)."""
    centers = mesh.face_centers
    normals = mesh.face_normals

    in_frustum = frustum.contains(centers)
    view = _normalize_rows(centers - frustum.position)
    dots = np.sum(normals * view, axis=1)            # <0 => normal faces projector
    front = dots < 0.0
    grazing_ok = np.abs(dots) >= math.cos(math.radians(grazing_deg))

    mask = in_frustum & front & grazing_ok
    info = {
        "total_faces": mesh.num_faces,
        "in_frustum": int(in_frustum.sum()),
        "front_facing": int((in_frustum & front).sum()),
        "after_grazing": int(mask.sum()),
        "occlusion_run": False,
    }

    if do_occlusion:
        if mesh.num_faces <= max_occlusion_faces:
            occluded = _occluded_faces(mesh, frustum.position, np.nonzero(mask)[0])
            mask[np.nonzero(mask)[0][occluded]] = False
            info["occlusion_run"] = True
            info["after_occlusion"] = int(mask.sum())
        else:
            info["occlusion_skipped_reason"] = (
                f"mesh has {mesh.num_faces} faces > cap {max_occlusion_faces}; "
                "occlusion test skipped (O(n^2))."
            )
    return np.nonzero(mask)[0], info


def _occluded_faces(mesh, origin: np.ndarray, candidate_idx: np.ndarray) -> np.ndarray:
    """Naive ray-vs-mesh occlusion (Moller-Trumbore). Returns a mask over candidates."""
    verts = mesh.vertices
    tris = mesh.faces
    v0 = verts[tris[:, 0]]
    e1 = verts[tris[:, 1]] - v0
    e2 = verts[tris[:, 2]] - v0
    occluded = np.zeros(len(candidate_idx), dtype=bool)
    eps = 1e-7
    for i, fidx in enumerate(candidate_idx):
        target = mesh.face_centers[fidx]
        d = target - origin
        dist = np.linalg.norm(d)
        if dist < eps:
            continue
        d = d / dist
        pvec = np.cross(d, e2)
        det = np.sum(e1 * pvec, axis=1)
        hit = np.abs(det) > eps
        inv = np.where(hit, 1.0 / np.where(hit, det, 1.0), 0.0)
        tvec = origin - v0
        u = np.sum(tvec * pvec, axis=1) * inv
        qvec = np.cross(tvec, e1)
        v = np.sum(d * qvec, axis=1) * inv
        t = np.sum(e2 * qvec, axis=1) * inv
        valid = hit & (u >= -eps) & (v >= -eps) & (u + v <= 1 + eps) & (t > 1e-4) & (t < dist - 1e-3)
        valid[fidx] = False  # ignore self
        if np.any(valid):
            occluded[i] = True
    return occluded


def select_markers(points: np.ndarray, n: int) -> np.ndarray:
    """Farthest-point sampling for maximally-spread markers. Returns row indices."""
    pts = np.asarray(points, float).reshape(-1, 3)
    m = len(pts)
    if m <= n:
        return np.arange(m)
    centroid = pts.mean(axis=0)
    first = int(np.argmax(((pts - centroid) ** 2).sum(axis=1)))
    chosen = [first]
    dist2 = ((pts - pts[first]) ** 2).sum(axis=1)
    for _ in range(n - 1):
        nxt = int(np.argmax(dist2))
        chosen.append(nxt)
        dist2 = np.minimum(dist2, ((pts - pts[nxt]) ** 2).sum(axis=1))
    return np.array(chosen, dtype=int)


def condition_number(points: np.ndarray) -> float:
    """Condition number of the centred point set (spread/collinearity health)."""
    p = np.asarray(points, float).reshape(-1, 3)
    if len(p) < 2:
        return float("inf")
    s = np.linalg.svd(p - p.mean(axis=0), compute_uv=False)
    return float(s[0] / s[-1]) if s[-1] > 1e-12 else float("inf")


def spread_3d(points: np.ndarray) -> float:
    """0 = coplanar/collinear (bad for 3D PnP); ~1 = isotropic 3D spread."""
    p = np.asarray(points, float).reshape(-1, 3)
    if len(p) < 3:
        return 0.0
    s = np.linalg.svd(p - p.mean(axis=0), compute_uv=False)
    return float(s[2] / s[0]) if s[0] > 1e-12 else 0.0


def calibratability(mesh, frustum: ProjectorFrustum, visible_idx: np.ndarray) -> dict:
    """Visibility Quality Index (VQI) in [0, 1] plus its component breakdown."""
    if len(visible_idx) == 0:
        return {"vqi": 0.0, "visible_area_fraction": 0.0, "mean_incidence": 0.0,
                "spread_3d": 0.0, "visible_faces": 0}
    areas = mesh.face_areas
    centers = mesh.face_centers[visible_idx]
    normals = mesh.face_normals[visible_idx]
    view = _normalize_rows(centers - frustum.position)
    incidence = float(np.abs(np.sum(normals * view, axis=1)).mean())  # 1=head-on, 0=grazing
    area_frac = float(areas[visible_idx].sum() / max(areas.sum(), 1e-12))
    sf = spread_3d(centers)
    vqi = float(np.clip(area_frac * incidence * (0.5 + 0.5 * sf), 0.0, 1.0))
    return {"vqi": vqi, "visible_area_fraction": area_frac, "mean_incidence": incidence,
            "spread_3d": sf, "visible_faces": int(len(visible_idx))}
