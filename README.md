# pixera-mcp

An MCP (Model Context Protocol) server for **AV Stumpfl Pixera** — a projection-mapping
**learning companion** and **marker-calibration advisor**, with a live-hybrid **view-cone marker
recommender**.

It speaks Pixera's Native API (JSON-RPC 2.0 over **JSON/TCP(dl)**, the literal `0xPX` delimiter) and
exposes three layers to an LLM:

1. **Knowledge + validation + recommendation (offline)** — teaches Pixera projection mapping, validates
   your parameters and tells you *what is wrong for the workflow*, and recommends calibration/warp strategy.
   Works with **no Pixera connection**.
2. **Live control + inspection** — the subset Pixera's API actually exposes (transport, cues, blackout,
   calibration triggers, marker writes, MPCDI load, project load/save, reads).
3. **Live-hybrid view-cone recommender** — reads a projector's **pose** live, then from a lens spec + mesh
   you supply, computes what that projector sees and recommends marker placement.

> See [`pixera_mcp_feasibility.md`](pixera_mcp_feasibility.md) for the full architecture, research, and risk report.

## Why offline-first

Pixera's API exposes projector **pose**, transport/cues, calibration *triggers* and marker *writes* — but
**not** soft-edge/blend parameters, live warp-grid editing, projector lens data, or mesh geometry. So the
biggest value is knowledge + validation + recommendation, which need no connection. Soft-edge/warp tools are
**advisory** (validate + guide), not actuating.

## Claude Desktop extension (recommended)

1. Download `pixera-mcp-<version>.mcpb` from the
   [latest release](https://github.com/LMXtinker/pixera-mcp/releases/latest).
2. Double-click it (or Claude Desktop > Settings > Extensions > Install extension).
3. Fill in the Pixera host and port. The extension then shows up with an on/off toggle.

Updates: on every start the extension checks the latest GitHub release and, if it is newer,
downloads the new code into a local cache (`%LOCALAPPDATA%\pixera-mcp\releases`). Offline it keeps
using the cached or bundled copy. A release that changes dependencies is not applied automatically;
the log then points to the new `.mcpb`. Switch updates off in the extension settings if a show
machine must not change.

The extension needs no Python install (Claude Desktop runs it with uv). For `pixera_describe` and
offline call validation, Pixera should be installed on the same machine, or set `PIXERA_API_JSON`.

### Publishing a release (maintainers)

1. Bump `version` in `pyproject.toml`, run the tests, commit and push.
2. `python tools/build_mcpb.py` (needs Node.js for `npx @anthropic-ai/mcpb`).
3. `git tag v<version> && git push origin v<version>`
4. `gh release create v<version> dist/pixera-mcp-<version>.mcpb --generate-notes`

Running extensions pick up the release on their next start. Only code changes are applied
automatically; if `dependencies` changed, teammates install the new `.mcpb` once.

## Install (Python package)

```bash
pip install -e .            # core (mcp<2, numpy)
pip install -e ".[mesh]"    # + trimesh for FBX/GLTF/PLY/STL meshes (OBJ works without it)
pip install -e ".[dev]"     # + pytest
```

## Configure Pixera (for live features)

In Pixera → **Settings → API**: add an API access port with protocol **JSON/TCP(dl)** on your chosen
network adapter and port (default here: `1500`). There is **no auth** in the protocol — run on a
trusted/isolated show LAN and firewall the port.

If every call fails with `{"code": -32602, "message": "Access is not authorized."}`, switch off
**Restrict Web Access To Actions That Match Allowlist** in Pixera's API settings (or allowlist the methods).

Tested live against Pixera 26.1 R39, API revision 481.

## Environment variables

| Var | Default | Meaning |
|---|---|---|
| `PIXERA_HOST` | `127.0.0.1` | Pixera host |
| `PIXERA_PORT` | `1500` | JSON/TCP(dl) port set in Pixera |
| `PIXERA_API_JSON` | local Pixera install | Pixera API JSON used by `pixera_describe` / `pixera_call` validation |
| `PIXERA_PROTECTED_PREFIXES` | `LE_` | Comma-separated timeline name prefixes that tools never remove or rename (empty = none) |
| `PIXERA_TIMEOUT` | `5.0` | per-request timeout (s) |
| `PIXERA_AUTOCONNECT` | `true` | connect on startup (offline tools still work if it fails) |

See [`.env.example`](.env.example).

## Connect it to an MCP client

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "pixera": {
      "command": "pixera-mcp",
      "env": { "PIXERA_HOST": "127.0.0.1", "PIXERA_PORT": "1500" }
    }
  }
}
```

**Claude Code:**

```bash
claude mcp add pixera --env PIXERA_HOST=127.0.0.1 --env PIXERA_PORT=1500 -- pixera-mcp
```

(`pixera-mcp` and `python -m pixera_mcp` are equivalent stdio entry points.)

## Raw API access and show setup (rev 481)

- **`pixera_describe(query)`** — offline lookup in Pixera's own API JSON. The file belongs to AV Stumpfl and
  is not shipped here: it is read from the local Pixera install (`<Program Files>/AV Stumpfl/Pixera/*/data/api/
  pixera_api.json`), or from `PIXERA_API_JSON`. Without it, `pixera_call` skips offline validation and relies on
  `getHasFunction`. A full name returns the
  signature and doc; a prefix like `Pixera.Timelines.Layer.` lists methods; a substring searches.
- **`pixera_call(method, params)`** — call any method. Before sending, it checks the method and params
  against the index (unknown names get "did you mean"), refuses destructive calls (remove/delete,
  load/save project, import mappings, engine stop) unless `allow_destructive=true`, never removes or renames
  protected timelines (name prefix from `PIXERA_PROTECTED_PREFIXES`, default `LE_`), and confirms the
  method with `getHasFunction`.
- **Inspect:** `pixera_list_screens_detailed` (pose, scale, visibility), `pixera_list_resources` (folder tree
  with ids), `pixera_find_resource`, `pixera_list_timelines_detailed` (layers with resource, model, home
  screen, scale mode), `pixera_get_layer_json`. Resource folder paths start at a top-level folder:
  `Media/Live Inputs`.
- **Setup:** `pixera_set_screen_pose` (Pixera-native metres/degrees, reads back), `pixera_import_resource`
  (file or directory; never removes), `pixera_create_timeline`, `pixera_setup_layer` (resource id, home
  screen, fill/fit, render only on home screen), `pixera_set_live_input` (stream mode + activate).

Method names follow rev 481: class methods are class-qualified and take `handle`, e.g.
`Pixera.Timelines.Timeline.setName {"handle": h, "name": "..."}`. The test mock validates every request
against the same index, so a wrong method string fails the tests.

Confirmed live (26.1): an imported OBJ becomes a `3DModel` resource, and `pixera_setup_layer(model_resource_id=...)`
puts it in the layer's model slot next to the media resource. Pixera is right-handed, Y-up, metres;
`pixera_set_screen_pose(convention="blender")` converts Blender positions `(x, y, z)` to `(x, z, -y)`.
`pixera_list_outputs` / `pixera_export_mappings` / `pixera_import_mappings` back up and move projector
mappings (warp, soft edge, colour) between outputs by idPath, e.g. `{"1/1": "1/2"}`.

Not possible over the API (rev 481): creating screens, projectors, LED walls, Art-Net/sACN outputs, feeds,
fixtures or Live Input resources; mapping files cannot create Art-Net outputs or feeds. See
[`docs/live_probes.md`](docs/live_probes.md) for probe results.

## The headline feature: marker recommendation

`pixera_recommend_markers_for_projector` reads the projector pose live and culls your mesh to what the
projector sees, then proposes markers. You supply the lens and mesh (the API can't):

```jsonc
// tool: pixera_recommend_markers_for_projector
{
  "projector_name": "Projector 1",
  "lens": { "throw_ratio": 1.2, "aspect": 1.7778, "shift_h": 0, "shift_v": 0, "resolution": [1920, 1080] },
  "mesh_path": "C:/show/object.obj",            // OBJ (built-in) or FBX/GLTF with [mesh] extra
  "mesh_transform": { "position": [0,0,0], "rotation": [0,0,0], "scale": [1,1,1] },
  "num_markers": 6,
  "grazing_deg": 75,
  "do_occlusion": false
}
```

Returns marker positions + ids, a **VQI** calibratability score, and warnings (too little visible / too
oblique / near-coplanar). Then `pixera_apply_markers(positions, marker_ids)` pushes them into Pixera via
`Pixera.Calibration.setMarkerPositions` (world space, no screen handle: it applies to the marker
calibration open in Pixera; you trigger the solve / Calculate there).

> Coordinate-frame note: Pixera returns rotation as Euler degrees with an unstated order. `euler_order`
> defaults to `ZYX` (forward +Z); if recommendations look mirrored/rotated, try a different order and check
> `mesh_transform`. `pixera_score_projector_calibratability` (visible-area %) is a quick sanity check.

## Reading warp data from a project file (`.avp`)

Pixera's API can't read warp grids, and VWF export needs a VIOSO licence — but the project **`.avp`
show-file** contains the warp. `pixera_import_warp_context(avp_path)` parses it **offline** and returns
projectors (model + pose), **FFD warp grids** (dims + control points + bbox), marker calibration sets, and
soft-edge presence. CLI: `python -m pixera_mcp.avp project.avp`. The `.avp` is a custom tagged-binary
format; this reader is reverse-engineered and **heuristic for Pixera build 26-1** (tags: `0x07` int32,
`0x0d` vec3<f64>, length-prefixed type names). Dev tools [`tools/avp_explore.py`](tools/avp_explore.py)
and [`tools/vwf_inspect.py`](tools/vwf_inspect.py) help re-derive the layout on other builds.

## What's inside

- **47 tools** — `describe` / `call` (raw rev481 API), show setup (screens, resources, timelines, layers,
  live input), `validate_*`, `recommend_*`, `diagnose`, `plan_projection_mapping`,
  `import_warp_context` (reads `.avp`); marker subsystem (`recommend_markers_for_projector`,
  `score_projector_calibratability`, `apply_markers`); live control + inspection.
- **Resources** — `pixera://guide/*` (PM 101, warping, softedge, marker calibration, calibration algorithms,
  view-cone methodology, camera calibration), `pixera://reference/*` (parameters, glossary, api-capabilities),
  and live `pixera://status|projectors|screens|timeline/{name}/time`.
- **Prompts** — marker-calibration walkthrough, calibration-strategy, projection-mapping setup, soft-edge
  setup, troubleshoot.

## Testing (no Pixera needed)

On Windows, keep the virtualenv outside OneDrive (OneDrive locks files inside `site-packages`), e.g.
`uv venv ~/.venvs/pixera-mcp` and `uv pip install --python ~/.venvs/pixera-mcp/Scripts/python.exe -e ".[dev]"`.

```bash
python -m pytest -q                     # full suite (framing, geometry, validation, integration)
python tests/test_framing.py            # or run a file directly (no pytest needed)
python tests/mock_pixera.py             # standalone mock on 127.0.0.1:1500
npx @modelcontextprotocol/inspector python -m pixera_mcp   # drive the server live (against the mock)
```

The mock speaks the real `0xPX` framing and canned responses, so the whole MCP↔TCP path is exercised
offline — including the live-hybrid marker recommender and the `setMarkerPositions` write.

## Project layout

```
src/pixera_mcp/
  client.py        0xPX framing, id-correlation, reconnect, handle + getHasFunction cache
  api_index.py     offline index of api/pixera_api_rev481.json (describe, call validation)
  tools_call.py    pixera_call guards (destructive, LE_ timelines, getHasFunction)
  tools_show.py    show setup: screens, resources, timelines, layers, live input
  geometry.py      frustum + cull pipeline + marker selection + VQI (numpy)
  meshio.py        mesh loader (trimesh / OBJ fallback)
  lens.py          LensSpec + FOV-from-throw
  validation.py    parameter rules ("what's wrong")
  tools_guidance.py  recommend_* / diagnose / plan (offline)
  tools_geometry.py  view-cone recommender (live-hybrid)
  tools_control.py / tools_inspect.py  live API tools
  resources.py / prompts.py / server.py  MCP wiring
  knowledge/*.md   bundled guides
tests/             framing, geometry, validation, integration, launcher + mock_pixera
mcpb/              Claude Desktop extension: manifest, self-updating launcher, icon
tools/build_mcpb.py  builds dist/pixera-mcp-<version>.mcpb
```

## Security

Pixera's API has no authentication: anyone who can reach the port can control Pixera. Keep the API
port on a trusted show network or VPN. The auto-update runs code from this repository's releases on
every machine with the extension, so only trusted maintainers should be able to push tags.

## License

MIT for this code. The Pixera API JSON (`pixera_api.json`) belongs to AV Stumpfl and is not included.
