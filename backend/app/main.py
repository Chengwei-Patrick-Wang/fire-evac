"""FastAPI app (spec 7.5). From the repo root: uvicorn backend.app.main:app --reload

All routes live under /api. Buildings are files (contracts example, data/buildings,
data/private); runs go through the process pool in jobs.py and land in data/runs/.
"""
import json
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from . import jobs

ROOT = Path(__file__).resolve().parents[2]
BUILDING_EXAMPLE = ROOT / "contracts" / "building.example.json"
BATCH_EXAMPLE = ROOT / "contracts" / "batch.example.json"
BUILDINGS_DIR = ROOT / "data" / "buildings"
PRIVATE_DIR = ROOT / "data" / "private"  # gitignored; also where from-plan buildings are saved
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    jobs.shutdown()


app = FastAPI(
    title="Fire evac sim API",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.add_middleware(  # dev: allow every origin
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
router = APIRouter(prefix="/api")


def _json(obj: Any) -> Response:
    """Plain json.dumps is much faster than FastAPI's encoder on big coordinate lists."""
    return Response(json.dumps(obj, separators=(",", ":")), media_type="application/json")


# ---------------------------------------------------------------- buildings

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


def _buildings() -> dict[str, tuple[dict, bool]]:
    """id -> (building, private). Later sources override earlier ones with the same id."""
    sources = [(BUILDING_EXAMPLE, False)]
    sources += [(p, False) for p in sorted(BUILDINGS_DIR.glob("*.json"))]
    sources += [(p, True) for p in sorted(PRIVATE_DIR.glob("*.json"))]
    found: dict[str, tuple[dict, bool]] = {}
    for path, private in sources:
        building = _load_building(path)
        if building is not None:
            found[str(building["id"])] = (building, private)
    return found


def _building_or_404(building_id: str) -> dict:
    hit = _buildings().get(building_id)
    if hit is None:
        raise HTTPException(404, f"building {building_id!r} not found")
    return hit[0]


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/buildings")
def list_buildings():
    out = []
    for b, private in _buildings().values():
        item = {
            "id": b["id"],
            "name": b.get("name") or b["id"],
            "source": b.get("source"),
            "floors": len(b["floors"]),
        }
        if private:
            item["private"] = True
        out.append(item)
    return out


@router.get("/buildings/{building_id}")
def get_building(building_id: str):
    return _json(_building_or_404(building_id))


@router.post("/buildings/from-plan")
def building_from_plan(plan: dict[str, Any] = Body(...), wall: float | None = None):
    """plan/v0 in, building/v0 saved to data/private/{id}.json, {id} out."""
    try:
        from buildings.normalize import plan_to_building  # lazy: may not have landed yet
    except ImportError as e:
        raise HTTPException(501, f"buildings.normalize is not available yet: {e}")
    plan.setdefault("id", "plan-" + uuid.uuid4().hex[:8])
    try:
        building = plan_to_building(plan, wall)
    except Exception as e:
        raise HTTPException(422, f"could not normalize plan: {type(e).__name__}: {e}")
    building_id = str(building.get("id") or plan["id"])
    if not SAFE_ID.match(building_id):
        raise HTTPException(422, "plan id may only use letters, digits, '.', '-' and '_'")
    building["id"] = building_id
    # data/private/ is gitignored, so a traced UMass plan can never be committed by accident
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    final = PRIVATE_DIR / f"{building_id}.json"
    tmp = PRIVATE_DIR / f"{building_id}.json.tmp"
    tmp.write_text(json.dumps(building, separators=(",", ":")), encoding="utf-8")
    tmp.replace(final)
    return {"id": building_id}


# --------------------------------------------------------------------- runs


@router.post("/runs")
def post_run(scenario: dict[str, Any] = Body(...)):
    """Body is a scenario/v0 whose buildingId names a listed building."""
    building_id = scenario.get("buildingId")
    if not building_id:
        raise HTTPException(422, "scenario.buildingId is required")
    building = _building_or_404(str(building_id))
    return {"runId": jobs.submit(building, scenario)}


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    """{"status": "running"}, {"status": "error", "error": ...}, or the run/v0 itself."""
    state = jobs.get(run_id) if SAFE_ID.match(run_id) else None
    if state is None:
        raise HTTPException(404, f"run {run_id!r} not found")
    if isinstance(state, Path):
        return Response(state.read_bytes(), media_type="application/json")
    return state


# ----------------------------------------------------- placeholders (batch etc.)


def _example_batch() -> bytes:
    try:
        return BATCH_EXAMPLE.read_bytes()
    except OSError:
        raise HTTPException(404, "contracts/batch.example.json has not been generated yet")


@router.post("/batch")
def post_batch():
    """Placeholder until fire.batch lands: every batch is the example batch."""
    return {"batchId": json.loads(_example_batch()).get("id", "example-batch")}


@router.get("/batch/{batch_id}")
def get_batch(batch_id: str):
    return Response(_example_batch(), media_type="application/json")


@router.post("/report")
def post_report():
    raise HTTPException(501, "not implemented yet")


@router.post("/trace/propose")
def post_trace_propose():
    raise HTTPException(501, "not implemented yet")


app.include_router(router)
