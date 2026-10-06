"""Live-hybrid view-cone marker recommender.

Reads a projector's pose from the Pixera API, builds its view cone from a
user-supplied lens, culls the user-supplied mesh to what the projector can
usefully light, and proposes marker positions for calibration. The pure compute
(`compute_from_mesh`) is offline-testable; the async wrappers add the live pose
fetch and the marker write-back.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .client import PixeraTCPClient
from .geometry import (
    ProjectorFrustum, _euler_to_matrix, calibratability, condition_number,
    filter_visible_faces, select_markers, spread_3d,
)
from .lens import LensSpec
from .meshio import Mesh, load_mesh

_API_CAVEAT = ("Projector pose is read live; lens + mesh are user-supplied (Pixera's API exposes "
               "neither). Existing warp/calibration cannot be imported. Accuracy depends on the "
               "lens spec, the mesh matching the real object, and the pose/mesh frames agreeing.")


def _apply_transform(mesh: Mesh, transform: dict | None) -> Mesh:
    if not transform:
        return mesh
    pos = np.asarray(transform.get("position", [0, 0, 0]), float)
    rot = transform.get("rotation", [0, 0, 0])
    scale = transform.get("scale", [1, 1, 1])
    rotm = _euler_to_matrix(float(rot[0]), float(rot[1]), float(rot[2]))
    scalem = np.diag(np.asarray(scale, float))
    verts = mesh.vertices @ (rotm @ scalem).T + pos
    return Mesh(verts, mesh.faces)


def compute_from_mesh(mesh: Mesh, pose: dict, lens: LensSpec, *, num_markers: int = 6,
                      grazing_deg: float = 75.0, do_occlusion: bool = False,
                      euler_order: str = "ZYX") -> dict[str, Any]:
    """Core, file-free recommendation. ``pose`` = {position:(x,y,z), rotation:(x,y,z)}."""
    frustum = ProjectorFrustum.from_euler(pose["position"], pose["rotation"], lens, order=euler_order)
    visible, cull_info = filter_visible_faces(mesh, frustum, grazing_deg=grazing_deg,
                                              do_occlusion=do_occlusion)
    metrics = calibratability(mesh, frustum, visible)

    warnings: list[str] = []
    if len(visible) == 0:
        warnings.append("This projector sees no usable faces of the mesh (after frustum/back-face/"
                        "grazing culling). Check the lens spec, mesh transform, and rotation order.")
        return {"marker_count": 0, "markers": [], "marker_ids": [], "positions_flat": [],
                "vqi": 0.0, "metrics": metrics, "cull_info": cull_info,
                "warnings": warnings, "caveat": _API_CAVEAT}

    centers = mesh.face_centers[visible]
    pick = select_markers(centers, num_markers)
    marker_xyz = centers[pick]
    marker_ids = list(range(1, len(pick) + 1))
    cond = condition_number(marker_xyz)
    spread = spread_3d(marker_xyz)

    if metrics["visible_area_fraction"] < 0.05:
        warnings.append(f"Only {metrics['visible_area_fraction'] * 100:.1f}% of the mesh area is "
                        "visible to this projector — calibration coverage is limited.")
    if metrics["mean_incidence"] < 0.30:
        warnings.append("Visible faces are viewed at a shallow (oblique) angle — markers will be "
                        "stretched and less precise.")
    if spread < 0.05:
        warnings.append("The visible patch is nearly coplanar — risk of 2-fold PnP pose ambiguity. "
                        "Prefer a viewpoint that sees multiple faces, or use more projectors.")
    if len(visible) < num_markers:
        warnings.append(f"Only {len(visible)} visible faces for {num_markers} requested markers.")

    return {
        "marker_count": len(pick),
        "markers": [{"id": mid, "position": [round(float(v), 4) for v in xyz]}
                    for mid, xyz in zip(marker_ids, marker_xyz)],
        "marker_ids": marker_ids,
        "positions_flat": [round(float(v), 4) for xyz in marker_xyz for v in xyz],
        "vqi": round(metrics["vqi"], 4),
        "metrics": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in metrics.items()},
        "marker_condition_number": (None if cond == float("inf") else round(cond, 3)),
        "marker_spread_3d": round(spread, 4),
        "cull_info": cull_info,
        "warnings": warnings,
        "caveat": _API_CAVEAT,
    }


async def recommend_markers_for_projector(
    client: PixeraTCPClient, projector_name: str, lens: dict, mesh_path: str,
    mesh_transform: dict | None = None, num_markers: int = 6,
    grazing_deg: float = 75.0, do_occlusion: bool = False, euler_order: str = "ZYX",
) -> dict[str, Any]:
    pose = await client.get_projector_pose(projector_name)
    mesh = _apply_transform(load_mesh(mesh_path), mesh_transform)
    result = compute_from_mesh(mesh, pose, LensSpec.from_dict(lens), num_markers=num_markers,
                               grazing_deg=grazing_deg, do_occlusion=do_occlusion,
                               euler_order=euler_order)
    result["projector"] = projector_name
    result["pose"] = {"position": list(pose["position"]), "rotation": list(pose["rotation"])}
    result["pose_source"] = "live Pixera API (getPosition/getRotation)"
    result["next_step"] = ("Place these markers in Pixera's Marker Calibration, or call apply_markers "
                           "to push them via setMarkerPositions, then iterate Calculate.")
    return result


async def score_projector_calibratability(
    client: PixeraTCPClient, projector_name: str, lens: dict, mesh_path: str,
    mesh_transform: dict | None = None, grazing_deg: float = 75.0, euler_order: str = "ZYX",
) -> dict[str, Any]:
    pose = await client.get_projector_pose(projector_name)
    mesh = _apply_transform(load_mesh(mesh_path), mesh_transform)
    frustum = ProjectorFrustum.from_euler(pose["position"], pose["rotation"],
                                          LensSpec.from_dict(lens), order=euler_order)
    visible, cull_info = filter_visible_faces(mesh, frustum, grazing_deg=grazing_deg)
    metrics = calibratability(mesh, frustum, visible)
    vqi = metrics["vqi"]
    verdict = ("good" if vqi >= 0.5 else "acceptable" if vqi >= 0.2 else "poor")
    return {
        "projector": projector_name,
        "pose": {"position": list(pose["position"]), "rotation": list(pose["rotation"])},
        "vqi": round(vqi, 4),
        "verdict": verdict,
        "metrics": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in metrics.items()},
        "cull_info": cull_info,
        "caveat": _API_CAVEAT,
    }


async def apply_markers(client: PixeraTCPClient, screen_name: str | None,
                        positions: list[float], marker_ids: list[int]) -> dict[str, Any]:
    """Push world-space markers via ``Pixera.Calibration.setMarkerPositions``.

    The rev 481 API takes no screen or projector handle: the markers apply to the
    marker calibration that is open in Pixera. ``screen_name`` is only echoed back.
    """
    if len(positions) != 3 * len(marker_ids):
        raise ValueError(f"positions has {len(positions)} values; expected 3 x {len(marker_ids)} "
                         "(flattened x,y,z per marker).")
    await client.request("Pixera.Calibration.setMarkerPositions",
                         {"positions": [float(v) for v in positions],
                          "markerIds": [int(i) for i in marker_ids]})
    return {
        "applied": True,
        "screen": screen_name,
        "marker_count": len(marker_ids),
        "note": ("Markers pushed via Pixera.Calibration.setMarkerPositions (world space, no screen "
                 "handle). Open the marker calibration for the target screen in Pixera and "
                 "trigger the solve (Calculate) there."),
    }
