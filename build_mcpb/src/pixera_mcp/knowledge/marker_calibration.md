# Marker Calibration in Pixera (deep dive)

Marker calibration computes a projector's **pose** by matching markers you place on the virtual 3D
model with markers projected onto the real object. Pixera solves the pose that minimises the
**Re-Projection Error** (shown in the Inspector); you iterate via **Calculate** until it is low.

It is a **point-correspondence / PnP** solve: given ≥5 (ideally ≥6 non-coplanar) 2D↔3D
correspondences, find the projector position + orientation (and optionally refine intrinsics).

## Prerequisites (do these first — in order)

1. **Set/lock EDIDs.** If Windows re-enumerates displays, warping gets mixed up. This is the single
   most important prerequisite.
2. **Pre-set the lens** — throw ratio, lens shift, zoom/FOV. Letting the solver guess them worsens accuracy.
3. **Accurate 3D model** — it must match the real object, ideally a 3D scan/photogrammetry. Set its Role to *Screen*; import the UV map.
4. **Roughly place** the projector near its real-world position before solving.
5. **Activate the output** so projected markers are visible.

## Placing markers (the rules that matter)

- **Count:** Pixera advises **≥5**; for 3D pose use **6–8**. More, well-spread markers = more stable.
- **Position:** as far out as possible, **ideally in all corners** of the output.
- **Non-coplanar + depth-varied:** spread markers across different faces and depths. Coplanar markers
  cause a **2-fold pose ambiguity** (the solve oscillates between two valid poses). Collinear markers are singular.
- **Avoid grazing faces** (projector nearly parallel to surface) and **occlusion boundaries** —
  markers there are stretched/unstable. (The view-cone recommender picks faces that avoid both.)
- **Marker appearance (25.1+):** colour and size are adjustable (defaults: yellow, 48 px, 2 px thickness);
  2D/3D positions are editable directly in the Inspector.

## Reading the Re-Projection Error

- Target **< 1 px @ HD**. 0 = perfect.
- **Uniformly high** → lens params or model wrong.
- **High on edge markers only** → 3D model distorted / UV off.
- **Oscillating between two states** → markers coplanar; add depth variation.
- **One/two markers high** → re-align those (arrow keys for fine control).

## API hooks

- `setMarkerPositions(positions[], markerIds[])` — **writable**: push marker positions in (e.g. the
  MCP `apply_markers` tool). The solve (Calculate) is a UI action unless External-Marker-from-API mode auto-applies.
- `runCalibration(mode, diff)` — launches a calibration tool (`newCalib`/`autoRecalib`; e.g. `vioso`).
- Existing warp grids / marker positions / calibration results are **not readable** via the API.

See `pixera://reference/api-capabilities` and the algorithm taxonomy in `pixera://guide/calibration-algorithms`.

Sources: *Marker Calibration* + *Marker Calibration Workflow*; *Camera Based Calibration*; PIXERA 25.1 overview; rev204 API comments.
