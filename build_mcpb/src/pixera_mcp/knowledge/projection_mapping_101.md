# Projection Mapping 101 in Pixera

A first-principles walkthrough of getting content onto a physical surface in AV Stumpfl Pixera.

## The pipeline (how a pixel reaches a wall)

```
Resources/Media → Layer (has a Home Screen) → Timeline → Screen (Canvas Resolution)
   → Mapping (Feed Areas · Warp · Soft Edge · Feed Mode) → Projector (pose · lens · output) → physical surface
```

- **Resources** — imported media (video/image/audio/3D models), stored as links to the original files.
- **Layer** — a container for media on the Timeline. Every layer has a **Home Screen** (its origin).
- **Timeline** — sequences layers; holds clips, keyframes, and **cues**.
- **Screen** — a virtual stand-in for the physical display; defines physical size (metres) and **Canvas Resolution** (the pixel resolution content renders at).
- **Mapping** — assigns projectors to the screen, divides the screen into **Feed Areas**, applies warping and soft edge.
- **Projector** — position/rotation/lens/output; projects the mapped feed.

## The three modes

| Mode | Purpose |
|---|---|
| **Screens** | Build the projection surfaces (flat screens, LED, 3D models). |
| **Mapping** | Place projectors, warp, soft edge, calibrate, assign outputs. |
| **Compositing** | Import and arrange content on the timeline; cues; playback. |

## Step-by-step (single flat projector)

1. **Project** — Settings → Project → New; name + save; press **G** for the grid.
2. **Screens** — add a *Generic Flat Screen*; set Width/Height (m); set **Canvas Resolution** to the projector's native resolution (e.g. 1920×1080).
3. **Mapping** — drag the projector from the Library; set position/rotation/lens (throw ratio, shift); **Ctrl+Alt+A** to auto-align; apply **FFD** warp to align corners; assign the output.
4. **Compositing** — import media; drag it onto the screen (this sets the layer's Home Screen); set Scale Unit Mode = *Resource Resolution*; add cues; **Space** to play.

## 2D vs 3D

- **2D / planar** — flat screens, walls, floors. Content maps directly via Feed Modes; no UV map.
- **3D** — domes, objects, sets. Import a 3D model, give it a **UV map**, set Feed Mode **None**, warp via **Vertex Modifier**, and align with **Marker Calibration**.

## Top beginner mistakes

- Canvas Resolution lower than the projector → soft image. Match the projector.
- Feed Mode **None** on a flat surface → black output. Use Fit/Stretch/Pixel Accurate.
- Content on the wrong **Home Screen** → renders on the wrong surface.
- Overlapping projectors without soft edge → a visible hard line.
- 3D object with non-continuous UVs but Feed Mode ≠ None → mis-mapped texture.

Sources: help.pixera.one 101 guides, *Warping, FeedModes and Softedge*, *Screens / Mapping / Compositing mode overviews*.
