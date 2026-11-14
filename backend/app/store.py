"""Shared API helpers: repo paths, building files and JSON responses.

Routers import from here, never from main.py, so main.py can import every router without a
circular import. Keep sim, fire and buildings out of this module (they load lazily, where used).
"""
import json
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Response

from .jobs import RUNS_DIR  # noqa: F401  (re-exported: batch and report results are saved next to the runs)

ROOT = Path(__file__).resolve().parents[2]
BUILDING_EXAMPLE = ROOT / "contracts" / "building.example.json"
BATCH_EXAMPLE = ROOT / "contracts" / "batch.example.json"
BUILDINGS_DIR = ROOT / "data" / "buildings"  # public buildings: committed once chosen for the demo
PRIVATE_DIR = ROOT / "data" / "private"  # gitignored: the default home of from-plan buildings
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def json_response(obj: Any) -> Response:
    """Plain json.dumps is much faster than FastAPI's encoder on big coordinate lists."""
    return Response(json.dumps(obj, separators=(",", ":")), media_type="application/json")


_cache: dict[Path, tuple[int, dict]] = {}  # path -> (mtime_ns, parsed building)


def _load_building(path: Path) -> dict | None:
    try:
        mtime = path.stat().st_mtime_ns
        hit = _cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # missing, half-written or not JSON: skip it
    ok = (
        isinstance(data, dict)
        and "id" in data
        and isinstance(data.get("floors"), list)
        and str(data.get("version", "building/v0")).startswith("building/")
    )
    if not ok:
        return None
    _cache[path] = (mtime, data)
    return data


def load_buildings() -> dict[str, tuple[dict, bool]]:
    """id -> (building, private). Later sources override earlier ones with the same id:
    the contracts example, then data/buildings, then data/private."""
    sources = [(BUILDING_EXAMPLE, False)]
    sources += [(p, False) for p in sorted(BUILDINGS_DIR.glob("*.json"))]
    sources += [(p, True) for p in sorted(PRIVATE_DIR.glob("*.json"))]
    found: dict[str, tuple[dict, bool]] = {}
    for path, private in sources:
        building = _load_building(path)
        if building is not None:
            found[str(building["id"])] = (building, private)
    return found


def building_or_404(building_id: str) -> dict:
    hit = load_buildings().get(building_id)
    if hit is None:
        raise HTTPException(404, f"building {building_id!r} not found")
    return hit[0]
