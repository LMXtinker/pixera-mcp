"""Tests for the parameter-validation rules and offline guidance recommenders."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from pixera_mcp import validation as V  # noqa: E402
from pixera_mcp.tools_guidance import (  # noqa: E402
    diagnose, recommend_calibration_method, recommend_warp_method,
)


def _messages(findings):
    return " | ".join(f.message for f in findings)


# ----------------------------------------------------------------- soft edge
def test_softedge_flags_bad_config():
    findings = V.validate_softedge({
        "projector_count": 3, "overlaps": [10, 30],
        "feed_areas_enabled": False, "feed_mode": "fit", "surface_type": "flat",
    })
    summary = V.summarize(findings)
    assert summary["verdict"] == "fail"
    text = _messages(findings)
    assert "Feed Areas" in text          # prerequisite error
    assert "inconsistent" in text.lower()  # mismatched overlap error
    assert any("10%" in m for m in [f.message for f in findings])  # low-overlap warn


def test_softedge_accepts_good_config():
    findings = V.validate_softedge({
        "projector_count": 2, "overlaps": [20, 20],
        "feed_areas_enabled": True, "feed_mode": "fit", "surface_type": "flat",
    })
    summary = V.summarize(findings)
    assert summary["ok"] is True and summary["verdict"] == "pass"


# --------------------------------------------------------- marker calibration
def test_marker_flags_coplanar_and_prereqs():
    findings = V.validate_marker_calibration({
        "marker_count": 4, "coplanar": True, "surface_type": "3d",
        "edids_set": False, "placement": "center", "lens_preset": False,
        "model_from_scan": False, "depth_varied": False, "reprojection_error": 5.0,
    })
    summary = V.summarize(findings)
    assert summary["verdict"] == "fail"
    text = _messages(findings).lower()
    assert "edid" in text                # EDID-first error
    assert "minimum of 5" in text        # too-few-markers error
    assert "coplanar" in text            # degeneracy error
    assert "re-projection error 5" in text


def test_marker_accepts_good_config():
    findings = V.validate_marker_calibration({
        "marker_count": 7, "coplanar": False, "depth_varied": True,
        "placement": "corners", "lens_preset": True, "edids_set": True,
        "model_from_scan": True, "surface_type": "3d", "reprojection_error": 0.6,
    })
    assert V.summarize(findings)["ok"] is True


# ----------------------------------------------------- canvas / feed mode
def test_canvas_below_projector_warns():
    findings = V.validate_canvas_resolution({
        "canvas_w": 1280, "canvas_h": 720, "projector_w": 1920, "projector_h": 1080,
        "keep_square": True,
    })
    summary = V.summarize(findings)
    assert summary["ok"] is True and summary["verdict"] == "review"
    assert "below projector output" in _messages(findings)


def test_feed_mode_rules():
    err = V.validate_feed_mode({"surface_type": "3d", "uv_continuous": False, "feed_mode": "fit"})
    assert V.summarize(err)["verdict"] == "fail"
    warn = V.validate_feed_mode({"surface_type": "flat", "feed_mode": "none"})
    assert any(f.severity == "warn" for f in warn)


# ------------------------------------------------------------- recommenders
def test_recommend_calibration_method():
    assert "VIOSO" in recommend_calibration_method("dome", 8, "high", "ample", True)["recommended"]["method"]
    assert "homography" in recommend_calibration_method("flat", 1, "standard", "tight", False)["recommended"]["method"].lower()
    assert "Marker" in recommend_calibration_method("object", 1, "standard", "normal", False)["recommended"]["method"]


def test_recommend_warp_method():
    assert "Multi-Pos" in recommend_warp_method(tracked=True)["method"]
    assert "Vertex" in recommend_warp_method(has_3d_model=True)["method"]
    assert "FFD" in recommend_warp_method()["method"]


def test_diagnose():
    assert diagnose("there is a visible seam between the two projectors")["matched"] is True
    assert diagnose("the projector output is completely black")["matched"] is True
    assert diagnose("xyzzy nonsense")["matched"] is False


def _run_all() -> None:
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("validation: all passed")


if __name__ == "__main__":
    _run_all()
