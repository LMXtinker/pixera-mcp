# Warping in Pixera

Warping geometrically corrects the projected image so it lands correctly on the surface.

## Warp tools (and when to use each)

| Tool | Use case | Notes |
|---|---|---|
| **FFD Modifier** (Free-Form Deformer) | Most surfaces; screen-space correction | **Preferred.** Grid of control points; **Bezier** (default) or **Linear** interpolation; subdivisions double when expanded. |
| **Vertex Modifier** | Imported 3D models | Edits the mesh's own vertices (fixed by the model). |
| **Polygonal Warp** | Non-rectangular feeds | Switch Feed Type Rectangle→Polygonal; requires **Pixel-Accurate** feed. |
| **Multi-Pos Warp** | Virtual production / tracked camera | Saves per-viewpoint warps and blends between ≥3; overscan 1.05–1.2, uncheck *Scale Resolution*. |

## FFD workflow

1. Add screen + projector; **Ctrl+Alt+A** to auto-align.
2. Enable a test pattern.
3. Enter edit mode (**E**) → FFD Modifier (Project tab → screen → Mesh Modifiers → FFD).
4. Drag control points (arrow keys for precision; Shift = larger steps).
5. Choose interpolation: **Bezier** for curves (Linear can facet); toggle edge-point interpolation as needed.
6. Add subdivisions only where you need finer control (they double each time).

## Interpolation: Bezier vs Linear

- **Bezier** — smooth; correct for curved surfaces.
- **Linear** — straight segments between points; can show **faceting/banding** on curves.

## Common warp problems

- **Faceting on a curve** → switch to Bezier; add subdivisions.
- **Warp lost after rerouting a projector** → avoid unnecessary rerouting; set/lock **EDIDs** first.
- **Grid stretch/compression** of moving content → Pixera linearises the grid; keep control points evenly distributed.

## API note

Live editing of warp grid points is **not** exposed by the Native API. You can `loadWarpFile`
(including MPCDI) and `resetWarpFile`, and trigger calibration — but per-point warp editing is UI-only.
See `pixera://reference/api-capabilities`.

Sources: *Warping, FeedModes and Softedge*; *Edit Mesh*; *Polygonal Warp*; *Multi-Pos Warp*.
