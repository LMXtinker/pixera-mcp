# Live probes (Pixera 26.1, API rev 481)

These questions decide how much of a Pixera show setup can run without UI work.
They cannot be answered offline. Run [`tools/probe_rev481.py`](../tools/probe_rev481.py) against a
running Pixera and record the answers here.

Rules: write probes only on a scratch project (the script checks `Session.getProjectName`).
Never save. Never touch `LE_*` timelines.

## How to run

1. Open Pixera with a scratch project, for example `scratch_probe`. API port JSON/TCP(dl) on 1500,
   allowlist restriction off.
2. In the scratch project, drag a 3D model onto one layer by hand (input for probe B).
3. Read phase (safe on any project):

   ```bash
   python tools/probe_rev481.py --port 1500 --out probe_out
   ```

4. Write phase:

   ```bash
   python tools/probe_rev481.py --port 1500 --out probe_out --write --scratch-project scratch_probe --obj C:/path/screen.obj
   ```

   Add `--import-mappings` to re-import the exported mappings (probe C round trip).

## Questions and results

First run: 2026-10-06, Pixera 26.1 R39, API rev 481, on a show prototype project cleared for edits
(14 custom screens, 8 projectors). All probe objects were removed afterwards; the project was not saved.

| Probe | Question | Result |
|---|---|---|
| A | Does `ResourceFolder.addResource` accept an OBJ and create a model resource? | **Yes.** `addResource(handle=<Models folder>, path=<file>.obj)` returns a resource handle; `getType` = `3DModel`, `getResolution` = `[0, 0]`, `getId` equals the handle. |
| B | Can a layer get a 3D model over the API? | **Yes, with `Layer.assignResource(id=<3DModel id>)`.** It fills the model slot (`getAssignedModelResource`) and leaves the media resource (`getAssignedResource`) alone, so one layer carries both. `resetAssignedModelResource` clears it. `getLayerJsonDescrip` has no model field (`Media`, `Opacity`, `Position`, `Rotation`, `Size`, `Transport`, `Volume`, `mute`, `muteAudio`), so the JSON route is not needed. |
| C1 | What does `LiveSystem.exportMappings(path)` write? | A folder `service_<ip>/original_output_structure.json` with the output structure only (graphics devices and outputs with resolution/fps/idPath, video devices and streams). Same content as `LiveSystem.getStructureJson`. `exportMappingsDirectly(path)` writes the same file without the `service_<ip>` folder. No mapping data was written because no output on this machine has a projector or screen assigned. |
| C1b | Export with a projector assigned to Output 1 | `service_<ip>/mapping_001.axp` … `mapping_004.axp`, one per projector-to-screen mapping on that output. Each `.axp` starts with `MuExport`, then a JSON header (`creatorSig` = projector, `parentScreenSig` = screen, `outputSigPath` = `Graphics Card 1/Output 1`, `altRecgn` with output id `<ip> gdi: 1 oid: 1`), then the same tagged-binary body as `.avp`: FFD/vertex/path warp modifiers, soft edge, material, color correction. |
| C2 | Does `importMappings` accept the exported files? What is `outputIdPathMapStr`? | **Yes.** Empty string: each mapping goes back to the output it was exported from. `"1/1:1/2"` (source output idPath `:` target idPath) **moved** the projector and its mappings from Output 1 to Output 2 (Output 1 empty afterwards). Restored with an empty-string import. Several pairs: separator not confirmed. |
| C3 | Can a generated mapping file create feeds or outputs? | **No (not practical).** `.axp` files carry projector warp/soft-edge/colour data for an existing projector-to-output assignment, not Art-Net outputs or feeds, and the body is undocumented binary. Use import/export to move or back up projector mappings; Art-Net outputs and feeds still need the UI (CSV or MVR import). |
| D | Axis convention | **Right-handed, Y-up, metres.** All 8 projectors hang at y = 13.0 m. Viewport test (computer use): moving a stage screen by +4 m on X moved it away from a camera looking along the hall, +4 m on Z moved it right, +3 m on Y moved it up; forward × up = right holds only for a right-handed frame. Blender `(x, y, z)` maps to Pixera `(x, z, -y)` (`axes.py`). Euler rotation order still unknown. |

Other live findings:

- `getResourceFolderWithNamePath` takes paths from a top-level folder with `/` or `.` as separator
  (`Media/Live Inputs`); an unknown path returns `0`, not an error.
- Screen names need not be unique (one test project had the same screen name twice). Name-based calls
  (`getScreenWithName`, `setHomeScreenFromScreenName`) are then ambiguous.
- `Layer.setScaleUnitMode` has 5 modes: 1 fill, 2 fit, 3 stretch, 4 resource resolution, 5 used 3D object 1:1.
- Methods documented as returning `null` return `1` live.
- `setPosRotScale` round trip is exact (set, read back, restore).
- The Live Input resources in this project report no stream modes (`getVideoStreamModes` = `[]`).

## Remaining UI steps

Over the API the setup can now: import screen OBJs as `3DModel` resources, build timelines and layers
with media and model, set screen poses (from Blender positions too), and move or restore projector
mappings between outputs. Still UI-only:
custom screen model import (Screens > Library > Custom > '+'), Art-Net/sACN outputs from CSV, feeds
from CSV or MVR (Pixera help articles 1005618, 2536197, 3023924, 2318485).
