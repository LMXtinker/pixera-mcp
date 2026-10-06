"""Offline guidance logic: calibration-method choice, warp choice, diagnosis, planning.

Pure functions returning JSON-serialisable dicts. ``server.py`` registers thin
MCP-tool wrappers around these; keeping the logic here makes it unit-testable
without ``mcp`` or a live Pixera.
"""

from __future__ import annotations

from typing import Any

from .validation import SRC


def recommend_calibration_method(surface_type: str, projector_count: int = 1,
                                 accuracy_need: str = "standard",
                                 time_budget: str = "normal",
                                 has_camera: bool = False) -> dict[str, Any]:
    """Choose a calibration approach from the algorithm-vs-use-case decision table."""
    s = surface_type.lower()
    flat = s in ("flat", "planar", "screen", "wall")
    many = projector_count >= 4
    high = accuracy_need.lower() in ("high", "subpixel")

    if (many or not flat) and has_camera and (high or many or s in ("dome", "curved")):
        choice = {
            "method": "Camera-based structured-light (VIOSO)",
            "min_points": "dense (automatic)",
            "why": "Automated structured-light + bundle adjustment gives sub-pixel results and "
                   "scales to many projectors and curved/dome surfaces.",
            "accuracy": "~0.2-0.5 px",
            "needs": "Calibration camera (e.g. Daheng), 'Texture per Screen', VIOSO licence.",
        }
    elif flat and projector_count <= 1:
        choice = {
            "method": "Planar homography (manual markers)",
            "min_points": "4 coplanar",
            "why": "A single flat surface is a planar homography — fastest path, 4 corner points.",
            "accuracy": "~0.5-2 px",
            "needs": "Nothing beyond Pixera.",
        }
    else:
        choice = {
            "method": "Marker calibration (PnP / point-correspondence)",
            "min_points": "6 non-coplanar (≥5 enforced by Pixera)",
            "why": "3D/object surfaces need full projector pose from non-coplanar 2D-3D "
                   "correspondences. Pixera's Marker Calibration solves exactly this.",
            "accuracy": "~1-3 px (better with more, well-spread markers)",
            "needs": "An accurate 3D model (ideally a scan); pre-set lens; EDIDs set.",
        }

    alternatives = [
        "MPCDI import — if calibration was produced by an external tool/vendor.",
        "Camera-based (VIOSO) — when accuracy/scale justifies a camera rig.",
        "Marker calibration — when no camera is available but a good 3D model exists.",
    ]
    return {
        "recommended": choice,
        "inputs": {"surface_type": surface_type, "projector_count": projector_count,
                   "accuracy_need": accuracy_need, "time_budget": time_budget,
                   "has_camera": has_camera},
        "alternatives": alternatives,
        "reminders": [
            "Set EDIDs before any calibration.",
            "Pre-set lens (throw/shift/FOV) — do not let the solver guess them.",
            "Markers: ≥5, in all corners, non-coplanar with depth variation.",
        ],
        "sources": [SRC["marker"], SRC["camera"]],
    }


def recommend_warp_method(surface_type: str = "flat", has_3d_model: bool = False,
                          curved: bool = False, tracked: bool = False,
                          non_rectangular: bool = False) -> dict[str, Any]:
    """Pick FFD vs Vertex vs Polygonal vs Multi-Pos warp."""
    if tracked:
        pick = ("Multi-Pos Warp",
                "Tracked/virtual-production cameras need per-viewpoint warps blended between "
                "saved positions. Use overscan 1.05-1.2 and uncheck 'Scale Resolution'.")
    elif has_3d_model:
        pick = ("Vertex Modifier",
                "For an imported 3D model, edit the mesh's own vertex points; FFD control points "
                "are better for screen-space surfaces.")
    elif non_rectangular:
        pick = ("Polygonal Warp",
                "Non-rectangular feeds need polygonal feed editing (requires Pixel-Accurate feed).")
    else:
        pick = ("FFD Modifier (Bezier)",
                "Free-Form Deformer is the preferred warp for most surfaces; use Bezier "
                "interpolation (Linear can facet on curves).")
    notes = []
    if curved:
        notes.append("Curved surface: prefer Bezier interpolation; add subdivisions where needed.")
    return {"method": pick[0], "why": pick[1], "notes": notes,
            "sources": [SRC["warp_softedge"]]}


_SYMPTOMS: list[dict[str, Any]] = [
    {
        "keys": ["seam", "visible line", "line between", "hard edge"],
        "causes": ["Soft edge missing or mismatched overlap between projectors.",
                   "Inconsistent blend width or gamma across the pair."],
        "fixes": ["Enable Feed Areas, Generate Auto Softedge, match ~20% overlap on both sides.",
                  "Keep blend width/gamma equal across adjacent projectors."],
        "src": ["softedge", "feed"],
    },
    {
        "keys": ["black box", "black output", "all black", "projects black", "completely black"],
        "causes": ["Feed Mode 'None' used on a surface that needs Fit/Stretch.",
                   "Output not assigned/activated."],
        "fixes": ["Use Fit/Stretch/Pixel Accurate for flat surfaces; 'None' only for 3D/non-continuous UV.",
                  "Assign and activate the projector output."],
        "src": ["warp_softedge"],
    },
    {
        "keys": ["raised black", "black level", "milky", "grey overlap", "gray overlap"],
        "causes": ["Overlap region shows lifted blacks (projector black is not true black)."],
        "fixes": ["Use 'Clear Softedge All Visible'; align blend gamma; apply black-level/color "
                  "calibration per output where available."],
        "src": ["softedge"],
    },
    {
        "keys": ["facet", "faceting", "banding on curve", "angular curve"],
        "causes": ["Linear warp interpolation on a curved surface."],
        "fixes": ["Switch FFD interpolation to Bezier; add subdivisions on the curve."],
        "src": ["warp_softedge"],
    },
    {
        "keys": ["warp lost", "warp gone", "reroute", "lost calibration"],
        "causes": ["Projector was rerouted; warp can be dropped. EDIDs not locked."],
        "fixes": ["Avoid unnecessary rerouting; set/lock EDIDs first so outputs stay stable."],
        "src": ["edid"],
    },
    {
        "keys": ["marker not detect", "markers not detected", "can't see marker", "cant see marker"],
        "causes": ["Markers too small/low-contrast; grazing angle; output not active."],
        "fixes": ["Increase marker size/brightness (25.1+); move markers off grazing faces; "
                  "activate the output before aligning."],
        "src": ["marker2"],
    },
    {
        "keys": ["oscillat", "ambiguous", "pose jumps", "two solutions", "unstable solve"],
        "causes": ["Markers are coplanar -> 2-fold PnP ambiguity."],
        "fixes": ["Spread markers across depth/faces so they are non-coplanar; use ≥6 points."],
        "src": ["marker2"],
    },
]


def diagnose(symptom: str) -> dict[str, Any]:
    """Map a free-text symptom to likely causes + fixes from the knowledge base."""
    q = symptom.lower()
    matches = []
    for entry in _SYMPTOMS:
        if any(k in q for k in entry["keys"]):
            matches.append({
                "likely_causes": entry["causes"],
                "fixes": entry["fixes"],
                "sources": [SRC[s] for s in entry["src"]],
            })
    if not matches:
        return {
            "matched": False,
            "message": f"No direct match for {symptom!r}.",
            "known_symptoms": ["visible seam", "black output", "raised blacks", "faceting on curve",
                               "warp lost on reroute", "markers not detected", "unstable/oscillating solve"],
        }
    return {"matched": True, "symptom": symptom, "diagnoses": matches}


def plan_projection_mapping(surface_type: str = "flat", projector_count: int = 1,
                            content_type: str = "video", curved: bool = False,
                            tracked: bool = False) -> dict[str, Any]:
    """Produce an ordered, scenario-tailored setup plan across Pixera's modes."""
    is_3d = surface_type.lower() in ("3d", "object", "curved") or curved
    steps = [
        {"phase": "Project", "action": "Settings → Project → New; name and save; press G for the grid."},
        {"phase": "Screens", "action": (
            "Add a 3D model as the Screen (Role: Screen) and import its UV map."
            if is_3d else
            "Add a Generic Flat Screen; set Width/Height (m) and Canvas Resolution to the "
            "projector's native resolution.")},
        {"phase": "Mapping", "action": (
            f"Add {projector_count} projector(s) from the Library; set position/rotation/lens "
            "(throw, shift). Auto-align with Ctrl+Alt+A.")},
    ]
    if projector_count >= 2:
        steps.append({"phase": "Mapping", "action":
                      "Select ALL projectors; set Feed Areas; aim for ~20% horizontal overlap; "
                      "Generate Auto Softedge."})
    steps.append({"phase": "Mapping", "action": (
        "Set EDIDs first, then run Marker Calibration: ≥5 non-coplanar markers in the corners; "
        "iterate until Re-Projection Error < 1px."
        if is_3d else
        "Apply FFD warp (Bezier) to align corners; verify with a test pattern.")})
    if tracked:
        steps.append({"phase": "Mapping", "action":
                      "For tracked cameras use Multi-Pos Warp (overscan 1.05-1.2, Scale Resolution off)."})
    steps += [
        {"phase": "Compositing", "action":
            "Import media; drag onto the Screen (sets the layer's Home Screen); arrange layers; "
            "set Scale Unit Mode to 'Resource Resolution' to avoid stretching."},
        {"phase": "Compositing", "action": "Add cues for transport/jumps; press Space to play."},
    ]
    validations = ["validate_canvas_resolution", "validate_feed_mode"]
    if projector_count >= 2:
        validations.append("validate_softedge")
    if is_3d:
        validations.append("validate_marker_calibration")
    return {
        "scenario": {"surface_type": surface_type, "projector_count": projector_count,
                     "content_type": content_type, "curved": curved, "tracked": tracked},
        "steps": steps,
        "suggested_validations": validations,
        "sources": [SRC["warp_softedge"], SRC["feed"], SRC["marker"]],
    }
