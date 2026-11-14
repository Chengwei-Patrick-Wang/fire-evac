"""Report route (spec 7.5), mounted under /api by main.py.

    POST /api/report  {runId} | {batchId}  ->  {markdown}       ?refresh=1 writes a new one

The card is backend.llm.features.report_card: every number built in code, the headline and fixes
from the LLM, or a template when the LLM is off, down or slow. AI-written cards are cached as
data/runs/report-{id}.md (id: the run's or batch's own id) and served from there until ?refresh=1;
template cards are not cached, so the next request tries the model again. A building from
data/private never goes to the model: its card is always the template. The model call can take a
while (up to 45 s per model, and a second model after that), so give the request time.

Where the result is looked up:
    runId    data/runs/{runId}.json (an API run); else the newest run in data/runs whose scenarioId
             is runId (the frontend keys live runs by their scenario id); else an entry of the demo
             index (frontend/public/demo/index.json); else contracts/run.example.json by its id.
    batchId  what GET /api/batch/{batchId} serves; else the demo index; else
             contracts/batch.example.json by its id.
409 while the run or batch is running or after it failed, 404 for an unknown id, 422 for a bad body.
"""
import json
import os
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Response

from ..llm.features import report_card
from . import jobs
from .store import BATCH_EXAMPLE, ROOT, RUNS_DIR, SAFE_ID, load_buildings

router = APIRouter()

DEMO_DIR = ROOT / "frontend" / "public" / "demo"
RUN_EXAMPLE = ROOT / "contracts" / "run.example.json"


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _head_field(path: Path, field: str) -> str | None:
    """A top-level string field from the first 4 KB of a JSON file: run files are megabytes, and
    their ids come first."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096).decode("utf-8", "replace")
    except OSError:
        return None
    m = re.search(r'"%s"\s*:\s*"([^"]*)"' % re.escape(field), head)
    return m.group(1) if m else None


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _demo(section: str, result_id: str) -> dict | None:
    """The file a demo-index entry with this id points at (public data, as the static site has it)."""
    index = _read(DEMO_DIR / "index.json") or {}
    for entry in index.get(section) or []:
        if isinstance(entry, dict) and entry.get("id") == result_id and isinstance(entry.get("file"), str):
            path = (DEMO_DIR / entry["file"]).resolve()
            if DEMO_DIR.resolve() in path.parents:
                return _read(path)
    return None


def _example(path: Path, result_id: str) -> dict | None:
    return _read(path) if path.is_file() and _head_field(path, "id") == result_id else None


def _run_by_scenario(scenario_id: str) -> dict | None:
    paths = [p for p in RUNS_DIR.glob("*.json") if not p.name.startswith(("batch-", "report-"))]
    for path in sorted(paths, key=_mtime, reverse=True):
        if _head_field(path, "scenarioId") == scenario_id:
            return _read(path)
    return None


def _load_run(run_id: str) -> dict:
    state = jobs.get(run_id)
    if isinstance(state, dict):
        if state.get("status") == "running":
            raise HTTPException(409, f"run {run_id!r} is still running")
        raise HTTPException(409, f"run {run_id!r} failed: {state.get('error')}")
    run = _read(state) if isinstance(state, Path) else None
    for find in (_run_by_scenario, lambda i: _demo("runs", i), lambda i: _example(RUN_EXAMPLE, i)):
        if run is None:
            run = find(run_id)
    if run is None:
        raise HTTPException(404, f"run {run_id!r} not found")
    return run


def _load_batch(batch_id: str) -> dict:
    from . import batch as batch_api

    try:
        state = batch_api.get_batch(batch_id)  # in-memory state, the saved file, or S5's placeholder
    except HTTPException as e:
        if e.status_code != 404:
            raise
        state = None
    if isinstance(state, dict):
        if state.get("status") == "running":
            raise HTTPException(409, f"batch {batch_id!r} is still running")
        raise HTTPException(409, f"batch {batch_id!r} failed: {state.get('error')}")
    batch = None
    if isinstance(state, Response):
        try:
            batch = json.loads(state.body)
        except ValueError:
            batch = None
    for find in (lambda i: _demo("batches", i), lambda i: _example(BATCH_EXAMPLE, i)):
        if batch is None:
            batch = find(batch_id)
    if not isinstance(batch, dict):
        raise HTTPException(404, f"batch {batch_id!r} not found")
    return batch


def _building(result: dict) -> tuple[dict, bool]:
    """(building, private) for the result's buildingId; ({}, False) if it is nowhere (names then
    fall back to ids)."""
    building_id = str(result.get("buildingId") or "")
    hit = load_buildings().get(building_id)
    if hit is not None:
        return hit
    return _demo("buildings", building_id) or {}, False


def _save(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


@router.post("/report")
def post_report(body: dict[str, Any] | None = Body(default=None), refresh: bool = False):
    """The report card of a run or a batch as markdown: {markdown}. See the module docstring."""
    if not isinstance(body, dict) or ("runId" in body) == ("batchId" in body):
        raise HTTPException(422, "body must be {runId} or {batchId}")
    requested = body.get("runId", body.get("batchId"))
    if not isinstance(requested, str) or not SAFE_ID.match(requested):
        raise HTTPException(422, "the id may only use letters, digits, '.', '-' and '_'")
    result = _load_run(requested) if "runId" in body else _load_batch(requested)

    own_id = str(result.get("id") or "")
    cache = RUNS_DIR / f"report-{own_id if SAFE_ID.match(own_id) else requested}.md"
    if not refresh and cache.is_file():
        try:
            return {"markdown": cache.read_text(encoding="utf-8")}
        except OSError:
            pass  # unreadable: write a new one
    building, private = _building(result)
    markdown, ai_written = report_card(result, building, allow_llm=not private)
    if ai_written:
        try:
            _save(cache, markdown)
        except OSError:
            pass  # serving it matters more than caching it
    return {"markdown": markdown}
