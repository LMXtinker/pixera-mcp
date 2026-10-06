"""Tests for the offline rev 481 API index (lookup, search, call validation)."""

from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from pixera_mcp.api_index import default_index  # noqa: E402

IDX = default_index()
SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "pixera_mcp"


def test_index_size_and_kinds():
    assert len(IDX.entries) > 800
    e = IDX.get("Pixera.Timelines.Timeline.createCue")
    assert e is not None and e.kind == "method" and e.needs_handle
    assert [p.name for p in e.params] == ["name", "timeInFrames", "operation", "cueLayerHandle"]
    assert e.deliver == "Pixera.Timelines.Cue"
    f = IDX.get("Pixera.Utility.getHasFunction")
    assert f is not None and f.kind == "function" and not f.needs_handle


def test_case_insensitive_get_and_suggest():
    assert IDX.get("pixera.screens.getscreennames").name == "Pixera.Screens.getScreenNames"
    assert "Pixera.Screens.getScreenNames" in IDX.suggest("Pixera.Screens.getScreenName")
    # rev204-style short form gets pointed at the class-qualified method
    assert "Pixera.Screens.Screen.setPosition" in IDX.suggest("Pixera.Screens.setPosition")


def test_describe_exact_prefix_and_none():
    d = IDX.describe("Pixera.Screens.Screen.setPosRotScale")
    assert d["match"] == "exact"
    assert d["signature"].startswith("bool Pixera.Screens.Screen.setPosRotScale(handle handle")
    assert all(p["optional"] for p in d["params"])
    s = IDX.describe("Pixera.Timelines.Layer.")
    assert s["match"] == "search" and len(s["results"]) == 40 and s["truncated"]
    sub = IDX.describe("VideoStreamMode")
    assert any("setVideoStreamMode" in r["signature"] for r in sub["results"])
    assert IDX.describe("zzzNothing")["match"] == "none"


def test_check_call_rules():
    ok = IDX.check_call("Pixera.Timelines.Timeline.createCue",
                        {"handle": 1, "name": "A", "timeInFrames": 0.0, "operation": 1,
                         "cueLayerHandle": 0})
    assert ok["ok"], ok["errors"]
    missing = IDX.check_call("Pixera.Timelines.Timeline.createCue",
                             {"handle": 1, "name": "A", "timeInFrames": 0.0, "operation": 1})
    assert not missing["ok"] and any("cueLayerHandle" in e for e in missing["errors"])
    no_handle = IDX.check_call("Pixera.Timelines.Timeline.setName", {"name": "x"})
    assert not no_handle["ok"] and any("handle" in e for e in no_handle["errors"])
    unknown = IDX.check_call("Pixera.Screens.getScreenNames", {"bogus": 1})
    assert not unknown["ok"]
    optional = IDX.check_call("Pixera.Screens.Screen.setPosRotScale", {"handle": 1, "xPos": 1.0})
    assert optional["ok"]
    typed = IDX.check_call("Pixera.Timelines.Layer.setScaleUnitMode", {"handle": 1, "mode": "fit"})
    assert typed["ok"] and typed["warnings"]
    case = IDX.check_call("pixera.utility.noop", {})
    assert not case["ok"] and "case-sensitive" in case["errors"][0]


def test_every_literal_method_in_src_exists_in_rev481():
    """Static guard: every "Pixera.X.Y" string literal in the server code is a rev481 method."""
    prefixes = {"_TS": "Pixera.Timelines", "_RS": "Pixera.Resources", "_SC": "Pixera.Screens"}
    bad = []
    for path in SRC.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        names = set(re.findall(r'"(Pixera\.[A-Za-z.]+[A-Za-z])"', text))
        for var, prefix in prefixes.items():
            names |= {prefix + m for m in re.findall(r'f"\{' + var + r'\}(\.[A-Za-z.]+)"', text)}
        for name in names:
            if name.count(".") >= 2 and IDX.get(name) is None and not name.endswith("."):
                bad.append(f"{path.name}: {name}")
    assert not bad, bad
