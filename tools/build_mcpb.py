"""Build the Claude Desktop extension: dist/pixera-mcp-<version>.mcpb.

Stages mcpb/ (manifest, launcher, icon) plus a copy of src/pixera_mcp into a
temp folder (outside synced folders such as OneDrive, which lock files), writes the bundle's pyproject.toml from the root one (same version and
dependencies, which the launcher compares against later releases), then runs the
official packer: ``npx -y @anthropic-ai/mcpb pack``.

Usage: python tools/build_mcpb.py [--no-pack]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGE = Path(tempfile.gettempdir()) / "pixera-mcp-build"
DIST = ROOT / "dist"


def toml_list(items: list[str]) -> str:
    return "[\n" + "".join(f"    {json.dumps(i)},\n" for i in items) + "]"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-pack", action="store_true", help="only stage the files")
    args = ap.parse_args()

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]

    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir()
    for name in ("launcher.py", "icon.png", ".mcpbignore"):
        shutil.copy2(ROOT / "mcpb" / name, STAGE / name)
    shutil.copy2(ROOT / "LICENSE", STAGE / "LICENSE")

    manifest = json.loads((ROOT / "mcpb" / "manifest.json").read_text(encoding="utf-8"))
    manifest["version"] = version
    (STAGE / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    (STAGE / "pyproject.toml").write_text(
        "[project]\n"
        'name = "pixera-mcp-extension"\n'
        f'version = "{version}"\n'
        'description = "Claude Desktop extension launcher for pixera-mcp"\n'
        'requires-python = ">=3.11"\n'
        f"dependencies = {toml_list(project['dependencies'])}\n\n"
        "[tool.uv]\n"
        "package = false\n",
        encoding="utf-8",
    )

    shutil.copytree(ROOT / "src" / "pixera_mcp", STAGE / "src" / "pixera_mcp",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "api"))
    leaked = [p for p in STAGE.rglob("*.json") if p.name.startswith("pixera_api")]
    if leaked:
        sys.exit(f"Refusing to pack vendor API files: {leaked}")
    print(f"Staged {STAGE} (version {version})")

    if args.no_pack:
        return
    DIST.mkdir(exist_ok=True)
    out = DIST / f"pixera-mcp-{version}.mcpb"
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        sys.exit("npx not found: install Node.js to pack the bundle.")
    subprocess.run([npx, "-y", "@anthropic-ai/mcpb", "validate", str(STAGE / "manifest.json")],
                   check=True)
    subprocess.run([npx, "-y", "@anthropic-ai/mcpb", "pack", str(STAGE), str(out)], check=True)
    print(f"Built {out}")


if __name__ == "__main__":
    main()
