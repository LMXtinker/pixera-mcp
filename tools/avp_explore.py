#!/usr/bin/env python
"""Schema explorer for an AV Stumpfl Pixera ``.avp`` show-file.

The .avp is a custom tagged-binary tree: type/field names and string values are
stored length-prefixed (``<len:1byte><ascii>``). This tool extracts that
vocabulary so we can locate warp / marker / projector / mapping structures and
then decode the float payloads next to them.

Usage:
    python tools/avp_explore.py path\\to\\project.avp
    python tools/avp_explore.py project.avp --grep warp,ffd,marker --context 64
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import re
import struct

_WORD = re.compile(rb"^[A-Za-z0-9_./:\- ]+$")
_DEFAULT_KEYS = ["warp", "ffd", "marker", "mesh", "vertex", "control", "point", "blend",
                 "soft", "edge", "calibrat", "project", "screen", "lens", "pose", "frustum",
                 "transform", "mapping", "uv", "grid", "deform", "modifier", "feed",
                 "position", "rotation", "matrix", "corner", "keystone"]


def extract_tokens(data: bytes, lo: int = 3, hi: int = 48):
    """Yield (offset, token_str) for length-prefixed ASCII tokens."""
    n = len(data)
    i = 0
    while i < n:
        L = data[i]
        if lo <= L <= hi and i + 1 + L <= n:
            tok = data[i + 1:i + 1 + L]
            if _WORD.match(tok):
                yield i, tok.decode("ascii")
                i += 1 + L
                continue
        i += 1


def floats_after(data: bytes, offset: int, count: int = 12):
    """Best-effort: read consecutive float32 starting near an offset."""
    out = []
    for k in range(count):
        pos = offset + 4 * k
        if pos + 4 <= len(data):
            (f,) = struct.unpack_from("<f", data, pos)
            out.append(round(f, 4))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Explore a Pixera .avp show-file schema.")
    ap.add_argument("path")
    ap.add_argument("--grep", default=None, help="comma-separated keywords (default: warp/marker/etc.)")
    ap.add_argument("--context", type=int, default=0, help="hexdump N bytes after first hit of each key")
    ap.add_argument("--top", type=int, default=60, help="show N most common tokens")
    args = ap.parse_args()

    data = pathlib.Path(args.path).read_bytes()
    keys = [k.strip().lower() for k in (args.grep.split(",") if args.grep else _DEFAULT_KEYS)]

    counts = collections.Counter()
    first_off = {}
    hits = collections.defaultdict(list)
    for off, tok in extract_tokens(data):
        counts[tok] += 1
        first_off.setdefault(tok, off)
        low = tok.lower()
        for k in keys:
            if k in low:
                if len(hits[k]) < 8:
                    hits[k].append((off, tok))

    print(f"file: {args.path}  size: {len(data)} bytes")
    print(f"unique tokens: {len(counts)}  total tokens: {sum(counts.values())}\n")

    print(f"[top {args.top} tokens by frequency]")
    for tok, c in counts.most_common(args.top):
        print(f"  {c:6d}  {tok}")

    print("\n[keyword matches]")
    for k in keys:
        toks = sorted({t for _, t in hits[k]})
        if toks:
            print(f"  {k:>10}: {', '.join(toks)}")

    if args.context:
        print("\n[context dumps]")
        for k in keys:
            if hits[k]:
                off, tok = hits[k][0]
                end = off + 1 + len(tok)
                print(f"  --- {tok!r} @ {off} (+floats after name) ---")
                print("   floats:", floats_after(data, end, 16))


if __name__ == "__main__":
    main()
