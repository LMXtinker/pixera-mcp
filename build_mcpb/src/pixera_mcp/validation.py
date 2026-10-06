"""Parameter-validation rules for Pixera projection-mapping workflows.

Each ``validate_*`` function takes a context dict (typically built from MCP tool
arguments or live API reads) and returns a list of :class:`Finding`. An empty
list means "no problems detected". Rules are seeded from official Pixera docs and
projection-mapping best practice; every finding cites a source so the agent can
explain *why* a parameter is wrong for the chosen workflow.

These functions are pure and have no dependency on ``mcp`` or a live connection,
so they are unit-testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --- documentation sources -------------------------------------------------
SRC = {
    "softedge": "https://help.pixera.one/softedge-creation",
    "warp_softedge": "https://help.pixera.one/en_US/mapping-/warping-feedmodes-and-softedge",
    "marker": "https://help.pixera.one/en_US/mapping-/2428906-marker-calibration-workflow",
    "marker2": "https://help.pixera.one/1215945-marker-calibration",
    "camera": "https://help.pixera.one/1218507-camera-based-calibration",
    "screen_size": "https://help.pixera.one/en_US/screens-/screen-size",
    "feed": "https://help.pixera.one/working-with-projectors/1223953-untitled-article",
    "edid": "https://help.pixera.one/graphic-cards/edid-management",
    "uv": "https://help.pixera.one/en_US/uv-maps",
}

_RECOMMENDED_OVERLAP = 20.0   # percent horizontal overlap (Pixera "ideal")
_OVERLAP_MIN = 15.0
_OVERLAP_MAX = 35.0
_REPROJ_WARN = 1.0            # px @ HD
_REPROJ_ERROR = 3.0


@dataclass
class Finding:
    severity: str          # "error" | "warn" | "info"
    message: str
    fix: str
    source: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "message": self.message,
                "fix": self.fix, "source": self.source}


def _err(msg: str, fix: str, src: str) -> Finding:
    return Finding("error", msg, fix, src)


def _warn(msg: str, fix: str, src: str) -> Finding:
    return Finding("warn", msg, fix, src)


def _info(msg: str, fix: str, src: str) -> Finding:
    return Finding("info", msg, fix, src)


def summarize(findings: list[Finding]) -> dict[str, Any]:
    """Roll findings into a tool-friendly result with a pass/fail verdict."""
    has_error = any(f.severity == "error" for f in findings)
    has_warn = any(f.severity == "warn" for f in findings)
    verdict = "fail" if has_error else ("review" if has_warn else "pass")
    return {
        "verdict": verdict,
        "ok": not has_error,
        "counts": {
            "error": sum(f.severity == "error" for f in findings),
            "warn": sum(f.severity == "warn" for f in findings),
            "info": sum(f.severity == "info" for f in findings),
        },
        "findings": [f.to_dict() for f in findings],
    }


# --------------------------------------------------------------- soft edge
def validate_softedge(ctx: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    count = int(ctx.get("projector_count", 0))
    overlaps = [float(x) for x in ctx.get("overlaps", [])]
    feed_areas = bool(ctx.get("feed_areas_enabled", True))
    feed_mode = str(ctx.get("feed_mode", "")).lower()
    surface = str(ctx.get("surface_type", "flat")).lower()
    dynamic = bool(ctx.get("dynamic_softedge", False))
    all_selected = ctx.get("all_projectors_selected")

    if count < 2:
        out.append(_info(
            "Soft edge only applies to 2+ overlapping projectors.",
            "If this is a single projector, no blend is needed.", SRC["softedge"]))

    if not feed_areas:
        out.append(_err(
            "Feed Areas are not enabled; 'Generate Auto Softedge' cannot calculate.",
            "Select all projectors, set Feed Areas (Fit/Stretch/Pixel Accurate) in Setup, "
            "then Generate Auto Softedge.", SRC["warp_softedge"]))

    for i, ov in enumerate(overlaps):
        if ov < _OVERLAP_MIN:
            out.append(_warn(
                f"Overlap pair {i + 1} is {ov:.0f}% — below the ~{_RECOMMENDED_OVERLAP:.0f}% "
                "horizontal overlap Pixera recommends.",
                "Increase projector overlap toward ~20% for a stable blend.", SRC["feed"]))
        elif ov > _OVERLAP_MAX:
            out.append(_warn(
                f"Overlap pair {i + 1} is {ov:.0f}% — unusually large; wastes resolution.",
                "Reduce overlap toward ~20% unless the surface needs more.", SRC["feed"]))

    if len(overlaps) >= 2 and (max(overlaps) - min(overlaps)) > 8.0:
        out.append(_err(
            f"Overlaps are inconsistent ({min(overlaps):.0f}%–{max(overlaps):.0f}%) between "
            "adjacent projectors — this produces visible seams.",
            "Match overlap width across all adjacent pairs (~20%).", SRC["feed"]))

    if feed_mode == "none" and surface == "flat":
        out.append(_err(
            "Feed Mode 'None' on a flat surface typically projects black.",
            "Use Fit / Stretch / Pixel Accurate for flat surfaces; reserve 'None' for "
            "3D objects with non-continuous UVs.", SRC["warp_softedge"]))

    if surface in ("3d", "curved") and not dynamic:
        out.append(_warn(
            "Static soft edge on a 3D/curved or moving surface may not blend correctly.",
            "Enable Dynamic Softedge (engine-side) for 3D/moving surfaces.", SRC["warp_softedge"]))

    if all_selected is False:
        out.append(_warn(
            "Feed Mode changes were not applied with all projectors selected.",
            "Select ALL projectors before changing Feed Areas, or the setting applies to one.",
            SRC["feed"]))

    return out


# --------------------------------------------------------- marker calibration
def validate_marker_calibration(ctx: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    n = int(ctx.get("marker_count", 0))
    placement = str(ctx.get("placement", "")).lower()
    coplanar = bool(ctx.get("coplanar", False))
    depth_varied = bool(ctx.get("depth_varied", True))
    lens_preset = bool(ctx.get("lens_preset", True))
    edids_set = bool(ctx.get("edids_set", True))
    model_from_scan = bool(ctx.get("model_from_scan", True))
    surface = str(ctx.get("surface_type", "3d")).lower()
    reproj = ctx.get("reprojection_error")
    is_3d = surface in ("3d", "curved", "object")

    if not edids_set:
        out.append(_err(
            "EDIDs are not set. Windows display-enumeration changes will corrupt warping.",
            "Set/lock EDIDs on all outputs BEFORE calibrating.", SRC["edid"]))

    if n < 5:
        out.append(_err(
            f"Only {n} markers. Pixera advises a minimum of 5.",
            "Add markers until you have at least 5 (more improves stability).", SRC["marker"]))
    if is_3d and n < 6:
        out.append(_warn(
            f"{n} markers for a 3D surface. PnP pose wants ≥6 non-coplanar points.",
            "Use 6–8 markers spread across depth for a 3D solve.", SRC["marker"]))

    if is_3d and coplanar:
        out.append(_err(
            "Markers are coplanar on a 3D surface — this causes a 2-fold pose ambiguity "
            "(the solve oscillates between two poses).",
            "Distribute markers across different faces/depths so they are non-coplanar.",
            SRC["marker2"]))
    if is_3d and not depth_varied:
        out.append(_warn(
            "Markers lack depth variation; the pose solve will be weakly constrained.",
            "Place markers on front and side/rear faces to span depth.", SRC["marker2"]))

    if placement and placement not in ("corners", "corners+edges", "spread"):
        out.append(_warn(
            f"Marker placement '{placement}' is not corner-biased.",
            "Place markers as far out as possible, ideally in all corners of the output.",
            SRC["marker"]))

    if not lens_preset:
        out.append(_warn(
            "Lens parameters are not pre-set; solving them during calibration worsens accuracy.",
            "Pre-set throw ratio, lens shift and zoom/FOV before calibrating.", SRC["marker"]))
    if is_3d and not model_from_scan:
        out.append(_warn(
            "The 3D model may not match the real object.",
            "Use a model that matches reality (ideally a 3D scan/photogrammetry).", SRC["marker"]))

    if reproj is not None:
        reproj = float(reproj)
        if reproj > _REPROJ_ERROR:
            out.append(_err(
                f"Re-Projection Error {reproj:.1f}px is high.",
                "Re-check lens params and 3D model; re-align outlier markers; add depth variation.",
                SRC["marker2"]))
        elif reproj > _REPROJ_WARN:
            out.append(_warn(
                f"Re-Projection Error {reproj:.1f}px exceeds the <1px (HD) target.",
                "Re-align edge markers and add corner/depth spread.", SRC["marker2"]))

    return out


# ------------------------------------------------------- canvas / feed mode
def validate_canvas_resolution(ctx: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    cw, ch = int(ctx.get("canvas_w", 0)), int(ctx.get("canvas_h", 0))
    pw, ph = int(ctx.get("projector_w", 0)), int(ctx.get("projector_h", 0))
    keep_square = bool(ctx.get("keep_square", True))

    if cw and pw and (cw < pw or ch < ph):
        out.append(_warn(
            f"Canvas {cw}x{ch} is below projector output {pw}x{ph} — content renders soft.",
            "Set Canvas Resolution to at least the projector's native resolution.",
            SRC["screen_size"]))
    if cw and ch and pw and ph:
        ca, pa = cw / ch, pw / ph
        if abs(ca - pa) / pa > 0.01:
            out.append(_warn(
                f"Canvas aspect {ca:.3f} differs from projector aspect {pa:.3f}.",
                "Match aspect ratios or expect letterboxing/stretching.", SRC["screen_size"]))
    if not keep_square:
        out.append(_info(
            "Non-square pixels are in use.",
            "Keep 'Keep Pixels as Squares' enabled unless non-square pixels are intentional.",
            SRC["screen_size"]))
    return out


def validate_feed_mode(ctx: dict[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    surface = str(ctx.get("surface_type", "flat")).lower()
    uv_continuous = bool(ctx.get("uv_continuous", True))
    feed_mode = str(ctx.get("feed_mode", "")).lower()

    if surface in ("3d", "object", "curved") and not uv_continuous and feed_mode != "none":
        out.append(_err(
            "Non-continuous UVs require Feed Mode 'None' to map correctly.",
            "Set Feed Mode to 'None' for this 3D surface.", SRC["uv"]))
    if surface == "flat" and feed_mode == "none":
        out.append(_warn(
            "Feed Mode 'None' on a flat surface usually yields black output.",
            "Use Fit / Stretch / Pixel Accurate for flat surfaces.", SRC["warp_softedge"]))
    return out
