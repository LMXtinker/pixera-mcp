# Pixera Native API — what is controllable vs UI-only

Critical for setting expectations. The API is JSON-RPC 2.0 over JSON/TCP(dl) (messages delimited by the
literal `0xPX`). Security is network-level only (choose adapter + port in Pixera settings; no auth token).

## Readable (live)

- **Projector:** `getProjectorNames`, `getProjectorWithName` → handle; `getPosition`, `getRotation`, `getBlackout`.
- **Utility:** `getApiRevision`, `getHasFunction(name)`, `getCurrentTime(AsString)`, `pollMonitoring`, `noop`.
- **Compound:** `getParamValue(path)`, `getCurrentTimeOfTimelineInSeconds(name)`.
- **Screens/Timelines:** `getScreenNames`, `getTimelines`/`getTimelineFromName`.

## Writable / actuating

- **Transport & cues (Compound):** `setTransportModeOnTimelineAtIndex/OnTimeline` (Play=1/Pause=2/Stop=3),
  `applyCueAtIndexOnTimelineAtIndex`, `applyCueNumberOnTimelineAtIndex`.
- **Projector:** `setPosition`, `setRotation`, `setBlackout`, `activateScreenMapping`.
- **Screen:** `setPosition/Rotation/Scale/PosRotScale`, `setIsVisible`, `setBlackout`,
  `setColorCorrectionAsJsonString`, `loadWarpFile`(+`WithDiff "mpcdi"`), `resetWarpFile`, `runCalibration(mode,diff)`, `triggerRefreshMapping`.
- **Calibration:** `Pixera.Calibration.setMarkerPositions(positions[], markerIds[])` (world space,
  no screen handle; applies to the marker calibration open in Pixera).
- **Resources:** `Compound.addResourceToFolder(namePath, filePath)`, `ResourceFolder.addResource`
  (OBJ becomes a `3DModel` resource),
  `addResourcesFromDirectory`, `Resource.replace`, `Resource.refresh`, live input
  `setVideoStreamMode(index)` + `LiveSystems.VideoStream.setActive`.
- **Timelines/layers:** `createTimeline`, `Timeline.createLayer/createCueLayer/createCue`
  (pass `cueLayerHandle: 0`), `Layer.assignResource(id)`, `setHomeScreenFromScreenName`,
  `setScaleUnitMode` (1 fill, 2 fit, 3 stretch, 4 resource, 5 3D object 1:1), `setRenderOnlyOnHomeScreen`, `get/setLayerJsonDescrip`.
- **Mappings:** `LiveSystem.exportMappings(path)` writes `service_<ip>/mapping_NNN.axp` (projector warp,
  soft edge, colour per projector-to-screen mapping); `importMappings(path, "1/1:1/2")` moves them to
  another output by idPath, empty string restores. Cannot create outputs or feeds.
- **Axes:** right-handed, Y-up, metres (confirmed live).
- **Session:** `loadProject`, `saveProject`, `saveProjectAs`, `shutdownSystem`.

## NOT available (UI-only / not exposed)

- ❌ Projector **lens/FOV/throw/shift** getters (write-only).
- ❌ **Mesh geometry** (vertices/faces) — parse the model file off disk instead.
- ❌ **Soft-edge** Shape/Gradient/Size/Dynamic params and blend black-level.
- ❌ Live **warp-grid point** editing.
- ❌ Reading existing **warp grids / calibration results / marker positions**.
- ❌ Creating **screens, projectors, LED walls, Art-Net/sACN outputs, feeds, fixtures** or a Live Input
  resource. (Assigning a 3D model to a layer **does** work: `Layer.assignResource` with a `3DModel`
  resource id, confirmed live on 26.1.)

## Consequences for this MCP server

- The view-cone recommender reads projector **pose live**, but needs **lens + mesh from you**; it cannot
  import existing warp.
- Soft-edge/warp/feed-mode tools are **advisory** (validate + guide), not actuating.
- Handles invalidate on project reload — the client clears its handle cache after `loadProject`.

## Method naming (rev 481, confirmed live on Pixera 26.1)

Class methods are class-qualified and take the object handle as a param:
`Pixera.Timelines.Timeline.setName {"handle": h, "name": "..."}`. Getters such as
`getScreenWithName` return a bare integer handle. Use `pixera_describe` to look up any signature.

Sources: rev481 API JSON (`api/pixera_api_rev481.json`); rev204 API comments; *API Commands*; *How to get and use handles*; *Direct API*.
