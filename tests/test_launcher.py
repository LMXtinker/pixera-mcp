"""Self-update logic of the Claude Desktop extension launcher (mcpb/launcher.py)."""

from __future__ import annotations

import importlib.util
import io
import json
import pathlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("launcher", ROOT / "mcpb" / "launcher.py")
launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launcher)


def _zip(tag: str, deps: list[str]) -> bytes:
    buf = io.BytesIO()
    top = f"pixera-mcp-{tag.lstrip('v')}"
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{top}/pyproject.toml",
                    f'[project]\nname="pixera-mcp"\nversion="{tag.lstrip("v")}"\n'
                    f"dependencies={json.dumps(deps)}\n")
        zf.writestr(f"{top}/src/pixera_mcp/__init__.py", "")
        zf.writestr(f"{top}/src/pixera_mcp/server.py", "def main():\n    return 'release'\n")
        zf.writestr(f"{top}/README.md", "x")
    return buf.getvalue()


def _patch_bundle(monkeypatch, version="0.2.0", deps=("mcp>=1.2.0,<2", "numpy>=1.24")):
    monkeypatch.setattr(launcher, "bundle_info", lambda: (version, list(deps)))


def test_newer_release_with_same_deps_is_installed(tmp_path, monkeypatch):
    _patch_bundle(monkeypatch)
    label, path = launcher.choose_source(
        "o/r", True, tmp_path, fetch_tag=lambda repo: "v0.3.0",
        fetch=lambda url: _zip("v0.3.0", ["numpy>=1.24", "mcp >= 1.2.0, < 2"]))
    assert label == "v0.3.0"
    assert (path / "pixera_mcp" / "server.py").is_file()
    assert not (path / "README.md").exists()
    assert json.loads((tmp_path / "current.json").read_text())["tag"] == "v0.3.0"


def test_release_with_new_deps_is_skipped(tmp_path, monkeypatch):
    _patch_bundle(monkeypatch)
    label, path = launcher.choose_source(
        "o/r", True, tmp_path, fetch_tag=lambda repo: "v0.3.0",
        fetch=lambda url: _zip("v0.3.0", ["mcp>=1.2.0,<2", "numpy>=1.24", "trimesh"]))
    assert label.startswith("bundled") and path == launcher.BUNDLED_SRC


def test_offline_uses_cache_then_bundle(tmp_path, monkeypatch):
    _patch_bundle(monkeypatch)
    launcher.choose_source("o/r", True, tmp_path, fetch_tag=lambda r: "v0.3.0",
                           fetch=lambda u: _zip("v0.3.0", ["mcp>=1.2.0,<2", "numpy>=1.24"]))

    def offline(repo):
        raise OSError("no network")

    label, _ = launcher.choose_source("o/r", True, tmp_path, fetch_tag=offline)
    assert label == "v0.3.0"
    label, path = launcher.choose_source("o/r", True, tmp_path / "empty", fetch_tag=offline)
    assert label.startswith("bundled")


def test_newer_bundle_beats_older_cache(tmp_path, monkeypatch):
    _patch_bundle(monkeypatch, version="0.2.0")
    launcher.choose_source("o/r", True, tmp_path, fetch_tag=lambda r: "v0.3.0",
                           fetch=lambda u: _zip("v0.3.0", ["mcp>=1.2.0,<2", "numpy>=1.24"]))
    _patch_bundle(monkeypatch, version="0.4.0")
    label, path = launcher.choose_source("o/r", False, tmp_path)
    assert label == "bundled 0.4.0"


def test_auto_update_off_never_fetches(tmp_path, monkeypatch):
    _patch_bundle(monkeypatch)

    def boom(*a):
        raise AssertionError("network used")

    label, _ = launcher.choose_source("o/r", False, tmp_path, fetch_tag=boom, fetch=boom)
    assert label.startswith("bundled")
