"""Repeatable room-ignition batches. Run from the repo root: python -m fire.batch."""
import argparse
import base64
from collections import defaultdict
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
        metrics = compute(result, _BUILDING, scenario)
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


def aggregate(building: dict, base: dict, records: list[dict]) -> dict:
    """Summarize successful runs without importing the simulator or mutating inputs."""
    records = [record for record in records if record["ok"]]
    by_room, by_door, by_floor = defaultdict(list), defaultdict(list), defaultdict(list)
    for record in records:
        ignition = record["ignition"]
        by_room[(ignition["floor"], ignition["room"])].append(record)
        for door in record["doors"]:
            by_door[(door["floor"], door["id"])].append(door)
        for heatmap in record["heatmaps"]:
            by_floor[heatmap["floor"]].append(heatmap)
    rooms = []
    for (floor, room), runs in by_room.items():
        times = [r["t90"] for r in runs]
        risk = (sum(t if t is not None else base["maxTime"] for t in times) / len(runs)
                if any(t is not None for t in times) else None)
        rooms.append({"id": room, "floor": floor, "riskT90": risk,
                      "riskTrapped": sum(r["trapped"] for r in runs) / len(runs), "n": len(runs)})
    doors = [{"id": door, "floor": floor,
              "meanWait": sum(d["waitPersonSeconds"] for d in values) / len(records),
              "peakQueue": max(d["peakQueue"] for d in values)}
             for (floor, door), values in by_door.items()]
    max_wait = max((d["meanWait"] for d in doors), default=0)
    max_queue = max((d["peakQueue"] for d in doors), default=0)
    for door in doors:
        door["score"] = round(100 * (0.7 * door["meanWait"] / (max_wait or 1)
                                     + 0.3 * door["peakQueue"] / (max_queue or 1)), 1)

    heatmaps = []
    for floor, maps in by_floor.items():
        header = {key: maps[0][key] for key in ("floor", "origin", "cell", "cols", "rows")}
        total = np.zeros(header["cols"] * header["rows"], dtype=float)
        for heatmap in maps:
            if any(heatmap[key] != value for key, value in header.items()):
                raise ValueError(f"Incompatible heatmap grids on floor {floor}")
            values = np.frombuffer(base64.b64decode(heatmap["d"]), dtype=np.uint8)
            if values.size != total.size:
                raise ValueError(f"Invalid heatmap size on floor {floor}")
            total += values
        mean = total / len(records)
        scaled = np.rint(mean * 100 / mean.max()).astype(np.uint8) if mean.size and mean.max() else mean.astype(np.uint8)
        heatmaps.append({**header, "d": base64.b64encode(scaled.tobytes()).decode("ascii")})

    room_info = {(f["id"], r["id"]): r for f in building["floors"] for r in f["rooms"]}
    door_info = {(f["id"], d["id"]): (f, d) for f in building["floors"] for d in f["doors"]}
    top = []
    for door in sorted(doors, key=lambda d: -d["score"])[:4]:
        if door["score"] <= 0:
            continue
        floor, info = door_info[(door["floor"], door["id"])]
        connected = [room_info.get((floor["id"], rid), {}) for rid in info["connects"]]
        stair = next((r for r in connected if r.get("type") == "stair"), None)
        if "outside" in info["connects"]:
            kind = "exit"
            exit_info = next((e for e in floor["exits"] if e["door"] == door["id"]), {})
            label = f"Exit {exit_info.get('name', door['id'])}"
        elif stair:
            kind, label = "stair", f"Stair {stair.get('group', stair['id'])} door"
        else:
            kind, label = "door", f"Door {door['id']}"
        why = (f"{label}: {door['peakQueue']} people queued at peak; "
               f"{door['meanWait']:,.0f} person-seconds of waiting on average across {len(records)} fires.")
        top.append({"kind": kind, "id": door["id"], "floor": door["floor"],
                    "score": door["score"], "why": why.encode("ascii", "replace").decode("ascii")})
    if rooms:
        def effective_time(room):
            return room["riskT90"] if room["riskT90"] is not None else base["maxTime"]

        max_time = max(effective_time(r) for r in rooms)
        max_trapped = max(1.0, max(r["riskTrapped"] for r in rooms))

        def room_score(room):
            return round(100 * (0.5 * effective_time(room) / (max_time or 1)
                                + 0.5 * room["riskTrapped"] / max_trapped), 1)

        worst = max(rooms, key=room_score)
        info = room_info[(worst["floor"], worst["id"])]
        evacuation = (f"90% out after {worst['riskT90']:.0f} s"
                      if worst["riskT90"] is not None else f"90% not out by {base['maxTime']:g} s in any run")
        why = (f"Fire in {info.get('name', worst['id'])} ({worst['id']}): "
               f"{worst['riskTrapped']:.1f} people trapped on average; {evacuation} ({worst['n']} fires).")
        top.append({"kind": "room", "id": worst["id"], "floor": worst["floor"],
                    "score": room_score(worst), "why": why.encode("ascii", "replace").decode("ascii")})
    return {"rooms": rooms, "doors": doors, "heatmaps": heatmaps,
            "top": sorted(top, key=lambda item: -item["score"])}


def run_many(building: dict, base: dict, ignitions: list[dict] | None = None,
             seeds=(1, 2, 3), workers: int | None = None, timeout_s: float = 7200,
             progress: bool = True) -> dict:
    """Build batch/v0 with room risks, chokepoint ranking and mean heatmaps.

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
            "note": "Simulated rule-based batch; fire and smoke model is illustrative.",
            "runs": [{key: record[key] for key in ("scenarioId", "seed", "ignition", "t90", "t100", "trapped")}
                     for record in records if record["ok"]],
            "failed": [{"scenarioId": record["scenarioId"], "error": record["error"]}
                       for record in records if not record["ok"]],
            **aggregate(building, base, records)}


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
    for item in batch["top"]:
        print(item["why"], flush=True)


if __name__ == "__main__":
    main()
