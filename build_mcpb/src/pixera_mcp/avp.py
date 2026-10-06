"""Best-effort reader for AV Stumpfl Pixera ``.avp`` show-files.

Pixera does not expose warp/calibration data over its API and (without a VIOSO
licence) cannot export VWF. The ``.avp`` project file, however, contains it. The
format is an undocumented tagged-binary tree; this module reverse-engineers just
enough to extract a **mapping/warp context summary**: projectors (model + pose),
FFD warp modifiers (grid dims + control points), marker calibration sets, and
soft-edge presence.

Decoded tag scheme (observed, Pixera build 26-1):
- length-prefixed ASCII tokens ``<len:1><name>`` carry type/field names
- ``0x07`` + 4 bytes  -> int32
- ``0x0d`` + 24 bytes -> vec3 of float64 (a 3D point: position/rotation/scale/control point/marker)
- ``0x40`` + 4 bytes  -> nested-object header

This is heuristic and version-dependent. Values are reported with that caveat.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import Any

TAG_INT32 = 0x07
TAG_VEC3 = 0x0D
TAG_OBJECT = 0x40

# Type-name anchors we care about (exact length-prefixed tokens).
_ANCHORS = ["Project", "Projector", "ObjectBaseTransform", "FFD Modifier", "ModifierFFD",
            "Vertex Modifier", "ScreenMarkerSet", "MarkerCalibrationProperties",
            "SoftedgeWarp", "Softedge Warped", "Softedge Screen Aligned", "CmappingScreenHolder"]
_MODEL_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-]{3,}$")  # e.g. PT-RQ18K
_BUILD_RE = re.compile(rb"build_([0-9A-Za-z_\-]+)/pixera\.exe")
_COORD_LIMIT = 1e7


def _find_all(data: bytes, name: str) -> list[int]:
    pat = bytes([len(name)]) + name.encode()
    offs, i = [], 0
    while True:
        j = data.find(pat, i)
        if j < 0:
            return offs
        offs.append(j)
        i = j + 1


def _tokens_in(data: bytes, start: int, end: int, lo: int = 3, hi: int = 40) -> list[str]:
    out, i = [], start
    while i < end:
        L = data[i]
        if lo <= L <= hi and i + 1 + L <= len(data):
            tok = data[i + 1:i + 1 + L]
            if re.match(rb"^[A-Za-z0-9_./: +-]+$", tok):
                out.append(tok.decode("ascii"))
                i += 1 + L
                continue
        i += 1
    return out


def _collect_values(data: bytes, start: int, end: int) -> tuple[list[int], list[tuple]]:
    """Decode int32 / vec3<f64> in [start, end), descending through nested objects."""
    ints, vecs, i = [], [], start
    while i < end:
        t = data[i]
        if t == TAG_VEC3 and i + 25 <= end:
            v = struct.unpack_from("<3d", data, i + 1)
            if all(abs(x) < _COORD_LIMIT or x == 0.0 for x in v):
                vecs.append(tuple(round(x, 5) for x in v))
            i += 25
        elif t == TAG_INT32 and i + 5 <= end:
            ints.append(struct.unpack_from("<i", data, i + 1)[0])
            i += 5
        elif t == TAG_OBJECT:
            i += 5  # skip object header, keep descending
        else:
            i += 1
    return ints, vecs


def _bbox(vecs: list[tuple]) -> dict | None:
    if not vecs:
        return None
    xs, ys, zs = zip(*vecs)
    return {"min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]}


def _windows(offsets: list[int], boundaries: list[int], max_span: int) -> list[tuple[int, int]]:
    out = []
    for o in offsets:
        nxt = min([b for b in boundaries if b > o] + [o + max_span])
        out.append((o, min(nxt, o + max_span)))
    return out


def extract_warp_context(path: str | Path, max_span: int = 20000) -> dict[str, Any]:
    """Parse a .avp and return a mapping/warp context summary (best-effort)."""
    data = Path(path).read_bytes()
    all_anchor_offsets = sorted({o for a in _ANCHORS for o in _find_all(data, a)})

    build = _BUILD_RE.search(data)
    result: dict[str, Any] = {
        "file": str(path),
        "size_bytes": len(data),
        "pixera_build": build.group(1).decode() if build else None,
        "projectors": [],
        "ffd_modifiers": [],
        "marker_sets": [],
        "softedge": {},
        "notes": [
            "Heuristic read of an undocumented .avp format (Pixera build 26-1). "
            "vec3 values are float64 triples tagged 0x0d; some may be frame/basis "
            "vectors rather than control points. Treat as context, not ground truth.",
        ],
    }

    # Projectors: model name + ObjectBaseTransform (position/rotation/scale).
    # ObjectBaseTransform is itself an anchor, so scan a fixed forward span here
    # (the anchor-clipped window would stop right before it).
    for o in _find_all(data, "Projector"):
        seg = min(len(data), o + 1200)
        toks = _tokens_in(data, o + len("Projector") + 1, seg)
        model = next((t for t in toks if _MODEL_RE.match(t)), None)
        brand = next((t for t in toks if t in ("Panasonic", "Barco", "Epson", "Christie",
                                               "NEC", "Sony", "Digital Projection")), None)
        obt = _find_all(data[o:seg], "ObjectBaseTransform")
        pose = {}
        if obt:
            s = o + obt[0] + len("ObjectBaseTransform") + 1
            _, vecs = _collect_values(data, s, s + 120)
            if len(vecs) >= 3:
                pose = {"position": list(vecs[0]), "rotation": list(vecs[1]), "scale": list(vecs[2])}
        result["projectors"].append({"model": model, "brand": brand, "pose": pose})

    # FFD modifiers: grid dims + control points.
    for o, end in _windows(_find_all(data, "FFD Modifier"), all_anchor_offsets, max_span):
        ints, vecs = _collect_values(data, o + len("FFD Modifier") + 1, end)
        dims = ints[:3] if len(ints) >= 3 else ints
        result["ffd_modifiers"].append({
            "grid_dims": dims,
            "value_count": len(vecs),
            "control_points_sample": [list(v) for v in vecs[:8]],
            "bbox": _bbox(vecs),
        })

    # Marker calibration sets.
    marker_offs = _find_all(data, "MarkerCalibrationProperties") or _find_all(data, "ScreenMarkerSet")
    for o, end in _windows(marker_offs, all_anchor_offsets, max_span):
        _, vecs = _collect_values(data, o, end)
        result["marker_sets"].append({
            "marker_point_count": len(vecs),
            "points_sample": [list(v) for v in vecs[:12]],
            "bbox": _bbox(vecs),
        })

    # Soft edge presence (parameters themselves are not in a documented form).
    se_types = {}
    for name in ("SoftedgeWarp", "Softedge Warped", "Softedge Screen Aligned"):
        c = len(_find_all(data, name))
        if c:
            se_types[name] = c
    result["softedge"] = {"present": bool(se_types), "types": se_types}

    return result


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) != 2:
        print("usage: python -m pixera_mcp.avp path/to/project.avp")
        raise SystemExit(2)
    print(json.dumps(extract_warp_context(sys.argv[1]), indent=2))
