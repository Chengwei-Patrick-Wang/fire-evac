"""Run jobs: sim + metrics in a process pool, results saved to data/runs/{runId}.json.

`_worker` is a top-level function so it pickles under spawn (Windows, macOS). sim, fire
and buildings are imported inside it, so the API starts before those modules exist.
Keep this module light: every pool process imports it.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import threading
import traceback
import uuid
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "data" / "runs"

_lock = threading.Lock()
_pool: ProcessPoolExecutor | None = None
_futures: dict[str, Future] = {}


def _json_default(o):
    """Let numpy scalars and arrays through json.dumps."""
    import numpy as np

    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    raise TypeError(f"{type(o).__name__} is not JSON serializable")


def _worker(run_id: str, building: dict, scenario: dict) -> str:
    """Runs in a pool process: sim, then metrics, then save. Returns the saved path."""
    from fire.metrics import compute as compute_metrics  # lazy: may not have landed yet
    from sim.run import run as run_sim

    run = run_sim(building, scenario)  # fire=None: the sim picks its default fire model
    run["id"] = run_id
    # compute() returns the full metrics dict (or just the extras): merge handles both
    run["metrics"] = {**(run.get("metrics") or {}), **(compute_metrics(run, building) or {})}

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(run, default=_json_default, separators=(",", ":"), allow_nan=False)
    final = RUNS_DIR / f"{run_id}.json"
    tmp = RUNS_DIR / f"{run_id}.json.tmp"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, final)  # atomic: readers never see a half-written run
    return str(final)


def _init_worker() -> None:
    """Pool process start-up: exit when the API process dies. A hard kill (Task Manager,
    closed terminal) would otherwise leave idle workers behind for good."""
    try:
        parent = multiprocessing.parent_process()
        if parent is not None:
            threading.Thread(target=lambda: (parent.join(), os._exit(0)), daemon=True).start()
    except Exception:
        pass


def _get_pool() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        workers = min(61, max(1, (os.cpu_count() or 2) - 1))  # 61 = Windows limit
        _pool = ProcessPoolExecutor(
            max_workers=workers,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_init_worker,
            # fresh interpreter per run: edited sim/fire code is picked up without a
            # server restart, and nothing carries over between runs (costs about 0.5 s)
            max_tasks_per_child=1,
        )
    return _pool


def submit(building: dict, scenario: dict) -> str:
    """Queue a run and return its runId."""
    run_id = uuid.uuid4().hex[:12]
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        try:
            fut = _get_pool().submit(_worker, run_id, building, scenario)
        except BrokenProcessPool:  # a worker died hard (native crash): start a fresh pool
            _reset_pool_locked()
            fut = _get_pool().submit(_worker, run_id, building, scenario)
        _futures[run_id] = fut
    return run_id


def get(run_id: str) -> dict | Path | None:
    """State of a run.

    dict -> {"status": "running"} or {"status": "error", "error": ..., "traceback": ...}
    Path -> the finished run file (also found after a server restart)
    None -> unknown run id
    """
    with _lock:
        fut = _futures.get(run_id)
    if fut is not None:
        if not fut.done():
            return {"status": "running"}
        if fut.cancelled():
            return {"status": "error", "error": "run was cancelled"}
        exc = fut.exception()
        if exc is not None:
            return {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": _traceback_of(exc),
            }
    path = RUNS_DIR / f"{run_id}.json"
    return path if path.is_file() else None


def _traceback_of(exc: BaseException) -> str:
    remote = getattr(exc.__cause__, "tb", None)  # _RemoteTraceback from the pool process
    text = remote or "".join(traceback.format_exception(exc))
    return text.strip().strip('"').strip()[-2000:]  # the pool wraps remote text in """


def _reset_pool_locked() -> None:
    global _pool
    pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


def shutdown() -> None:
    """Stop the pool (app shutdown). Kills running jobs so Ctrl+C does not hang."""
    global _pool
    with _lock:
        pool, _pool = _pool, None
    if pool is None:
        return
    procs = list((getattr(pool, "_processes", None) or {}).values())  # private API, 3.12
    pool.shutdown(wait=False, cancel_futures=True)
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
