# Soft Edge / Edge Blending in Pixera

Soft edge blends the overlap between adjacent projectors so the seam disappears.

## Where it lives

Projector Inspector → **Softedge** tab (next to the Warp tab). Two ways to create it:

- **Generate Auto Softedge** — requires **Feed Areas enabled** first; Pixera computes warped blend masks from projector + screen geometry.
- **Manual** — the **+** button adds a softedge element you shape by hand.
- **Dynamic Softedge** — engine-side, for 3D/moving surfaces (not shown in the static Softedge tab).

## Parameters

Static softedge exposes **Shape**, **Gradient**, **Size** (AV Stumpfl does not publish exact numeric ranges).
Dynamic Softedge exposes:

| Parameter | Effect |
|---|---|
| **Smoothness** | Longer fade = covers more of the output. |
| **Gamma** | Lower = darker fade from the edge. |
| **Angle Weight** | Shifts fade weight toward the angle between outputs. |
| **Distance Weight** | Pushes the full-black edge farther from the seam. |
| **Limit Angle / Limit Power** | Curve the blend edge instead of a flat line. |
| **Orientation** | Horizontal / Vertical / Both. |

## Recommended values

- **~20% horizontal overlap** is the documented "ideal" for a stable blend.
- Keep overlap **consistent** across adjacent pairs — mismatched widths cause visible seams.
- Match blend gamma/curve across the pair.

## Workflow (static, feed-mode based)

1. Add screen + projectors; set lens/throw/zoom per projector.
2. **Select ALL projectors**; set **Feed Areas** (Fit/Stretch/Pixel-Accurate); adjust the softedge value for ~20% overlap.
3. **Ctrl+Alt+A** to auto-align each projector.
4. **Generate Auto Softedge**.
5. Fine-tune Shape/Gradient/Size; "Dive" into pixel space for precise alignment.
6. If screen black edges show, tick **Clear Softedge All Visible**.

## Black level in overlaps

Pixera has no single "black level uplift" slider. Use **Clear Softedge All Visible**, the Dynamic
**Gamma**, and per-output **color calibration** to manage lifted blacks in the overlap.

## Common mistakes

- Not selecting **all** projectors before changing Feed Mode → setting applies to one.
- Using **Generate Auto Softedge** without Feed Areas → nothing to calculate.
- Mismatched overlap % between pairs → seams.

## API note

Soft-edge parameters are **UI-only** — not controllable via the Native API. The MCP server
**validates and guides** soft-edge setup; it cannot set blend values. See `pixera://reference/api-capabilities`.

Sources: *Softedge Creation*; *Warping, FeedModes and Softedge*; *Projector Feed Areas*.
