"""Offline index of the Pixera Native API, built from Pixera's machine-readable API JSON.

Pixera ships ``data/api/pixera_api.json`` with every install. It lists every
namespace function and class method with parameter names and types. This module
flattens that tree into fully qualified names (``Pixera.Timelines.Timeline.createCue``)
so tools can look up signatures and validate a call before it goes over the wire.

Conventions from the JSON (checked against rev 481):

* Namespace functions take their params as listed.
* Class methods additionally take ``handle`` (the object handle). It is not listed
  in the JSON, so :meth:`ApiIndex.check_call` adds it.
* ``optional<T>`` params may be omitted. All other params are treated as required:
  live testing showed ``Timeline.createCue`` fails with error -5 when
  ``cueLayerHandle`` is omitted, although its comment calls it optional.

The API JSON belongs to AV Stumpfl and is not shipped with this package. It is
found at runtime, in this order:

1. ``PIXERA_API_JSON`` (path to a ``pixera_api.json``),
2. ``api/pixera_api*.json`` next to this module (local copy, git-ignored),
3. the newest local Pixera install: ``<Program Files>/AV Stumpfl/Pixera/*/data/api/pixera_api.json``.

Without a file, :func:`default_index` raises :class:`ApiIndexUnavailable` and the
tools fall back to ``getHasFunction`` checks only.
"""

from __future__ import annotations

import difflib
import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

_LOCAL_DIR = Path(__file__).parent / "api"


class ApiIndexUnavailable(FileNotFoundError):
    """No Pixera API JSON was found (see module docstring for the search order)."""


def _rev(path: Path) -> int:
    m = re.search(r"rev(\d+)", path.name)
    return int(m.group(1)) if m else -1


def find_api_json() -> Path:
    """Locate a Pixera API JSON file; raise :class:`ApiIndexUnavailable` if none exists."""
    env = os.environ.get("PIXERA_API_JSON")
    if env:
        p = Path(env)
        if p.is_file():
            return p
        raise ApiIndexUnavailable(f"PIXERA_API_JSON points to a missing file: {env}")
    local = sorted(_LOCAL_DIR.glob("pixera_api*.json"), key=_rev)
    if local:
        return local[-1]
    found: list[Path] = []
    for base in {os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramW6432", r"C:\Program Files")}:
        root = Path(base) / "AV Stumpfl" / "Pixera"
        if root.is_dir():
            found += root.glob("*/data/api/pixera_api*.json")
    if found:
        return max(found, key=lambda f: (_rev(f), f.stat().st_mtime))
    raise ApiIndexUnavailable(
        "No Pixera API JSON found. Install Pixera on this machine, or set PIXERA_API_JSON to "
        "<Pixera install>/data/api/pixera_api.json (copy it from the Pixera PC).")


@dataclass(frozen=True)
class ApiParam:
    name: str
    type: str

    @property
    def optional(self) -> bool:
        return self.type.startswith("optional<")


@dataclass(frozen=True)
class ApiEntry:
    """One callable: a namespace function or a class method."""

    name: str                      # fully qualified, e.g. Pixera.Screens.Screen.setPosition
    kind: str                      # "function" or "method"
    owner: str                     # namespace or class it belongs to
    params: tuple[ApiParam, ...]
    returns: str
    doc: str = ""
    deliver: str | None = None     # class whose handle(s) the call returns, if any
    extra: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def short(self) -> str:
        return self.name.rsplit(".", 1)[-1]

    @property
    def needs_handle(self) -> bool:
        return self.kind == "method"

    def signature(self) -> str:
        args = [f"{p.type} {p.name}" for p in self.params]
        if self.needs_handle:
            args.insert(0, "handle handle")
        return f"{self.returns} {self.name}({', '.join(args)})"

    def to_dict(self, with_doc: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "signature": self.signature(),
            "params": [{"name": p.name, "type": p.type, "optional": p.optional}
                       for p in self.params],
            "returns": self.returns,
        }
        if self.needs_handle:
            out["handle_from"] = f"a {self.owner} handle (pass as params.handle)"
        if self.deliver:
            out["returns_handle_of"] = self.deliver
        if with_doc and self.doc:
            out["doc"] = self.doc
        return out


def _clean_doc(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\r", "").replace("<br>", "")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _type_ok(api_type: str, value: Any) -> bool:
    """Loose JSON type check; unknown API types always pass."""
    t = api_type
    if t.startswith("optional<"):
        t = t[len("optional<"):-1]
    if t.endswith("[]"):
        return isinstance(value, list) and all(_type_ok(t[:-2], v) for v in value)
    if t == "bool":
        return isinstance(value, bool)
    if t in ("int", "uint", "handle"):
        return isinstance(value, int) and not isinstance(value, bool)
    if t in ("double", "float"):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "string":
        return isinstance(value, str)
    return True


class ApiIndex:
    def __init__(self, data: dict[str, Any], source: str = ""):
        self.source = source
        self.entries: dict[str, ApiEntry] = {}
        self._walk(data, "")
        self._lower = {k.lower(): k for k in self.entries}

    # ----------------------------------------------------------------- build
    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "ApiIndex":
        p = Path(path) if path else find_api_json()
        with open(p, encoding="utf-8-sig") as fh:
            return cls(json.load(fh), source=str(p))

    def _walk(self, ns: dict[str, Any], prefix: str) -> None:
        name = f"{prefix}.{ns['name']}" if prefix else ns["name"]
        for fn in ns.get("functions", []):
            self._add(fn, "function", name)
        for cls_ in ns.get("classes", []):
            owner = f"{name}.{cls_['name']}"
            for m in cls_.get("methods", []):
                self._add(m, "method", owner)
        for sub in ns.get("namespaces", []):
            self._walk(sub, name)

    def _add(self, fn: dict[str, Any], kind: str, owner: str) -> None:
        params = tuple(ApiParam(p["name"], p["type"]) for p in fn.get("params", []))
        rets = fn.get("returnValues") or []
        returns = rets[0]["type"] if rets else "null"
        fq = f"{owner}.{fn['name']}"
        self.entries[fq] = ApiEntry(
            name=fq, kind=kind, owner=owner, params=params, returns=returns,
            doc=_clean_doc(fn.get("documentation")), deliver=fn.get("deliver"),
            extra={k: v for k, v in fn.items()
                   if k not in ("name", "params", "returnValues", "documentation", "deliver")},
        )

    # ---------------------------------------------------------------- lookup
    def get(self, name: str) -> ApiEntry | None:
        hit = self.entries.get(name)
        if hit is None:
            key = self._lower.get(name.lower())
            hit = self.entries.get(key) if key else None
        return hit

    def suggest(self, name: str, n: int = 5) -> list[str]:
        """Close matches for a mistyped method name (by full name and by short name)."""
        out = difflib.get_close_matches(name, self.entries.keys(), n=n, cutoff=0.6)
        short = name.rsplit(".", 1)[-1].lower()
        for k, e in self.entries.items():
            if len(out) >= n:
                break
            if e.short.lower() == short and k not in out:
                out.append(k)
        return out

    def search(self, query: str, limit: int = 40) -> list[ApiEntry]:
        """Prefix match on the full name, else case-insensitive substring on name and doc."""
        q = query.strip()
        hits = [e for k, e in self.entries.items() if k.startswith(q)]
        if not hits:
            ql = q.lower()
            hits = [e for k, e in self.entries.items() if ql in k.lower()]
            if not hits:
                hits = [e for e in self.entries.values() if ql in e.doc.lower()]
        return hits[:limit]

    def describe(self, query: str, limit: int = 40) -> dict[str, Any]:
        exact = self.get(query)
        if exact is not None:
            return {"match": "exact", **exact.to_dict()}
        hits = self.search(query, limit=limit + 1)
        if hits:
            out: dict[str, Any] = {
                "match": "search",
                "query": query,
                "results": [{"signature": e.signature(),
                             "summary": e.doc.split("\n", 1)[0] if e.doc else ""}
                            for e in hits[:limit]],
            }
            if len(hits) > limit:
                out["truncated"] = True
                out["hint"] = "Narrow the query (e.g. a class prefix like 'Pixera.Timelines.Layer.')."
            return out
        return {"match": "none", "query": query, "did_you_mean": self.suggest(query)}

    # ------------------------------------------------------------ validation
    def check_call(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        """Validate a call offline. Returns ``{"ok", "errors", "warnings", "entry"}``."""
        params = params or {}
        errors: list[str] = []
        warnings: list[str] = []
        entry = self.entries.get(method)
        if entry is None:
            near = self.get(method)
            if near is not None:
                errors.append(f"Method names are case-sensitive: use {near.name!r}.")
            else:
                errors.append(f"Unknown method {method!r} in API index ({self.source}).")
                sugg = self.suggest(method)
                if sugg:
                    errors.append(f"Did you mean: {', '.join(sugg)}")
            return {"ok": False, "errors": errors, "warnings": warnings, "entry": None}

        known = {p.name for p in entry.params}
        if entry.needs_handle:
            if "handle" not in params:
                errors.append(f"{method} is a {entry.owner} method and needs params.handle.")
            known.add("handle")
        for key in params:
            if key not in known:
                errors.append(f"Unknown param {key!r}. Expected: {sorted(known) or 'none'}.")
        for p in entry.params:
            if p.name not in params:
                if not p.optional:
                    errors.append(f"Missing required param {p.name!r} ({p.type}).")
            elif not _type_ok(p.type, params[p.name]):
                warnings.append(f"Param {p.name!r} expects {p.type}, got "
                                f"{type(params[p.name]).__name__}.")
        return {"ok": not errors, "errors": errors, "warnings": warnings, "entry": entry}


@lru_cache(maxsize=1)
def default_index() -> ApiIndex:
    return ApiIndex.load()
