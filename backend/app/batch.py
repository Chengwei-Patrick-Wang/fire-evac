"""Batch routes (spec 7.4, 7.5), mounted under /api by main.py.

    POST /api/batch       {base, ignitions?: [{floor, room}], seeds?: [int]}  ->  {batchId}
    GET  /api/batch/{id}  ->  {"status": "running"}
                            | {"status": "error", "error": str, "traceback"?: str}
                            | the batch/v0 itself (also after a restart: data/runs/batch-{id}.json)

`base` is a scenario/v0 whose buildingId names the building. A batch is fire.batch.run_many: one
fire per ignition room (default: every room that is not a corridor or a stair, 40 sampled above
50) times each seed (default 1, 2, 3), rule-based agents only. run_many owns its process pool, so
batches run one at a time on a single worker thread of this process: no pool inside a pool, and
the request thread never waits for a batch.

While fire.batch does not import, S5's placeholder is served instead: the example batch
(contracts/batch.example.json, which carries "placeholder": true).
"""
import json
import multiprocessing
import os
import sys
import threading
import traceback
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Response

from .jobs import _json_default
from .store import BATCH_EXAMPLE, RUNS_DIR, SAFE_ID, building_or_404

router = APIRouter()

DEFAULT_SEEDS = [1, 2, 3]
# run_many's deadline (its own default is 2 h). Runs still unfinished after it are reported in
# the batch's `failed` list. The frontend stops polling after 30 min, so a hung batch should not
# hold the only batch thread much longer than that.
TIMEOUT_S = 1800

_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None
_jobs: dict[str, Future] = {}  # batchId -> the job; after a restart only the saved files remain


class BatchError(Exception):
    """A batch that finished with nothing to show. Its message goes to the client as it is."""


# ---------------------------------------------------------------- placeholder (S5)


def _fire_batch():
    """The fire.batch module once D's code imports, else None (the placeholder is served). A
    module that is there but broken is not hidden: other import errors print a warning."""
    try:
        import fire.batch as fire_batch
    except ImportError as e:
        if not (isinstance(e, ModuleNotFoundError) and e.name in ("fire", "fire.batch")):
            print(f"WARNING (batch): fire.batch does not import yet: {e}", file=sys.stderr)
        return None
    return fire_batch


def _example_batch() -> bytes:
    try:
        return BATCH_EXAMPLE.read_bytes()
    except OSError:
        raise HTTPException(404, "contracts/batch.example.json has not been generated yet")


# ------------------------------------------------------------------ the request


def _parse_body(body: Any) -> tuple[dict, list[dict] | None, list[int]]:
    """Check the POST body: (a copy of base, ignitions or None for run_many's default, seeds)."""
    if not isinstance(body, dict) or not isinstance(body.get("base"), dict):
        raise HTTPException(422, "body must be {base: scenario/v0, ignitions?: [{floor, room}], seeds?: [int]}")
    base = deepcopy(body["base"])
    if not base.get("buildingId"):
        raise HTTPException(422, "base.buildingId is required")
    fire = base.get("fire")
    if not isinstance(fire, dict) or not fire.get("type"):
        raise HTTPException(422, "base.fire.type is required (kitchen, bedroom, battery, trash or liquid)")

    ignitions = body.get("ignitions")
    if ignitions is not None:
        if not (
            isinstance(ignitions, list)
            and ignitions
            and all(isinstance(i, dict) and isinstance(i.get("floor"), str) and isinstance(i.get("room"), str)
                    for i in ignitions)
        ):
            raise HTTPException(422, "ignitions must be a non-empty list of {floor, room}")
        ignitions = [{"floor": i["floor"], "room": i["room"]} for i in ignitions]

    seeds = body.get("seeds")
    if seeds is None:
        seeds = list(DEFAULT_SEEDS)
    elif not (
        isinstance(seeds, list) and seeds and all(isinstance(s, int) and not isinstance(s, bool) for s in seeds)
    ):
        raise HTTPException(422, "seeds must be a non-empty list of integers")
    return base, ignitions, seeds


def _check_ignitions(building: dict, ignitions: list[dict]) -> None:
    rooms = {(f["id"], r["id"]) for f in building["floors"] for r in f["rooms"]}
    unknown = [f"{i['floor']}/{i['room']}" for i in ignitions if (i["floor"], i["room"]) not in rooms]
    if unknown:
        raise HTTPException(422, f"no such room in building {building['id']!r}: {', '.join(unknown[:5])}")


# --------------------------------------------------------------------- the job


def _batch_path(batch_id: str) -> Path:
    return RUNS_DIR / f"batch-{batch_id}.json"


def _nothing_to_show(batch: dict) -> str:
    failed = batch.get("failed") or []
    if not failed:
        return "the batch ran nothing: there is no room to start a fire in"
    first = failed[0]
    return f"all {len(failed)} runs failed; first: {first.get('scenarioId')}: {first.get('error')}"


def _run_job(batch_id: str, building: dict, base: dict, ignitions: list[dict] | None, seeds: list[int]) -> str:
    """On the batch thread: run_many, then save data/runs/batch-{id}.json. Returns the saved path."""
    import fire.batch as fire_batch  # looked up here, at call time (the smoke test swaps run_many)

    batch = fire_batch.run_many(building, base, ignitions=ignitions, seeds=seeds, workers=None, timeout_s=TIMEOUT_S)
    if not batch.get("runs"):  # every run failed (their errors are in `failed`): not a result
        raise BatchError(_nothing_to_show(batch))
    batch["id"] = batch_id

    text = json.dumps(batch, default=_json_default, separators=(",", ":"), allow_nan=False)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    final = _batch_path(batch_id)
    tmp = final.with_name(final.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, final)  # atomic: readers never see a half-written batch
    return str(final)


def _submit(batch_id: str, building: dict, base: dict, ignitions: list[dict] | None, seeds: list[int]) -> None:
    global _executor
    with _lock:
        if _executor is None:  # one thread: run_many owns the process pool, one batch at a time
            _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="batch")
        _jobs[batch_id] = _executor.submit(_run_job, batch_id, building, base, ignitions, seeds)


def _error_state(exc: BaseException) -> dict:
    if isinstance(exc, BatchError):
        return {"status": "error", "error": str(exc)}
    return {
        "status": "error",
        "error": f"{type(exc).__name__}: {exc}",
        "traceback": "".join(traceback.format_exception(exc)).strip()[-2000:],
    }


def shutdown() -> None:
    """App shutdown: drop queued batches and stop the running one, so Ctrl+C does not wait for
    minutes of simulation. run_many sees its workers die and returns."""
    global _executor
    with _lock:
        executor, _executor = _executor, None
        running = any(not f.done() for f in _jobs.values())
    if executor is None:
        return
    executor.shutdown(wait=False, cancel_futures=True)
    if running:
        # these are run_many's pool workers (and the run pool's, which jobs.shutdown stops anyway)
        for p in multiprocessing.active_children():
            try:
                p.terminate()
            except Exception:
                pass


# ---------------------------------------------------------------------- routes


@router.post("/batch")
def post_batch(body: dict[str, Any] | None = Body(default=None)):
    """Start a batch and return {batchId}; poll GET /batch/{batchId}.

    Body: {base, ignitions?: [{floor, room}], seeds?: [int]}. `base` is a scenario/v0 with
    buildingId and fire.type; its brain is forced to "rules", and a missing id, seed or maxTime
    gets the sim's own default. Every ignition is a room of the building (default: every room
    except corridors and stairs, 40 sampled above 50); seeds default to [1, 2, 3].
    404: unknown building. 422: a malformed body or an ignition room that does not exist.
    """
    if _fire_batch() is None:  # S5's placeholder: every batch is the example batch
        return {"batchId": json.loads(_example_batch()).get("id", "example-batch")}

    base, ignitions, seeds = _parse_body(body)
    building = building_or_404(str(base["buildingId"]))
    if ignitions is not None:
        _check_ignitions(building, ignitions)

    base["brain"] = "rules"  # batches and what-ifs are rule-based only (spec 7.4)
    # What the sim defaults to, spelled out because run_many's ids and its ranking index them
    base.setdefault("id", f"{building['id']}-batch")
    base.setdefault("seed", 0)
    base.setdefault("maxTime", 600)

    batch_id = uuid.uuid4().hex[:12]
    _submit(batch_id, deepcopy(building), base, ignitions, seeds)  # a copy: the sim never touches the cached building
    return {"batchId": batch_id}


@router.get("/batch/{batch_id}")
def get_batch(batch_id: str):
    """{"status": "running"}, {"status": "error", "error": ...}, or the batch/v0 itself."""
    if SAFE_ID.match(batch_id):
        with _lock:
            fut = _jobs.get(batch_id)
        if fut is not None:
            if not fut.done():
                return {"status": "running"}
            if fut.cancelled():
                return {"status": "error", "error": "batch was cancelled"}
            exc = fut.exception()
            if exc is not None:
                return _error_state(exc)
        path = _batch_path(batch_id)  # also found after a server restart
        if path.is_file():
            return Response(path.read_bytes(), media_type="application/json")
        if _fire_batch() is None:  # S5's placeholder: every batch is the example batch
            return Response(_example_batch(), media_type="application/json")
    raise HTTPException(404, f"batch {batch_id!r} not found")
