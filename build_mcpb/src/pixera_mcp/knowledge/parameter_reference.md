# Pixera Parameter Reference

Numeric reference for mapping/warp/blend/calibration. Where AV Stumpfl does not publish exact ranges,
that is stated rather than guessed.

## Canvas / screen

| Parameter | Unit | Typical / rule |
|---|---|---|
| Canvas Resolution | px (W×H) | Match projector native (1920×1080, 3840×2160). Never below projector output. |
| Screen size | metres | Physical W/H/position (X,Y,Z); Y often = half-height for ground alignment. |
| Pixel aspect | ratio | Default 1:1 ("Keep Pixels as Squares"). |

## Projector / lens

| Parameter | Unit | Notes |
|---|---|---|
| Throw ratio | ratio | throw distance ÷ image width. `FOV_h = 2·atan(0.5/throw)`. |
| Lens shift | % of half-image | Offsets the optical axis. |
| Rotation | degrees | Euler; 180° common for inverted rigs. |
| Resolution | px | Native output. |

## Feed Mode

`None` (no scaling; for 3D/non-continuous UV) · `Fit` (preserve aspect) · `Stretch` (fill) ·
`Pixel Accurate` (1:1) · `Perspective`.

## Soft edge

| Parameter | Range | Notes |
|---|---|---|
| Horizontal overlap | ~**20%** ideal | Keep consistent across pairs. |
| Shape / Gradient / Size (static) | undocumented | AV Stumpfl does not publish ranges. |
| Dynamic: Smoothness/Gamma/Angle Weight/Distance Weight/Limit Angle/Limit Power | undocumented | Orientation = H/V/Both. |

## Warp

| Parameter | Notes |
|---|---|
| FFD interpolation | Bezier (default) or Linear. Bezier for curves. |
| FFD subdivisions | Double on expand. |
| Multi-Pos overscan | 1.05–1.2; uncheck *Scale Resolution*. |

## Marker calibration

| Parameter | Value |
|---|---|
| Marker count | ≥5 (Pixera min); 6–8 for 3D PnP |
| Placement | corners + edges, non-coplanar, depth-varied |
| Re-Projection Error target | < 1 px @ HD |
| Marker appearance (25.1+) | colour + size adjustable; defaults yellow, 48 px, 2 px |
| Grazing-angle threshold (recommender) | ~75° from normal |

## Transport mode enum

`Play = 1`, `Pause = 2`, `Stop = 3` (used by `setTransportModeOnTimeline...`).
