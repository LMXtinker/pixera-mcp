"""Mesh loading and the lightweight :class:`Mesh` used by the view-cone culler.

Pixera does not expose mesh geometry via its API, so the recommender loads the
projection-surface model from a file the user supplies. ``trimesh`` (optional
dependency, extra ``mesh``) handles OBJ/FBX/GLTF/PLY/STL; without it a built-in
parser covers OBJ only. FBX additionally needs ``trimesh`` + assimp, otherwise
export to OBJ/GLTF.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Mesh:
    """Triangle mesh with cached per-face geometry.

    ``vertices`` is (N, 3); ``faces`` is (M, 3) integer indices. Face normals
    follow the winding of ``faces`` and are assumed to point **outward** (the
    convention for back-face culling). Loaders normalise winding where possible.
    """

    vertices: np.ndarray
    faces: np.ndarray

    def __post_init__(self) -> None:
        self.vertices = np.asarray(self.vertices, dtype=float).reshape(-1, 3)
        self.faces = np.asarray(self.faces, dtype=int).reshape(-1, 3)
        v0 = self.vertices[self.faces[:, 0]]
        v1 = self.vertices[self.faces[:, 1]]
        v2 = self.vertices[self.faces[:, 2]]
        self.face_centers = (v0 + v1 + v2) / 3.0
        cross = np.cross(v1 - v0, v2 - v0)
        norm = np.linalg.norm(cross, axis=1)
        self.face_areas = 0.5 * norm
        safe = np.where(norm > 1e-12, norm, 1.0)[:, None]
        self.face_normals = cross / safe

    @property
    def num_faces(self) -> int:
        return int(self.faces.shape[0])


def box_mesh(center=(0.0, 0.0, 0.0), size=(1.0, 1.0, 1.0)) -> Mesh:
    """An axis-aligned box with outward-facing winding (handy for tests/demos)."""
    cx, cy, cz = center
    sx, sy, sz = (s / 2.0 for s in size)
    v = np.array([
        [cx - sx, cy - sy, cz - sz],  # 0 (-,-,-)
        [cx + sx, cy - sy, cz - sz],  # 1 (+,-,-)
        [cx + sx, cy + sy, cz - sz],  # 2 (+,+,-)
        [cx - sx, cy + sy, cz - sz],  # 3 (-,+,-)
        [cx - sx, cy - sy, cz + sz],  # 4 (-,-,+)
        [cx + sx, cy - sy, cz + sz],  # 5 (+,-,+)
        [cx + sx, cy + sy, cz + sz],  # 6 (+,+,+)
        [cx - sx, cy + sy, cz + sz],  # 7 (-,+,+)
    ], dtype=float)
    faces = np.array([
        [4, 5, 6], [4, 6, 7],   # +Z
        [1, 0, 3], [1, 3, 2],   # -Z
        [1, 2, 6], [1, 6, 5],   # +X
        [0, 4, 7], [0, 7, 3],   # -X
        [3, 7, 6], [3, 6, 2],   # +Y
        [0, 1, 5], [0, 5, 4],   # -Y
    ], dtype=int)
    return Mesh(v, faces)


def load_mesh(path: str | Path) -> Mesh:
    """Load a mesh from disk. Uses trimesh if installed, else an OBJ fallback."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Mesh file not found: {path}")
    try:
        import trimesh  # type: ignore

        loaded = trimesh.load(str(path), force="mesh", process=False)
        if not hasattr(loaded, "faces") or len(loaded.faces) == 0:
            raise ValueError(f"No triangle faces in {path}")
        return Mesh(np.asarray(loaded.vertices), np.asarray(loaded.faces))
    except ImportError:
        if path.suffix.lower() != ".obj":
            raise ImportError(
                f"Loading '{path.suffix}' requires the optional 'mesh' extra "
                "(pip install 'pixera-mcp[mesh]'). For now, export the model to "
                ".obj or install trimesh."
            )
        return _load_obj(path)


def _load_obj(path: Path) -> Mesh:
    """Minimal OBJ reader: 'v' vertices and 'f' faces (polygons fan-triangulated)."""
    vertices: list[list[float]] = []
    faces: list[list[int]] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("v "):
                parts = line.split()
                vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
            elif line.startswith("f "):
                idx = []
                for token in line.split()[1:]:
                    # handles 'v', 'v/vt', 'v/vt/vn', 'v//vn'; OBJ is 1-indexed
                    raw = token.split("/")[0]
                    idx.append(int(raw) - 1 if int(raw) > 0 else len(vertices) + int(raw))
                for k in range(1, len(idx) - 1):  # fan triangulation
                    faces.append([idx[0], idx[k], idx[k + 1]])
    if not faces:
        raise ValueError(f"No faces parsed from {path}")
    return Mesh(np.array(vertices, dtype=float), np.array(faces, dtype=int))
