"""Projector lens model.

Pixera's API does **not** expose projector lens/FOV/throw values (they are
write-only or UI-only), so the user must supply them for the view-cone
recommender. This module converts a throw ratio (the spec most commonly printed
on a projector/lens datasheet) into the field of view the frustum needs.

Relations used (projector modelled as an inverse pinhole camera):
    FOV_h = 2 * atan(0.5 / throw_ratio)          # throw_ratio = throw_dist / image_width
    FOV_v = 2 * atan(tan(FOV_h / 2) / aspect)
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class LensSpec:
    """A projector's optical parameters for frustum construction.

    Provide **either** ``throw_ratio`` **or** ``fov_h_deg``. ``aspect`` defaults
    to 16:9 but is derived from ``resolution`` when given. ``shift_h``/``shift_v``
    are optional lens shifts as a fraction of the half-image (0 = centred).
    """

    throw_ratio: float | None = None
    fov_h_deg: float | None = None
    aspect: float = 16.0 / 9.0
    shift_h: float = 0.0
    shift_v: float = 0.0
    resolution: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        if self.resolution is not None:
            w, h = self.resolution
            if h:
                self.aspect = w / h
        if self.throw_ratio is None and self.fov_h_deg is None:
            raise ValueError("LensSpec requires either throw_ratio or fov_h_deg")
        if self.throw_ratio is not None and self.throw_ratio <= 0:
            raise ValueError("throw_ratio must be positive")

    @property
    def horizontal_fov_deg(self) -> float:
        if self.fov_h_deg is not None:
            return self.fov_h_deg
        assert self.throw_ratio is not None
        return math.degrees(2.0 * math.atan(0.5 / self.throw_ratio))

    @property
    def vertical_fov_deg(self) -> float:
        h = math.radians(self.horizontal_fov_deg)
        return math.degrees(2.0 * math.atan(math.tan(h / 2.0) / self.aspect))

    @classmethod
    def from_dict(cls, data: dict) -> "LensSpec":
        """Build from a loosely-typed dict (e.g. MCP tool arguments)."""
        res = data.get("resolution")
        if isinstance(res, (list, tuple)) and len(res) == 2:
            res = (int(res[0]), int(res[1]))
        else:
            res = None
        return cls(
            throw_ratio=data.get("throw_ratio"),
            fov_h_deg=data.get("fov_h_deg"),
            aspect=float(data.get("aspect", 16.0 / 9.0)),
            shift_h=float(data.get("shift_h", 0.0)),
            shift_v=float(data.get("shift_v", 0.0)),
            resolution=res,
        )
