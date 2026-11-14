"""Repeatable room-ignition batches. Run from the repo root: python -m fire.batch."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed, TimeoutError
from concurrent.futures.process import BrokenProcessPool
from copy import deepcopy
import json
import multiprocessing
import os
from pathlib import Path
import time

import numpy as np
from shapely.geometry import Polygon

_BUILDING = None


def _init(building: dict):
    global _BUILDING
    _BUILDING = building


def _ignitions(building: dict, base: dict, rooms: int | None = None) -> list[dict]:
    candidates = [{"floor": floor["id"], "room": room["id"]}
                  for floor in building["floors"] for room in floor["rooms"]
                  if room.get("type") not in ("corridor", "stair")]
    count = rooms if rooms is not None else (40 if len(candidates) > 50 else len(candidates))
    if count < 0:
        raise ValueError("rooms must be non-negative")
    if count < len(candidates):
        indexes = sorted(np.random.default_rng(base["seed"]).choice(len(candidates), count, replace=False))
        return [candidates[i] for i in indexes]
    return candidates


def _tasks(building: dict, base: dict, ignitions: list[dict], seeds) -> list[dict]:
    rooms = {(floor["id"], room["id"]): room
             for floor in building["floors"] for room in floor["rooms"]}
    tasks = []
    for ignition in ignitions:
        room = rooms[(ignition["floor"], ignition["room"])]
        point = Polygon(room["polygon"]).representative_point()
        for seed in seeds:
            scenario = deepcopy(base)
            scenario.update(id=f"{base['id']}-{ignition['room']}-s{seed}", seed=int(seed), brain="rules")
            scenario["fire"].update(floor=ignition["floor"], room=ignition["room"], x=point.x, y=point.y)
            tasks.append({"scenario": scenario, "ignition": dict(ignition)})
    return tasks


def _run_one(task: dict) -> dict:
    """Catch errors as strings, so even unpicklable exceptions cross the pool."""
    scenario = task["scenario"]
    try:
        from sim.run import run
        from fire.model import FireModel
        from fire.metrics import compute

        result = run(_BUILDING, scenario, FireModel(_BUILDING, scenario))
        metrics = compute(result, _BUILDING)
        return {"ok": True, "scenarioId": scenario["id"], "seed": scenario["seed"],
                "ignition": task["ignition"], "t90": metrics["t90"], "t100": metrics["t100"],
                "trapped": metrics["trapped"],
                "doors": [{key: door[key] for key in ("id", "floor", "peakQueue", "waitPersonSeconds")}
                          for door in metrics["doors"]], "heatmaps": metrics["heatmaps"]}
    except Exception as error:
        return {"ok": False, "scenarioId": scenario["id"], "error": repr(error)}


def _records(building, tasks, workers, timeout_s, progress):
    """Return records in ignition order, then seed order, regardless of completion."""
    records = {}
    started = time.perf_counter()

    def save(index, record):
        records[index] = record
        if progress:
            sc = tasks[index]["scenario"]
            outcome = f"t90={record['t90']}" if record["ok"] else f"failed={record['error']}"
            print(f"[{len(records)}/{len(tasks)}] {sc['fire']['room']} seed {sc['seed']} "
                  f"{outcome} ({time.perf_counter() - started:.1f} s)", flush=True)

    def failed(index, error):
        return {"ok": False, "scenarioId": tasks[index]["scenario"]["id"], "error": error}

    if workers == 1 or len(tasks) <= 1:
        _init(building)
        for index, task in enumerate(tasks):
            if time.perf_counter() - started >= timeout_s:
                save(index, failed(index, "TimeoutError: batch deadline exceeded"))
            else:
                save(index, _run_one(task))
    else:
        pool = ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"),
                                   initializer=_init, initargs=(building,))
        futures = {}
        aborted = False
        try:
            for index, task in enumerate(tasks):
                futures[pool.submit(_run_one, task)] = index
            remaining = max(0, timeout_s - (time.perf_counter() - started))
            for future in as_completed(futures, timeout=remaining):
                save(futures[future], future.result())
        except (TimeoutError, BrokenProcessPool) as error:
            aborted = True
            # Harvest results already finished before cancelling/terminating.
            for future, index in futures.items():
                if index not in records and future.done() and not future.cancelled():
                    try:
                        save(index, future.result())
                    except Exception as worker_error:
                        save(index, failed(index, repr(worker_error)))
            for future in futures:
                future.cancel()
            for child in list((pool._processes or {}).values()):
                child.terminate()
            for index in range(len(tasks)):
                if index not in records:
                    save(index, failed(index, repr(error)))
        finally:
            pool.shutdown(wait=not aborted, cancel_futures=aborted)
    return [records[i] for i in range(len(tasks))]


def run_many(building: dict, base: dict, ignitions: list[dict] | None = None,
             seeds=(1, 2, 3), workers: int | None = None, timeout_s: float = 7200,
             progress: bool = True) -> dict:
    """Build batch/v0; ranking and heatmap aggregation follow in D7.

    Inline execution (one worker or one task) checks the deadline between runs;
    a running inline simulation cannot be interrupted by this deadline.
    """
    if workers is None:
        workers = min(61, max(1, (os.cpu_count() or 1) - 1))
    if workers < 1 or timeout_s <= 0:
        raise ValueError("workers and timeout_s must be positive")
    if ignitions is None:
        ignitions = _ignitions(building, base)
    tasks = _tasks(building, base, ignitions, sorted(set(seeds)))
    records = _records(building, tasks, workers, timeout_s, progress)
    return {"version": "batch/v0", "id": f"batch-{building['id']}-{base['id']}",
            "buildingId": building["id"], "base": deepcopy(base),
            "runs": [{key: record[key] for key in ("scenarioId", "seed", "ignition", "t90", "t100", "trapped")}
                     for record in records if record["ok"]],
            "failed": [{"scenarioId": record["scenarioId"], "error": record["error"]}
                       for record in records if not record["ok"]],
            "rooms": [], "doors": [], "heatmaps": [], "top": []}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("building", type=Path)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--rooms", type=int)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    building = json.loads(args.building.read_text(encoding="utf-8"))
    base = json.loads(args.scenario.read_text(encoding="utf-8"))
    seeds = tuple(int(seed) for seed in args.seeds.split(","))
    started = time.perf_counter()
    batch = run_many(building, base, _ignitions(building, base, args.rooms), seeds, args.workers)
    out = args.out if args.out is not None else Path(f"data/runs/batch-{building['id']}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(batch, separators=(",", ":")), encoding="utf-8")
    print(f"runtime {time.perf_counter() - started:.1f} s", flush=True)
    print(f"wrote {out} ({len(batch['runs'])} runs, {len(batch['failed'])} failed)", flush=True)


if __name__ == "__main__":
    main()
