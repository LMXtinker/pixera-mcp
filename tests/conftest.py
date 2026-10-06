"""Make ``src/`` and ``tests/`` importable whether run via pytest or directly.

The Pixera API JSON is not part of this repository (it belongs to AV Stumpfl). Tests
that need it (the mock validates every request against it) are skipped when no
Pixera install is found and PIXERA_API_JSON is not set.
"""

import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _p in (_ROOT / "src", _ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from pixera_mcp.api_index import ApiIndexUnavailable, find_api_json  # noqa: E402

collect_ignore: list[str] = []
try:
    find_api_json()
except ApiIndexUnavailable as _exc:
    print(f"\n[pixera-mcp] Skipping API-index tests: {_exc}\n")
    collect_ignore = ["test_api_index.py", "test_show.py", "test_framing.py", "test_integration.py"]
