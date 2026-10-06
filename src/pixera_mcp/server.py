"""FastMCP server wiring: lifespan, tool/resource/prompt registration, entrypoint.

Offline tools (knowledge, validation, recommendation) always work. Live tools
(control, inspection, the view-cone recommender) use the persistent
:class:`PixeraTCPClient`; if Pixera is unreachable they raise a clear,
actionable error rather than failing silently.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from .client import PixeraError, PixeraTCPClient
from .config import Settings
from .runtime import Runtime
from . import tools_call as tcall
from . import tools_control as tc
from . import tools_geometry as tg
from . import tools_inspect as ti
from . import tools_show as ts
from . import validation as V
from .prompts import register_prompts
from .resources import register_resources
from .tools_guidance import (
    diagnose, plan_projection_mapping, recommend_calibration_method, recommend_warp_method,
)


def build_server():
    from mcp.server.fastmcp import FastMCP

    settings = Settings.from_env()
    runtime = Runtime(settings)

    @asynccontextmanager
    async def lifespan(_server):
        client = PixeraTCPClient(settings)
        runtime.client = client
        if settings.autoconnect:
            try:
                await client.connect()
            except PixeraError:
                pass  # stay up offline; live tools report the connection error on use
        try:
            yield {"runtime": runtime}
        finally:
            await client.close()

    mcp = FastMCP("pixera-mcp", lifespan=lifespan)
    register_resources(mcp, runtime)
    register_prompts(mcp)
    _register_tools(mcp, runtime)
    return mcp


def _register_tools(mcp, runtime: Runtime) -> None:
    client = runtime.require_client  # callable -> connected client (or raises)

    # ----------------------------------------------------- offline: guidance
    @mcp.tool()
    def pixera_recommend_calibration_method(
        surface_type: str, projector_count: int = 1, accuracy_need: str = "standard",
        time_budget: str = "normal", has_camera: bool = False,
    ) -> dict[str, Any]:
        """Recommend a calibration approach (homography / PnP markers / VIOSO / MPCDI) for a scenario."""
        return recommend_calibration_method(surface_type, projector_count, accuracy_need,
                                            time_budget, has_camera)

    @mcp.tool()
    def pixera_recommend_warp_method(
        surface_type: str = "flat", has_3d_model: bool = False, curved: bool = False,
        tracked: bool = False, non_rectangular: bool = False,
    ) -> dict[str, Any]:
        """Recommend a warp tool: FFD vs Vertex vs Polygonal vs Multi-Pos, with rationale."""
        return recommend_warp_method(surface_type, has_3d_model, curved, tracked, non_rectangular)

    @mcp.tool()
    def pixera_diagnose(symptom: str) -> dict[str, Any]:
        """Diagnose a projection-mapping symptom (e.g. 'visible seam', 'black output') -> cause + fix."""
        return diagnose(symptom)

    @mcp.tool()
    def pixera_plan_projection_mapping(
        surface_type: str = "flat", projector_count: int = 1, content_type: str = "video",
        curved: bool = False, tracked: bool = False,
    ) -> dict[str, Any]:
        """Produce an ordered, scenario-tailored Pixera setup plan (Screens -> Mapping -> Compositing)."""
        return plan_projection_mapping(surface_type, projector_count, content_type, curved, tracked)

    @mcp.tool()
    def pixera_import_warp_context(avp_path: str) -> dict[str, Any]:
        """Parse a Pixera .avp show-file (offline) and summarize the mapping/warp context.

        Returns projectors (model + pose), FFD warp modifiers (grid dims + control points),
        marker calibration sets, and soft-edge presence read straight from the project file -
        warp data the Native API cannot expose. Heuristic for Pixera build 26-1.
        """
        from .avp import extract_warp_context
        return extract_warp_context(avp_path)

    # ----------------------------------------------------- offline: validation
    @mcp.tool()
    def pixera_validate_softedge(
        projector_count: int, overlaps: list[float] | None = None, feed_areas_enabled: bool = True,
        feed_mode: str = "fit", surface_type: str = "flat", dynamic_softedge: bool = False,
        all_projectors_selected: bool = True,
    ) -> dict[str, Any]:
        """Validate a soft-edge/blend setup and flag what is wrong for the workflow."""
        return V.summarize(V.validate_softedge({
            "projector_count": projector_count, "overlaps": overlaps or [],
            "feed_areas_enabled": feed_areas_enabled, "feed_mode": feed_mode,
            "surface_type": surface_type, "dynamic_softedge": dynamic_softedge,
            "all_projectors_selected": all_projectors_selected}))

    @mcp.tool()
    def pixera_validate_marker_calibration(
        marker_count: int, surface_type: str = "3d", coplanar: bool = False,
        depth_varied: bool = True, placement: str = "corners", lens_preset: bool = True,
        edids_set: bool = True, model_from_scan: bool = True,
        reprojection_error: float | None = None,
    ) -> dict[str, Any]:
        """Validate marker-calibration parameters (count, coplanarity, EDID/lens prereqs, error)."""
        return V.summarize(V.validate_marker_calibration({
            "marker_count": marker_count, "surface_type": surface_type, "coplanar": coplanar,
            "depth_varied": depth_varied, "placement": placement, "lens_preset": lens_preset,
            "edids_set": edids_set, "model_from_scan": model_from_scan,
            "reprojection_error": reprojection_error}))

    @mcp.tool()
    def pixera_validate_canvas_resolution(
        canvas_w: int, canvas_h: int, projector_w: int, projector_h: int, keep_square: bool = True,
    ) -> dict[str, Any]:
        """Validate Canvas Resolution vs projector output (resolution + aspect)."""
        return V.summarize(V.validate_canvas_resolution({
            "canvas_w": canvas_w, "canvas_h": canvas_h, "projector_w": projector_w,
            "projector_h": projector_h, "keep_square": keep_square}))

    @mcp.tool()
    def pixera_validate_feed_mode(
        surface_type: str, feed_mode: str, uv_continuous: bool = True,
    ) -> dict[str, Any]:
        """Validate Feed Mode choice for a surface (e.g. 'None' only for 3D/non-continuous UV)."""
        return V.summarize(V.validate_feed_mode({
            "surface_type": surface_type, "feed_mode": feed_mode, "uv_continuous": uv_continuous}))

    # ------------------------------------------------ live-hybrid: geometry
    @mcp.tool()
    async def pixera_recommend_markers_for_projector(
        projector_name: str, lens: dict, mesh_path: str, mesh_transform: dict | None = None,
        num_markers: int = 6, grazing_deg: float = 75.0, do_occlusion: bool = False,
        euler_order: str = "ZYX",
    ) -> dict[str, Any]:
        """Read the projector pose live, cull the mesh to what it sees, and recommend marker placement.

        lens: {throw_ratio | fov_h_deg, aspect, shift_h, shift_v, resolution:[w,h]}.
        mesh_path: OBJ/GLTF/... on disk. mesh_transform: optional {position, rotation, scale} to
        place the mesh in world coordinates. Requires a live Pixera connection.
        """
        return await tg.recommend_markers_for_projector(
            client(), projector_name, lens, mesh_path, mesh_transform, num_markers,
            grazing_deg, do_occlusion, euler_order)

    @mcp.tool()
    async def pixera_score_projector_calibratability(
        projector_name: str, lens: dict, mesh_path: str, mesh_transform: dict | None = None,
        grazing_deg: float = 75.0, euler_order: str = "ZYX",
    ) -> dict[str, Any]:
        """Score how calibratable a mesh is from a projector (VQI + breakdown). Requires a live connection."""
        return await tg.score_projector_calibratability(
            client(), projector_name, lens, mesh_path, mesh_transform, grazing_deg, euler_order)

    @mcp.tool()
    async def pixera_apply_markers(
        positions: list[float], marker_ids: list[int], screen_name: str | None = None,
    ) -> dict[str, Any]:
        """Push world-space markers via Pixera.Calibration.setMarkerPositions (positions = flat x,y,z).

        Applies to the marker calibration open in Pixera; the API takes no screen handle.
        """
        return await tg.apply_markers(client(), screen_name, positions, marker_ids)

    # ------------------------------------------------------------ live: control
    @mcp.tool()
    async def pixera_get_api_revision() -> dict[str, Any]:
        """Return the Pixera Native API revision (even=release, odd=beta)."""
        return await tc.get_api_revision(client())

    @mcp.tool()
    async def pixera_ping() -> dict[str, Any]:
        """Liveness check: API revision + noop round-trip."""
        return await tc.ping(client())

    @mcp.tool()
    async def pixera_has_function(name: str) -> dict[str, Any]:
        """Probe whether the connected Pixera supports an API function."""
        return await tc.has_function(client(), name)

    @mcp.tool()
    async def pixera_set_timeline_transport(timeline_index: int, action: str) -> dict[str, Any]:
        """Play/Pause/Stop a timeline by index (action: 'play'|'pause'|'stop')."""
        return await tc.set_timeline_transport(client(), timeline_index, action)

    @mcp.tool()
    async def pixera_set_timeline_transport_by_name(timeline_name: str, action: str) -> dict[str, Any]:
        """Play/Pause/Stop a timeline by name (action: 'play'|'pause'|'stop')."""
        return await tc.set_timeline_transport_by_name(client(), timeline_name, action)

    @mcp.tool()
    async def pixera_apply_cue(timeline_index: int, cue_index: int) -> dict[str, Any]:
        """Fire a cue by index on a timeline by index (zero-based)."""
        return await tc.apply_cue(client(), timeline_index, cue_index)

    @mcp.tool()
    async def pixera_apply_cue_by_number(timeline_index: int, cue_number: int) -> dict[str, Any]:
        """Fire a cue by its cue number on a timeline by index."""
        return await tc.apply_cue_by_number(client(), timeline_index, cue_number)

    @mcp.tool()
    async def pixera_set_projector_blackout(projector_name: str, on: bool) -> dict[str, Any]:
        """Blackout (or restore) a projector by name."""
        return await tc.set_projector_blackout(client(), projector_name, on)

    @mcp.tool()
    async def pixera_run_calibration(screen_name: str, mode: str = "newCalib",
                                     tool: str = "vioso") -> dict[str, Any]:
        """Launch a calibration tool for a screen (mode 'newCalib'|'autoRecalib', tool e.g. 'vioso')."""
        return await tc.run_calibration(client(), screen_name, mode, tool)

    @mcp.tool()
    async def pixera_load_warp_file(screen_name: str, path: str, mpcdi: bool = True) -> dict[str, Any]:
        """Load a warp file (MPCDI by default) onto a screen."""
        return await tc.load_warp_file(client(), screen_name, path, mpcdi)

    @mcp.tool()
    async def pixera_load_project(path: str) -> dict[str, Any]:
        """Load a Pixera project (replaces the current project; clears the handle cache)."""
        return await tc.load_project(client(), path)

    @mcp.tool()
    async def pixera_save_project() -> dict[str, Any]:
        """Save the current Pixera project."""
        return await tc.save_project(client())

    @mcp.tool()
    async def pixera_refresh_mapping(screen_name: str) -> dict[str, Any]:
        """Trigger a mapping refresh on a screen."""
        return await tc.refresh_mapping(client(), screen_name)

    # ------------------------------------------------------- raw API access
    @mcp.tool()
    def pixera_describe(query: str, limit: int = 40) -> dict[str, Any]:
        """Look up Pixera API methods offline (rev 481 API JSON). No connection needed.

        query: a full method name (returns signature + doc), a prefix such as
        'Pixera.Timelines.Layer.' (lists methods), or a substring such as 'VideoStream'.
        Class methods take the object handle as params.handle. Use before pixera_call.
        """
        return tcall.describe(query, limit)

    @mcp.tool()
    async def pixera_call(
        method: str, params: dict | None = None, allow_destructive: bool = False,
        validate: bool = True,
    ) -> dict[str, Any]:
        """Call any Pixera API method, e.g. method='Pixera.Screens.Screen.setIsVisible',
        params={'handle': 123, 'isVisible': true}.

        Checks first: method and params against the rev 481 index (validate=false skips),
        destructive calls (remove/delete, load/save project, import mappings, engine stop)
        need allow_destructive=true, protected timelines can never be removed or renamed, and
        getHasFunction must confirm the method. Returns {ok, result | errors, stage}.
        """
        return await tcall.call(client(), method, params, allow_destructive=allow_destructive,
                                validate=validate)

    # ------------------------------------------------------- show setup: inspect
    @mcp.tool()
    async def pixera_list_screens_detailed() -> dict[str, Any]:
        """All screens with handle, position (m), rotation (deg), scale, visible, blackout."""
        return await ts.list_screens_detailed(client())

    @mcp.tool()
    async def pixera_list_resources(
        folder_name_path: str | None = None, max_depth: int = 4, detailed: bool = False,
    ) -> dict[str, Any]:
        """Resource folder tree with each resource's name, id and type.

        folder_name_path (e.g. 'Media/Screens') starts at one folder. detailed adds file path
        and resolution. Use the id with pixera_setup_layer(resource_id=...).
        """
        return await ts.list_resources(client(), folder_name_path, max_depth, detailed)

    @mcp.tool()
    async def pixera_find_resource(folder_name_path: str, resource_name: str) -> dict[str, Any]:
        """Find one resource by folder name path and name; returns handle, id, type, file path."""
        return await ts.find_resource(client(), folder_name_path, resource_name)

    @mcp.tool()
    async def pixera_list_timelines_detailed(include_layers: bool = True) -> dict[str, Any]:
        """Timelines with fps and transport mode; per layer: assigned resource, model resource,
        home screen, scale mode. Protected timelines (PIXERA_PROTECTED_PREFIXES, default LE_) are marked."""
        return await ts.list_timelines_detailed(client(), include_layers)

    @mcp.tool()
    async def pixera_get_layer_json(timeline: str, layer: str) -> dict[str, Any]:
        """Return Layer.getLayerJsonDescrip for one layer (raw JSON string from Pixera)."""
        return await ts.get_layer_json(client(), timeline, layer)

    # --------------------------------------------------------- show setup: write
    @mcp.tool()
    async def pixera_set_screen_pose(
        screen_name: str, position: list[float] | None = None,
        rotation: list[float] | None = None, scale: list[float] | None = None,
        convention: str = "pixera",
    ) -> dict[str, Any]:
        """Set screen position [x,y,z] (m), rotation [x,y,z] (deg) and/or scale; reads pose back.

        Pixera is right-handed, Y-up, metres. convention='blender' converts a Blender Z-up
        position (x, y, z) to Pixera (x, z, -y); rotation is refused in that mode.
        Omitted vectors stay unchanged.
        """
        return await ts.set_screen_pose(client(), screen_name, position, rotation, scale,
                                        convention)

    @mcp.tool()
    async def pixera_import_resource(
        path: str, folder_name_path: str, directory: bool = False,
    ) -> dict[str, Any]:
        """Import a file (or, with directory=true, every file in a folder) into a resource folder.

        OBJ files become '3DModel' resources (confirmed live); assign them to a layer with
        pixera_setup_layer(model_resource_id=...).

        Directory import never removes existing resources. Returns name, id and type of each
        new resource.
        """
        return await ts.import_resource(client(), path, folder_name_path, directory)

    @mcp.tool()
    async def pixera_create_timeline(name: str) -> dict[str, Any]:
        """Create and name a new timeline. Refuses existing names and protected prefixes."""
        return await ts.create_timeline(client(), name)

    @mcp.tool()
    async def pixera_setup_layer(
        timeline: str, layer: str, create: bool = True, resource_id: float | None = None,
        model_resource_id: float | None = None, home_screen: str | None = None,
        scale_mode: str | None = None, render_only_on_home_screen: bool | None = None,
    ) -> dict[str, Any]:
        """Find or create a layer, then set any of: media resource (id), 3D model resource (id of a
        '3DModel' resource, e.g. an imported OBJ), home screen, scale_mode ('fill' | 'fit' |
        'stretch' | 'resource' | 'model_1to1'), render only on home screen. Refuses protected timelines."""
        return await ts.setup_layer(client(), timeline, layer, create=create,
                                    resource_id=resource_id,
                                    model_resource_id=model_resource_id, home_screen=home_screen,
                                    scale_mode=scale_mode,
                                    render_only_on_home_screen=render_only_on_home_screen)

    @mcp.tool()
    async def pixera_set_live_input(
        folder_name_path: str, resource_name: str, mode_index: int | None = None,
        activate: bool = True,
    ) -> dict[str, Any]:
        """Set the stream mode of an existing Live Input resource and (de)activate its streams.

        Without mode_index, only lists the available modes.
        """
        return await ts.set_live_input(client(), folder_name_path, resource_name, mode_index,
                                       activate)

    # --------------------------------------------------- show setup: mappings
    @mcp.tool()
    async def pixera_list_outputs(live_system: str | None = None) -> dict[str, Any]:
        """Outputs of a live system (default: first) with idPath, resolution, assigned
        projectors and screens. idPath (e.g. '1/2') is used by pixera_import_mappings."""
        return await ts.list_outputs(client(), live_system)

    @mcp.tool()
    async def pixera_export_mappings(path: str, live_system: str | None = None) -> dict[str, Any]:
        """Export the live system's projector mappings (warp, soft edge, color correction) to a
        folder: service_<ip>/mapping_NNN.axp plus original_output_structure.json."""
        return await ts.export_mappings(client(), path, live_system)

    @mcp.tool()
    async def pixera_import_mappings(
        path: str, output_map: dict[str, str] | None = None, live_system: str | None = None,
        allow_destructive: bool = False,
    ) -> dict[str, Any]:
        """Import mappings exported by pixera_export_mappings. output_map retargets by output
        idPath, e.g. {"1/1": "1/2"} moves output 1/1's mappings to 1/2. Overwrites the target
        outputs' mappings, so allow_destructive=true is required. Cannot create Art-Net
        outputs or feeds."""
        if not allow_destructive:
            return {"ok": False, "errors": ["importMappings overwrites mappings; pass "
                                            "allow_destructive=true to proceed."]}
        return await ts.import_mappings(client(), path, output_map, live_system)

    # ------------------------------------------------------------ live: inspect
    @mcp.tool()
    async def pixera_list_projectors() -> dict[str, Any]:
        """List projector names in the current project."""
        return await ti.list_projectors(client())

    @mcp.tool()
    async def pixera_get_projector_pose(name: str) -> dict[str, Any]:
        """Get a projector's live position (m) and rotation (deg)."""
        return await ti.get_projector_pose(client(), name)

    @mcp.tool()
    async def pixera_list_screens() -> dict[str, Any]:
        """List screen names in the current project."""
        return await ti.list_screens(client())

    @mcp.tool()
    async def pixera_list_timelines() -> dict[str, Any]:
        """List timelines (handles + count) in the current project."""
        return await ti.list_timelines(client())

    @mcp.tool()
    async def pixera_get_param(path: str) -> dict[str, Any]:
        """Read a parameter value by instance path (e.g. 'Timeline 1.Layer 1.Opacity')."""
        return await ti.get_param(client(), path)

    @mcp.tool()
    async def pixera_get_timeline_time(name: str) -> dict[str, Any]:
        """Get a timeline's current playhead time in seconds."""
        return await ti.get_timeline_time(client(), name)

    @mcp.tool()
    async def pixera_poll_monitoring() -> dict[str, Any]:
        """Fetch Pixera monitoring data (alerts/heartbeat)."""
        return await ti.poll_monitoring(client())


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
