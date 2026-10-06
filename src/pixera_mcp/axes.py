"""Axis conventions between Blender and Pixera.

Confirmed live on Pixera 26.1 (2026-10-06): Pixera world space is right-handed and
Y-up, in metres. Moving a screen along +X, +Y, +Z in the viewport showed
forward +X, up +Y, right +Z for a camera looking along +X, which is only
consistent with a right-handed frame.

Blender is right-handed and Z-up. The standard change of basis (the one Blender's
OBJ/glTF exporters use with "Y up") maps a Blender point ``(x, y, z)`` to Pixera
``(x, z, -y)``. This assumes the venue was modelled in Blender with the same
ground-plane orientation as the OBJ files Pixera uses as screen models, which is
true when those OBJs were exported from (or imported into) Blender with the
default Y-up setting.

Only positions are converted here. Pixera's Euler rotation order is not
confirmed, so rotations are left to the caller.
"""

from __future__ import annotations

from collections.abc import Sequence


def blender_to_pixera_position(p: Sequence[float]) -> list[float]:
    """Blender ``(x, y, z)`` (Z-up) to Pixera ``(x, y, z)`` (Y-up), both in metres."""
    x, y, z = (float(v) for v in p)
    return [x, z, -y]


def pixera_to_blender_position(p: Sequence[float]) -> list[float]:
    """Inverse of :func:`blender_to_pixera_position`."""
    x, y, z = (float(v) for v in p)
    return [x, -z, y]
