# Calibration Algorithms — which one for which use case

| Method | Min points | Surface | Accuracy | Best for | Fails when |
|---|---|---|---|---|---|
| **Planar homography** (DLT) | 4 coplanar | flat | ±0.5–2 px | flat screens, quick setup | points collinear / non-planar surface |
| **PnP / DLT** (3D pose) | **6 non-coplanar** | any 3D | ±1–5 px | objects, domes, **Pixera Marker Calibration** | coplanar (2-fold ambiguity); collinear (singular) |
| **PnP + bundle adjustment** | 8+ | any | ±0.5 px | high-precision multi-projector | poor initialisation |
| **Structured light** (VIOSO) | dense (auto) | curved/large | ±0.2–0.5 px | domes, many projectors, automation | needs camera + controlled light |
| **MPCDI import** | n/a | any | as-calibrated | external/vendor interop | no on-site refinement |

## Decision shortcut

- **Flat + 1 projector** → planar homography (4 corner points). Fastest.
- **3D object / dome + 1 projector, no camera** → PnP **Marker Calibration** (≥6 non-coplanar).
- **Many projectors / curved / sub-pixel + a camera** → **VIOSO** structured light.
- **High precision** → PnP **plus** bundle-adjustment refinement.
- **Calibration done elsewhere** → import **MPCDI**.

## The coplanarity / degeneracy rule (why it matters)

A full 3D projector pose has **6 DoF**. Each 2D↔3D marker gives 2 constraints, so ≥6 points overdetermine it.
But if the points are **coplanar**, two distinct poses reproject identically → the solve **oscillates**
(2-fold ambiguity). If they are **collinear**, the system is **singular** (no solution).

**Therefore:** spread markers across **different faces and depths** so they are non-coplanar, and never
place them all on one edge/plane. Good distribution (corners + depth variation) also lowers the solution's
**condition number**, making it robust to placement noise.

## Accuracy expectations

±-pixel figures above are typical from the projector-calibration literature; Pixera/VIOSO do not publish
hard tolerances. Real accuracy depends on point count/spread, model fidelity, and lens-parameter accuracy.

Sources: OpenCV solvePnP/homography docs; projector-calibration literature; VIOSO docs; Pixera Marker/Camera calibration pages.
