"""FastAPI app (spec 7.5). From the repo root: uvicorn backend.app.main:app --reload

All routes live under /api. Buildings are files (contracts example, data/buildings,
data/private); runs go through the process pool in jobs.py and land in data/runs/.
Shared helpers are in store.py; batch.py, report.py and trace.py each hold one router,
registered once at the bottom of this file.
"""
import io
import json
import sys
import threading
import uuid
from contextlib import asynccontextmanager, redirect_stderr
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from . import batch, jobs, report, trace
from .store import (
    BUILDINGS_DIR,
    PRIVATE_DIR,
    ROOT,
    SAFE_ID,
    building_or_404,
    json_response,
    load_buildings,
)

WARNING_PREFIX = "WARNING (normalize):"  # what buildings.normalize prints to stderr


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    batch.shutdown()
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


# ---------------------------------------------------------------- buildings


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/buildings")
def list_buildings():
    out = []
    for b, private in load_buildings().values():
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
    return json_response(building_or_404(building_id))


_normalize_lock = threading.Lock()  # redirect_stderr swaps the process-wide sys.stderr


def _normalize(plan_to_building, plan: dict, wall: float | None) -> tuple[dict, list[str]]:
    """plan_to_building(plan, wall) -> (building, the normalizer's 'WARNING (normalize):' lines)."""
    buf = io.StringIO()
    try:
        with _normalize_lock, redirect_stderr(buf):
            building = plan_to_building(plan, wall)
    finally:
        text = buf.getvalue()
        if text:
            sys.stderr.write(text)  # captured, but still in the server log
    return building, [ln for ln in text.splitlines() if ln.startswith(WARNING_PREFIX)]


@router.post("/buildings/from-plan")
def building_from_plan(
    plan: dict[str, Any] = Body(...), wall: float | None = None, public: bool = False
):
    """plan/v0 in, building/v0 saved, {id, warnings} out.

    The building goes to data/private/{id}.json, which is gitignored, so a traced UMass plan
    can never be committed by accident; public=true saves it to data/buildings/{id}.json
    instead. warnings are the normalizer's "WARNING (normalize):" stderr lines.
    """
    if plan.get("version") != "plan/v0":
        raise HTTPException(422, f"plan.version must be 'plan/v0', got {plan.get('version')!r}")
    try:
        from buildings.normalize import plan_to_building  # lazy: may not have landed yet
    except ImportError as e:
        raise HTTPException(501, f"buildings.normalize is not available yet: {e}")
    if not plan.get("id"):
        plan["id"] = "plan-" + uuid.uuid4().hex[:8]
    try:
        building, warnings = _normalize(plan_to_building, plan, wall)
    except Exception as e:
        raise HTTPException(422, f"could not normalize plan: {type(e).__name__}: {e}")
    building_id = str(building.get("id") or plan["id"])
    if not SAFE_ID.match(building_id):
        raise HTTPException(422, "plan id may only use letters, digits, '.', '-' and '_'")
    building["id"] = building_id

    folder = BUILDINGS_DIR if public else PRIVATE_DIR
    other = (PRIVATE_DIR if public else BUILDINGS_DIR) / f"{building_id}.json"
    if other.is_file():  # the listing lets data/private win, so say which copy is served
        warnings.append(
            f"WARNING (store): {other.relative_to(ROOT).as_posix()} has the same id; "
            f"/api/buildings serves the data/private copy"
        )
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / f"{building_id}.json"
    tmp = folder / f"{building_id}.json.tmp"
    tmp.write_text(json.dumps(building, separators=(",", ":")), encoding="utf-8")
    tmp.replace(final)
    return {"id": building_id, "warnings": warnings}


# --------------------------------------------------------------------- runs


@router.post("/runs")
def post_run(scenario: dict[str, Any] = Body(...)):
    """Body is a scenario/v0 whose buildingId names a listed building."""
    building_id = scenario.get("buildingId")
    if not building_id:
        raise HTTPException(422, "scenario.buildingId is required")
    building = building_or_404(str(building_id))
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


# Batch (A4), report (A7) and the tracer's first pass (A8): one router each. This is the only
# place that registers them.
router.include_router(batch.router)
router.include_router(report.router)
router.include_router(trace.router)

app.include_router(router)
