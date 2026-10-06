# Camera-Based Calibration (VIOSO) in Pixera

Automated projector calibration using a camera and structured-light patterns — best for curved/large
surfaces and many projectors.

## What it is

VIOSO 6 (bundled with Pixera 2.0.14x+) projects test/structured-light patterns, captures them with one or
more cameras, and computes warp + soft edge automatically (**structured light + bundle adjustment**).
Accuracy is typically sub-pixel.

## When to prefer it over manual markers

| Scenario | VIOSO | Manual markers |
|---|---|---|
| Single flat surface | overkill | ✓ fast |
| Curved / dome | ✓ essential | hard |
| Many projectors (5+) | ✓ practical | tedious |
| Sub-pixel accuracy | ✓ | depends on point count |

## Workflow

1. Ensure the licence includes VIOSO.
2. Set Screen to **"Texture per Screen"**; choose an empty calibration directory.
3. **Launch new Calibration**; pick the camera (Daheng supported); set inspector values.
4. Choose a **2D** or **3D Surface** profile. For 3D models set **Scale Factor 1000** (VIOSO works in mm, Pixera in m).
5. Calibrate — patterns are projected and analysed; results distribute to Director + clients.
6. Optionally use **autoRecalib** for automated re-calibration via Pixera Control.

## Prerequisites / gotchas

- **Set EDIDs first** (as with marker calibration).
- The camera must see the whole surface; lens distortion in the camera propagates to warp error.
- VIOSO 5 support ended 2024-12-31; `.vwf` files are forward-compatible.

## API hooks

`runCalibration("newCalib"|"autoRecalib", "vioso")`, `editCalibration`, `loadWarpFile(...,"mpcdi")`.
Calibration results are not readable back via the API.

Sources: Pixera *Camera Based Calibration*, *VIOSO 6*, *Vioso Camera Kit (Daheng)*; VIOSO docs.
