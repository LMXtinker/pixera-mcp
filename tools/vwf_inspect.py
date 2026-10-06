#!/usr/bin/env python
"""Structural inspector for a VIOSO ``.vwf`` warp file.

The .vwf format is proprietary and undocumented, so this tool reverse-engineers
the layout from a real sample: it dumps the header, embedded strings, plausible
float32 grid dimensions, and probes for the VIOSO WarpBlend DLL (which, if
present, exposes the warp/blend mesh on the CPU via ctypes).

Usage:
    python tools/vwf_inspect.py path\\to\\sample.vwf
    python tools/vwf_inspect.py sample.vwf --dll "C:\\path\\to\\VIOSOWarpBlend.dll"

Share its output (or the sample file) and the layout can be turned into a real
parser + an MCP `import_warp_context` tool.
"""

from __future__ import annotations

import argparse
import pathlib
import string
import struct
import sys

_PRINTABLE = set(bytes(string.printable[:-5], "ascii"))
# Common projector / warp-grid resolutions to test dimension guesses against.
_COMMON = [(1920, 1080), (3840, 2160), (1280, 800), (1280, 720), (1024, 768),
           (2560, 1600), (1600, 1200), (2048, 1080), (256, 256), (128, 128),
           (64, 64), (200, 200), (100, 100)]
_ASPECTS = [16 / 9, 16 / 10, 4 / 3, 1.0, 2.0]


def hexdump(data: bytes, n: int = 256) -> str:
    out = []
    for off in range(0, min(len(data), n), 16):
        chunk = data[off:off + 16]
        hexs = " ".join(f"{b:02x}" for b in chunk)
        text = "".join(chr(b) if b in _PRINTABLE and b >= 32 else "." for b in chunk)
        out.append(f"  {off:08x}  {hexs:<47}  {text}")
    return "\n".join(out)


def find_strings(data: bytes, minlen: int = 4, limit: int = 40) -> list[str]:
    found, cur = [], bytearray()
    for b in data:
        if 32 <= b < 127:
            cur.append(b)
        else:
            if len(cur) >= minlen:
                found.append(cur.decode("ascii", "replace"))
            cur = bytearray()
    if len(cur) >= minlen:
        found.append(cur.decode("ascii", "replace"))
    return found[:limit]


def read_scalars(data: bytes) -> None:
    """Print the first handful of int32/float32/int64 readings at offset 0."""
    print("  as int32 :", struct.unpack_from("<8i", data, 0) if len(data) >= 32 else "n/a")
    print("  as uint32:", struct.unpack_from("<8I", data, 0) if len(data) >= 32 else "n/a")
    print("  as float :", tuple(round(x, 4) for x in struct.unpack_from("<8f", data, 0))
          if len(data) >= 32 else "n/a")


def guess_float_grids(nbytes: int, max_header: int = 4096) -> list[str]:
    """Guess W x H x channels float32 layouts that fit the file size."""
    hits = []
    for header in range(0, min(max_header, nbytes), 4):
        rem = nbytes - header
        if rem <= 0 or rem % 4:
            continue
        floats = rem // 4
        for ch in (1, 2, 3, 4, 5, 6):
            if floats % ch:
                continue
            cells = floats // ch
            for (w, h) in _COMMON:
                if w * h == cells:
                    hits.append(f"header={header}B  grid={w}x{h}  channels={ch} (float32)")
            # also accept near-aspect square-ish factorings
            root = int(cells ** 0.5)
            for w in range(max(1, root - 2), root + 3):
                if w and cells % w == 0:
                    h = cells // w
                    if 16 <= w <= 8192 and 16 <= h <= 8192:
                        ar = w / h
                        if any(abs(ar - a) < 0.02 for a in _ASPECTS):
                            hits.append(f"header={header}B  grid={w}x{h}  channels={ch} (float32, aspect)")
        if len(hits) > 30:
            break
    # de-dup, keep order
    seen, out = set(), []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out[:30]


def probe_dll(dll_path: str | None) -> None:
    import ctypes

    candidates = [dll_path] if dll_path else [
        "VIOSOWarpBlend.dll",
        r"C:\Program Files\AV Stumpfl\Pixera\VIOSOWarpBlend.dll",
    ]
    wanted = ["VWB_Create", "VWB_CreateA", "VWB_Init", "VWB_Destroy", "VWB_render",
              "VWB_getWarpBlendMesh", "VWB_getWarpBlend", "VWB_getViewClip"]
    for cand in candidates:
        if not cand:
            continue
        try:
            lib = ctypes.WinDLL(cand)
        except OSError as exc:
            print(f"  DLL '{cand}': not loadable ({exc})")
            continue
        present = [s for s in wanted if hasattr(lib, s)]
        print(f"  DLL '{cand}': loaded. exported (of interest): {present or 'none of the probed names'}")
        if any(s in present for s in ("VWB_getWarpBlendMesh", "VWB_getWarpBlend")):
            print("  -> a CPU-side warp/blend mesh getter is available; a clean ctypes reader is viable.")
        return
    print("  No VIOSO DLL found. Pass --dll <path> if VIOSOWarpBlend.dll exists in your install.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Inspect a VIOSO .vwf warp file.")
    ap.add_argument("path", help="path to a .vwf sample")
    ap.add_argument("--dll", default=None, help="path to VIOSOWarpBlend.dll (optional)")
    args = ap.parse_args()

    data = pathlib.Path(args.path).read_bytes()
    print(f"file: {args.path}")
    print(f"size: {len(data)} bytes")
    print("\n[header hexdump]")
    print(hexdump(data, 256))
    print("\n[first scalars @0]")
    read_scalars(data)
    print("\n[embedded ascii strings]")
    for s in find_strings(data):
        print("  ", repr(s))
    print("\n[float32 grid guesses (size-based)]")
    for g in guess_float_grids(len(data)) or ["  (none fit common resolutions/aspects)"]:
        print("  ", g)
    print("\n[VIOSO DLL probe]")
    if sys.platform == "win32":
        probe_dll(args.dll)
    else:
        print("  (skip: not on Windows)")


if __name__ == "__main__":
    main()
