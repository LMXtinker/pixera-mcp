# View-Cone Marker Recommendation — methodology

How the `recommend_markers_for_projector` tool decides where markers should go, based on what each
projector actually sees of the mesh. The projector is modelled as an **inverse camera**.

## Inputs

- **Projector pose** — position + rotation, read **live** from the Pixera API (`getPosition`/`getRotation`).
- **Lens** — throw ratio (or FOV) + aspect + shift. The API does **not** expose lens data, so you supply it.
- **Mesh** — the surface model (OBJ/GLTF/…). The API does **not** expose geometry, so you supply the file.

> The API cannot read lens, mesh, or existing warp grids. Only pose is live. The recommendation is only
> as accurate as the lens spec and mesh you provide, and as the pose/mesh coordinate frames matching.

## Frustum

- `FOV_h = 2·atan(0.5 / throw_ratio)`, `FOV_v = 2·atan(tan(FOV_h/2) / aspect)`.
- The frustum is the projector's view cone: position (apex), forward/right/up basis, near/far, and the
  horizontal/vertical half-angles (with optional lens shift offsetting the axis).

## Culling pipeline (per face)

1. **Frustum cull** — keep faces whose centroid lies inside the cone.
2. **Back-face cull** — keep faces whose **outward normal points back toward the projector**
   (`dot(normal, view_dir) < 0`); a projector only lights faces turned toward it.
3. **Occlusion** *(optional)* — drop faces hidden by nearer geometry (ray test). O(n²); skipped on very large meshes.
4. **Grazing reject** — drop faces hit at a shallow incidence (default **> 75°** from the normal); those get
   stretched, low-resolution pixels and make poor, unstable markers.

## From visible faces → marker placement

- **Farthest-point sampling** over the visible face centroids → markers maximally **spread** across the visible patch.
- Report the **condition number** and **3D spread** of the chosen set; warn if the visible patch is
  near-coplanar (bad for 3D PnP) or too small/oblique.
- **VQI (Visibility Quality Index)** ∈ [0,1] = `visible_area_fraction × mean_incidence × (0.5 + 0.5·spread_3d)`.
  Low VQI flags a projector that can barely calibrate this mesh (too little visible, too oblique, or coplanar).

## Multi-projector

Compare each projector's visible set; faces visible to two projectors are good candidates for **shared
anchor markers** that keep adjacent projectors mutually consistent.

## Coordinate-frame caveat (integration risk)

Pixera returns rotation as Euler degrees with an unstated order/axis convention. `from_euler` uses a
documented default (intrinsic ZYX, forward +Z) that may need field tuning. If recommendations look
mirrored/rotated, check the rotation order and the mesh transform first — the visible-area fraction in
`score_projector_calibratability` is a quick sanity signal.

Sources: real-time rendering frustum/back-face culling; OpenCV pose; projector throw/FOV references.
