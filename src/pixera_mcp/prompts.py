"""MCP prompt registration: guided, reusable projection-mapping workflows.

Prompts return text that steers the assistant through a workflow, pointing it at
the right tools (``validate_*``, ``recommend_*``, ``recommend_markers_for_projector``)
and knowledge resources (``pixera://guide/*``).
"""

from __future__ import annotations


def register_prompts(mcp) -> None:
    @mcp.prompt(title="Marker calibration walkthrough")
    def marker_calibration_walkthrough() -> str:
        return (
            "Guide me through Pixera marker calibration. Follow this order and validate as we go:\n"
            "1. Confirm prerequisites: EDIDs set/locked FIRST; lens (throw/shift/FOV) pre-set; an "
            "accurate 3D model (ideally a scan); output activated.\n"
            "2. Read pixera://guide/marker-calibration for the rules.\n"
            "3. If a projector + lens + mesh are available, call recommend_markers_for_projector to "
            "get marker positions from what the projector actually sees.\n"
            "4. Place >=5 markers (6-8 for 3D), in all corners, non-coplanar with depth variation.\n"
            "5. Call validate_marker_calibration with my parameters and fix every error/warning.\n"
            "6. Iterate Calculate until Re-Projection Error < 1px @ HD.\n"
            "Ask me for any values you need (surface type, marker count, whether EDIDs are set, etc.)."
        )

    @mcp.prompt(title="Recommend a calibration strategy")
    def recommend_calibration_strategy(surface: str = "", projectors: str = "1",
                                       accuracy: str = "standard", time_budget: str = "normal") -> str:
        return (
            f"Recommend a calibration strategy for: surface={surface!r}, projectors={projectors}, "
            f"accuracy={accuracy!r}, time={time_budget!r}. "
            "Call recommend_calibration_method with these, then explain the trade-offs versus the "
            "alternatives and list the prerequisites I must satisfy. Reference "
            "pixera://guide/calibration-algorithms."
        )

    @mcp.prompt(title="Set up projection mapping")
    def setup_projection_mapping(surface_type: str = "flat", projectors: str = "1") -> str:
        return (
            f"Help me set up projection mapping for a {surface_type} surface with {projectors} "
            "projector(s). Call plan_projection_mapping for an ordered plan, then walk me through each "
            "step. Run the suggested validations (validate_canvas_resolution, validate_feed_mode, and "
            "validate_softedge if multi-projector) as we configure. Reference pixera://guide/projection-mapping-101."
        )

    @mcp.prompt(title="Set up soft-edge blend")
    def setup_softedge_blend(projectors: str = "2", overlap: str = "20") -> str:
        return (
            f"Help me set up a soft-edge blend across {projectors} projectors with ~{overlap}% overlap. "
            "Read pixera://guide/softedge. Confirm Feed Areas are enabled and ALL projectors are "
            "selected, then validate with validate_softedge and fix any findings. Remember soft-edge "
            "values are UI-only - you can guide and validate but not set them via the API."
        )

    @mcp.prompt(title="Troubleshoot a projection problem")
    def troubleshoot_projection(symptom: str = "") -> str:
        return (
            f"I have this projection problem: {symptom!r}. Call diagnose with it, then give me the most "
            "likely cause and the concrete fix. If it concerns blending or warping, also cite the "
            "relevant pixera://guide/* resource."
        )
