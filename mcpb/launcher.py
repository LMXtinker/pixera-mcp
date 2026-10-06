"""Claude Desktop extension entry point for pixera-mcp, with self-update from GitHub.

Claude Desktop runs this file with ``uv run`` inside the installed .mcpb folder. uv
installs the dependencies listed in the bundle's ``pyproject.toml``. The launcher then:

1. Asks GitHub for the latest release of the repository (4 s timeout, no token).
2. If that release is newer than what it has, downloads the release source and
   keeps ``src/pixera_mcp`` in a local cache.
3. Starts the newest usable copy: cached release or the copy bundled in the .mcpb.

A release is only used when its dependencies equal the bundle's. A release that
adds or changes dependencies needs a new .mcpb, so the launcher keeps running the
older code and logs where to download the new bundle. Offline, it uses the cache.

Everything goes to stderr: stdout carries the MCP protocol.

Environment (set from the extension settings):
    PIXERA_AUTO_UPDATE   "false" disables the GitHub check (default "true")
    PIXERA_MCP_REPO      owner/name of the GitHub repository (default below)
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import sys
import tempfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_REPO = "LMXtinker/pixera-mcp"
HERE = Path(__file__).resolve().parent
BUNDLED_SRC = HERE / "src"
TIMEOUT_S = 4.0


def log(msg: str) -> None:
    print(f"[pixera-mcp launcher] {msg}", file=sys.stderr, flush=True)


def cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME") \
        or str(Path.home() / ".cache")
    return Path(base) / "pixera-mcp" / "releases"


def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def normalize_deps(deps: list[str]) -> list[str]:
    return sorted(re.sub(r"\s+", "", d.split(";")[0].split("#")[0]).lower() for d in deps if d.strip())


def read_pyproject(text: str) -> tuple[str, list[str]]:
    data = tomllib.loads(text)
    project = data.get("project", {})
    return str(project.get("version", "0")), list(project.get("dependencies", []))


def bundle_info() -> tuple[str, list[str]]:
    return read_pyproject((HERE / "pyproject.toml").read_text(encoding="utf-8"))


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "pixera-mcp-launcher",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 (fixed https URLs)
        return resp.read()


def latest_tag(repo: str) -> str:
    data = json.loads(http_get(f"https://api.github.com/repos/{repo}/releases/latest"))
    return str(data["tag_name"])


def install_release(repo: str, tag: str, dest_root: Path, bundle_deps: list[str],
                    fetch=http_get) -> Path | None:
    """Download a tagged source zip and cache its ``src/pixera_mcp``.

    Returns the cache folder (containing ``pixera_mcp``), or None if the release
    needs different dependencies than the bundle provides.
    """
    blob = fetch(f"https://codeload.github.com/{repo}/zip/refs/tags/{tag}")
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
        top = names[0].split("/", 1)[0]
        pyproject = zf.read(f"{top}/pyproject.toml").decode("utf-8")
        _, deps = read_pyproject(pyproject)
        if normalize_deps(deps) != normalize_deps(bundle_deps):
            log(f"Release {tag} changes dependencies; download the new .mcpb from "
                f"https://github.com/{repo}/releases/latest. Keeping the current code.")
            return None
        prefix = f"{top}/src/pixera_mcp/"
        dest_root.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=f".{tag}-", dir=dest_root))
        try:
            for name in names:
                if not name.startswith(prefix) or name.endswith("/"):
                    continue
                rel = name[len(f"{top}/src/"):]
                target = tmp / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(name))
            final = dest_root / tag
            if final.exists():
                shutil.rmtree(final)
            tmp.rename(final)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
    (dest_root / "current.json").write_text(json.dumps({"tag": tag}), encoding="utf-8")
    return dest_root / tag


def cached_release(dest_root: Path) -> tuple[str, Path] | None:
    try:
        tag = json.loads((dest_root / "current.json").read_text(encoding="utf-8"))["tag"]
    except (OSError, ValueError, KeyError):
        return None
    path = dest_root / tag
    return (tag, path) if (path / "pixera_mcp" / "server.py").is_file() else None


def choose_source(repo: str, auto_update: bool, dest_root: Path, fetch_tag=latest_tag,
                  fetch=http_get) -> tuple[str, Path]:
    """Return (label, folder to put on sys.path)."""
    bundle_version, bundle_deps = bundle_info()
    cached = cached_release(dest_root)
    if auto_update:
        try:
            tag = fetch_tag(repo)
            if version_tuple(tag) > version_tuple(bundle_version) and \
                    (cached is None or version_tuple(tag) > version_tuple(cached[0])):
                log(f"Updating to {tag} from github.com/{repo}")
                path = install_release(repo, tag, dest_root, bundle_deps, fetch)
                if path is not None:
                    cached = (tag, path)
        except Exception as exc:  # noqa: BLE001 - offline or GitHub down: keep going
            log(f"Update check skipped: {exc}")
    if cached and version_tuple(cached[0]) > version_tuple(bundle_version):
        return cached[0], cached[1]
    return f"bundled {bundle_version}", BUNDLED_SRC


def main() -> None:
    repo = os.environ.get("PIXERA_MCP_REPO") or DEFAULT_REPO
    auto = os.environ.get("PIXERA_AUTO_UPDATE", "true").strip().lower() not in ("0", "false", "no", "off")
    label, path = choose_source(repo, auto, cache_dir())
    sys.path.insert(0, str(path))
    try:
        from pixera_mcp.server import main as server_main
    except Exception as exc:  # noqa: BLE001 - broken cached release: fall back to the bundle
        log(f"Could not load {label} ({exc}); using the bundled copy.")
        sys.path.remove(str(path))
        for mod in [m for m in sys.modules if m == "pixera_mcp" or m.startswith("pixera_mcp.")]:
            del sys.modules[mod]
        sys.path.insert(0, str(BUNDLED_SRC))
        label = "bundled"
        from pixera_mcp.server import main as server_main
    log(f"Starting pixera-mcp ({label})")
    server_main()


if __name__ == "__main__":
    main()
