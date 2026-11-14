"""Repeatable room-ignition batches. Run from the repo root: python -m fire.batch."""
import argparse
import base64
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed, TimeoutError
from concurrent.futures.process import BrokenProcessPool
from copy import deepcopy
import json
import math
import multiprocessing
import os
from pathlib import Path
import re
from statistics import median
import time

import numpy as np
from shapely.geometry import Polygon

_BUILDING = None


def _workers(workers):
    return workers if workers is not None else min(61, max(1, (os.cpu_count() or 1) - 1))


def plan_rooms(budget_s, pilot_s, seeds, workers, variants=0, contention=2.0) -> int:
    """Estimate room count with a conservative pool-contention allowance."""
    if (not all(math.isfinite(value) and value > 0
                for value in (budget_s, pilot_s, workers, contention))
            or not len(seeds) or variants < 0):
        raise ValueError("budget, pilot, workers, contention and seeds must be positive; variants non-negative")
    return max(1, math.floor(budget_s * workers /
                            (pilot_s * contention * len(seeds) * (1 + variants))))


def apply_overrides(base: dict, occupants: int | None = None, fire_type: str | None = None) -> dict:
    """A copy of `base` with the `--occupants` and `--fire-type` overrides applied.

    Occupant overrides keep the mobility mix and replace any per-room counts; a fire type
    replaces the preset and removes a custom growth class. A bad value raises ValueError.
    """
    result = deepcopy(base)
    if occupants is not None:
        if occupants < 1:
            raise ValueError("--occupants must be positive")
        result["occupants"] = {"total": occupants, "mix": result["occupants"]["mix"]}
    if fire_type is not None:
        from fire.presets import fire_params
        result["fire"]["type"] = fire_type
        result["fire"].pop("growth", None)
        fire_params(result["fire"])
    return result


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
    started = time.perf_counter()
    try:
        from sim.run import run
        from fire.model import FireModel
        from fire.metrics import compute

        result = run(_BUILDING, scenario, FireModel(_BUILDING, scenario))
        metrics = compute(result, _BUILDING, scenario)
        return {"ok": True, "wallS": time.perf_counter() - started,
                "scenarioId": scenario["id"], "seed": scenario["seed"],
                "ignition": task["ignition"], "t90": metrics["t90"], "t100": metrics["t100"],
                "trapped": metrics["trapped"], "exitCounts": metrics["exitCounts"],
                "dosed": metrics["exposure"]["dosed"],
                "smokeSeconds": metrics["exposure"]["personSecondsInSmoke"],
                "doors": [{key: door[key] for key in ("id", "floor", "peakQueue", "waitPersonSeconds", "smokeWait")}
                          for door in metrics["doors"]], "heatmaps": metrics["heatmaps"]}
    except Exception as error:
        return {"ok": False, "wallS": time.perf_counter() - started,
                "scenarioId": scenario["id"], "error": repr(error)}


def _records(building, tasks, workers, timeout_s, progress):
    """Return records in ignition order, then seed order, regardless of completion."""
    records = {}
    started = time.perf_counter()

    def save(index, record):
        records[index] = record
        if progress:
            sc = tasks[index]["scenario"]
            outcome = f"t90={record['t90']}" if record["ok"] else f"failed={record['error']}"
            elapsed = time.perf_counter() - started
            eta = elapsed / len(records) * (len(tasks) - len(records)) / 60
            print(f"[{len(records)}/{len(tasks)}] {sc['fire']['room']} seed {sc['seed']} "
                  f"{outcome} ({elapsed:.1f} s); eta {eta:.1f} min", flush=True)

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


# D23: widen_door's two errors that name a door, with the door's label in place of its id (an IFC id means
# nothing to a reader). `relabel` writes the same texts over the id forms that saved batches carry.
NO_OPENING = "{label} has no opening"
NOT_WIDENABLE = "widening {label} changes room connections or walkable pieces"
_SAVED_REASONS = ((re.compile(r"door (?P<id>.+) has no opening"), NO_OPENING),
                  (re.compile(r"widening (?P<id>.+) changes room connections or walkable pieces"), NOT_WIDENABLE))
_NUMERIC = ("runs", "rooms", "doors", "heatmaps")  # the batch sections `relabel` leaves alone: numbers and ids


def _room_name(room: dict) -> str:
    return room.get("name") or room["id"]


def _shown(room: dict, with_id: bool) -> str:
    """A room as a plain-door label shows it: ASCII, no colon (a `why` line ends its label at the first ": "),
    and, with `with_id`, the room's id after a name that is not the id."""
    raw = _room_name(room)
    name = re.sub(r"\s*:\s*", " - ", raw).encode("ascii", "replace").decode("ascii")
    return f"{name} ({room['id']})" if with_id and raw != room["id"] else name


def _midpoint(door: dict) -> tuple[float, float]:
    """The middle of the opening to the centimetre: doors on one wall line tie on x and are told apart by y."""
    try:
        return tuple(round((door["a"][i] + door["b"][i]) / 2, 2) for i in (0, 1))
    except (KeyError, IndexError, TypeError):
        return 0.0, 0.0


def _plain_labels(floor: dict) -> dict[str, str]:
    """D23: the label of every plain interior door on a floor (not an exit, not a stair door), by door id.

    `Door between <A> and <B>` with the rooms' names in floor order; `Door from <A>` with one known room;
    `Door <id>` with none. When another plain door of the floor joins the same names (either way round), or
    a door joins two rooms of one name, each name gets its room id: `Door between OPEN OFFICE (R113a) and
    CORRIDOR (R141)`. Doors that join the same rooms then end `, 1 of 2`, `, 2 of 2`, by the middle of the
    opening (x, then y).
    """
    rooms = {}
    for index, room in enumerate(floor.get("rooms", [])):
        rooms.setdefault(room["id"], (index, room))
    plain, seen = [], set()
    for door in floor.get("doors", []):
        if door["id"] in seen:  # the first door with an id is the one door_label finds
            continue
        seen.add(door["id"])
        connects = door.get("connects", [])
        known = [rooms[c][1] for c in sorted({c for c in connects if c in rooms}, key=lambda c: rooms[c][0])]
        if "outside" not in connects and not any(r.get("type") == "stair" for r in known):
            plain.append((door, known))
    joins = Counter(tuple(sorted(_room_name(r) for r in known)) for _, known in plain)
    memo = {}  # (room id, with id) -> how the room reads; most rooms have several doors

    def show(room: dict, with_id: bool) -> str:
        if (room["id"], with_id) not in memo:
            memo[room["id"], with_id] = _shown(room, with_id)
        return memo[room["id"], with_id]

    labels, twins = {}, defaultdict(list)
    for door, known in plain:
        if not known:
            labels[door["id"]] = f"Door {door['id']}"
            continue
        names = [_room_name(r) for r in known]
        crowded = joins[tuple(sorted(names))] > 1 or len(set(names)) < len(names)
        shown = [show(r, crowded) for r in known]
        labels[door["id"]] = ("Door from " + shown[0] if len(shown) == 1 else
                              "Door between " + ", ".join(shown[:-1]) + " and " + shown[-1])
        twins[tuple(r["id"] for r in known)].append(door)
    for group in twins.values():
        if len(group) > 1:
            for number, door in enumerate(sorted(group, key=lambda d: (*_midpoint(d), d["id"])), 1):
                labels[door["id"]] += f", {number} of {len(group)}"
    return labels


def door_label(building: dict, floor_id: str, door_id: str) -> tuple[str, str]:
    """Label a door, including stair and exterior openings; tolerate unknown ids."""
    floor = next((f for f in building.get("floors", []) if f["id"] == floor_id), {})
    door = next((d for d in floor.get("doors", []) if d["id"] == door_id), {})
    rooms = [r for r in floor.get("rooms", []) if r["id"] in door.get("connects", [])]
    stair = next((r for r in rooms if r.get("type") == "stair"), None)
    if "outside" in door.get("connects", []):
        info = next((e for e in floor.get("exits", []) if e["door"] == door_id), {})
        name = info.get("name", "")
        if name and ":" not in name and len(name) <= 30:
            return "exit", f"Exit {name}"
        if stair:
            return "exit", f"Stair {stair.get('group', stair['id'])} exit"
        if rooms and name:
            room = rooms[0]
            return "exit", f"Exit from {room.get('name', room['id'])} ({room['id']})"
        return "exit", f"Exit {door_id}"
    if stair:
        return "stair", f"Stair {stair.get('group', stair['id'])} door"
    if not door:
        return "door", f"Door {door_id}"  # an id the building does not have
    return "door", _plain_labels(floor).get(door_id, f"Door {door_id}")


def _legacy_label(floor: dict, door: dict) -> str:
    """What `door_label` called a plain interior door before D23, to the letter: `Door <id> (<A> to <B>)`.
    Saved batches carry these strings; `relabel` finds them with this."""
    names = " to ".join(r.get("name", r["id"]) for r in floor.get("rooms", []) if r["id"] in door.get("connects", []))
    return f"Door {door['id']}" + (f" ({names})" if names else "")


def relabel(building: dict, batch: dict) -> dict:
    """A copy of a saved batch whose texts name plain interior doors the D23 way (pure; nothing reruns).

    Every text outside the numeric sections (`runs`, `rooms`, `doors`, `heatmaps`) has each legacy label
    (`Door D$77xwP (CORRIDOR to SCIF OPEN OFFICE)`, as saved with its names folded to ASCII or not) swapped for
    the door's current label, and a skipped fix's reason that names its door by id gets the door's label.
    Ids, numbers and field names stay, and a second pass changes nothing. A legacy label that two floors
    would give different new labels is left alone.
    """
    swaps, clashes = {}, set()
    for floor in building.get("floors", []):
        labels, first = _plain_labels(floor), set()
        for door in floor.get("doors", []):
            if door["id"] in first:  # door_label finds the first door of an id
                continue
            first.add(door["id"])
            new = labels.get(door["id"])
            old = _legacy_label(floor, door)
            for saved in {old, old.encode("ascii", "replace").decode("ascii")}:
                if new is not None and saved != new:
                    if swaps.setdefault(saved, new) != new:
                        clashes.add(saved)
    pattern = re.compile("|".join(re.escape(s) for s in sorted(set(swaps) - clashes, key=len, reverse=True)) or r"(?!)")

    def swap(text: str) -> str:
        return pattern.sub(lambda m: swaps[m.group(0)], text) if "Door " in text else text

    def walk(value):
        if isinstance(value, str):
            return swap(value)
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        return value

    def named(reason: str) -> str:
        for saved, template in _SAVED_REASONS:
            match = saved.fullmatch(reason)
            if match:
                floor = next((f["id"] for f in building.get("floors", [])
                              if any(d["id"] == match["id"] for d in f.get("doors", []))), None)
                if floor is not None:
                    return template.format(label=door_label(building, floor, match["id"])[1])
        return reason

    result = deepcopy(batch)
    for key in result:
        if key not in _NUMERIC:
            result[key] = walk(result[key])
    for skipped in result.get("fixesSkipped", []):
        if isinstance(skipped.get("reason"), str):
            skipped["reason"] = named(skipped["reason"])
    return result


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
        if all("dosed" in record for record in records):
            rooms[-1]["riskDosed"] = sum(r["dosed"] for r in runs) / len(runs)
    doors = [{"id": door, "floor": floor,
              "meanWait": sum(d["waitPersonSeconds"] for d in values) / len(records),
              "peakQueue": max(d["peakQueue"] for d in values)}
             for (floor, door), values in by_door.items()]
    for door in doors:
        values = by_door[(door["floor"], door["id"])]
        if all("smokeWait" in value for value in values):
            door["meanSmokeWait"] = sum(d["smokeWait"] for d in values) / len(records)
    max_smoke = max((d.get("meanSmokeWait", 0) for d in doors), default=0)
    max_wait = max((d["meanWait"] for d in doors), default=0)
    max_queue = max((d["peakQueue"] for d in doors), default=0)
    for door in doors:
        if max_smoke > 0:
            door["score"] = round(100 * (0.5 * door["meanWait"] / (max_wait or 1)
                                         + 0.2 * door["peakQueue"] / (max_queue or 1)
                                         + 0.3 * door.get("meanSmokeWait", 0) / max_smoke), 1)
        else:
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
    top = []
    for door in sorted(doors, key=lambda d: -d["score"])[:4]:
        if door["score"] <= 0:
            continue
        kind, label = door_label(building, door["floor"], door["id"])
        smoke_clause = (f", {door['meanSmokeWait']:,.0f} of them in smoke,"
                        if door.get("meanSmokeWait", 0) >= 1 else "")
        why = (f"{label}: {door['peakQueue']} people queued at peak; "
               f"{door['meanWait']:,.0f} person-seconds of waiting on average{smoke_clause} across {len(records)} fires.")
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


def seed_ranges(building: dict, base: dict, records: list[dict]) -> dict:
    """Optional ranges and ranking stability over successful seeds; pure."""
    records = [r for r in records if r["ok"]]
    seeds = sorted({r["seed"] for r in records})
    if len(seeds) < 2:
        return {}

    def bounds(values):
        values = [float(v) for v in values]
        return {"min": min(values), "median": float(median(values)), "max": max(values)}

    result = aggregate(building, base, records)
    by_room = defaultdict(list)
    for record in records:
        by_room[(record["ignition"]["floor"], record["ignition"]["room"])].append(record)
    for room in result["rooms"]:
        runs = by_room[(room["floor"], room["id"])]
        room["riskT90Range"] = (bounds(r["t90"] if r["t90"] is not None else base["maxTime"]
                                       for r in runs) if room["riskT90"] is not None else None)
        room["riskTrappedRange"] = bounds(r["trapped"] for r in runs)
        if "riskDosed" in room:
            room["riskDosedRange"] = bounds(r["dosed"] for r in runs)

    per_seed = [aggregate(building, base, [r for r in records if r["seed"] == seed])
                for seed in seeds]
    door_maps = [{(d["floor"], d["id"]): d for d in summary["doors"]} for summary in per_seed]
    for door in result["doors"]:
        for source, field in (("score", "scoreRange"), ("meanWait", "meanWaitRange")):
            door[field] = bounds(mapping.get((door["floor"], door["id"]), {}).get(source, 0)
                                 for mapping in door_maps)

    def top_doors(summary):
        return [(item["floor"], item["id"]) for item in summary["top"]
                if item["kind"] in ("door", "stair", "exit")][:3]

    top3 = top_doors(result)
    seed_top3 = [top_doors(summary) for summary in per_seed]
    for item in result["top"]:
        key = (item["floor"], item["id"])
        if item["kind"] == "room":
            count = sum(any(t["kind"] == "room" and (t["floor"], t["id"]) == key
                            for t in summary["top"]) for summary in per_seed)
        else:
            count = sum(key in ranked for ranked in seed_top3)
        item.update(seedsInTop3=count, seeds=len(seeds))
    held_in = sum(set(ranked) == set(top3) for ranked in seed_top3)
    labels = [door_label(building, floor, ident)[1] for floor, ident in top3]
    why = (f"The top 3 weak spots hold in {held_in} of {len(seeds)} seeds: "
           + (", ".join(labels) if labels else "no queued doors") + ".")
    if top3:
        first = sum(bool(ranked) and ranked[0] == top3[0] for ranked in seed_top3)
        why += f" {labels[0]} ranks first in {first} of {len(seeds)}."
    result["stability"] = {"seeds": seeds, "top3": [ident for _, ident in top3],
                           "heldIn": held_in, "n": len(seeds), "stable": held_in == len(seeds),
                           "why": why.encode("ascii", "replace").decode("ascii")}
    return result


def run_many(building: dict, base: dict, ignitions: list[dict] | None = None,
             seeds=(1, 2, 3), workers: int | None = None, timeout_s: float = 7200,
             progress: bool = True) -> dict:
    """Build batch/v0 with room risks, chokepoint ranking and mean heatmaps.

    Inline execution (one worker or one task) checks the deadline between runs;
    a running inline simulation cannot be interrupted by this deadline.
    """
    workers = _workers(workers)
    if workers < 1 or timeout_s <= 0:
        raise ValueError("workers and timeout_s must be positive")
    if ignitions is None:
        ignitions = _ignitions(building, base)
    tasks = _tasks(building, base, ignitions, sorted(set(seeds)))
    started = time.perf_counter()
    records = _records(building, tasks, workers, timeout_s, progress)
    wall_s = time.perf_counter() - started
    run_times = [record["wallS"] for record in records if "wallS" in record]
    return {"version": "batch/v0", "id": f"batch-{building['id']}-{base['id']}",
            "buildingId": building["id"], "base": deepcopy(base),
            "note": "Simulated rule-based batch; fire and smoke model is illustrative.",
            "timing": {"runs": len(records), "failed": sum(not r["ok"] for r in records),
                       "workers": workers, "wallS": wall_s,
                       "meanRunS": sum(run_times) / len(run_times) if run_times else 0.0},
            "runs": [{key: record[key] for key in ("scenarioId", "seed", "ignition", "t90", "t100", "trapped",
                                                  "dosed", "smokeSeconds", "exitCounts") if key in record}
                     for record in records if record["ok"]],
            "failed": [{"scenarioId": record["scenarioId"], "error": record["error"]}
                       for record in records if not record["ok"]],
            **(seed_ranges(building, base, records) or aggregate(building, base, records))}


def _exit_why(exit_result: dict, building: dict | None = None) -> str:
    label = (door_label(building, exit_result["floor"], exit_result["id"])[1]
             if building is not None else f"Exit {exit_result['id']}")
    return (f"Blocking {label} adds {exit_result['dT90']:.0f} s "
            f"to 90% evacuation (mean of {exit_result['n']} fires).")


def add_exit_criticality(building: dict, base: dict, batch: dict,
                         workers: int | None = None, timeout_s: float = 7200,
                         top_rooms: int = 6) -> dict:
    """Compare blocked exits against successful baseline room/seed pairs.

    Return a copy; failed reruns are excluded from both sides of the comparison.
    The timeout applies separately to each exit's batch.
    """
    if top_rooms < 0:
        raise ValueError("top_rooms must be non-negative")
    result = deepcopy(batch)
    rooms = sorted(batch["rooms"], key=lambda room: -(
        room["riskT90"] if room["riskT90"] is not None else base["maxTime"]))[:top_rooms]
    ignitions = [{"floor": room["floor"], "room": room["id"]} for room in rooms]
    selected = {(room["floor"], room["id"]) for room in rooms}

    def key(run):
        return (run["ignition"]["floor"], run["ignition"]["room"], run["seed"])

    baseline = {key(run): run for run in batch["runs"]
                if (run["ignition"]["floor"], run["ignition"]["room"]) in selected}
    seeds = sorted({run["seed"] for run in baseline.values()})

    def effective_time(run):
        return run["t90"] if run["t90"] is not None else base["maxTime"]

    exits = []
    for floor in building["floors"]:
        for exit_info in floor["exits"]:
            blocked = deepcopy(base)
            blocked.setdefault("doors", {})[exit_info["door"]] = "blocked"
            rerun = run_many(building, blocked, ignitions, seeds, workers, timeout_s)
            pairs = [(run, baseline[key(run)]) for run in rerun["runs"] if key(run) in baseline]
            n = len(pairs)
            exits.append({"id": exit_info["door"], "floor": floor["id"],
                          "dT90": sum(effective_time(a) - effective_time(b) for a, b in pairs) / n if n else 0.0,
                          "dTrapped": sum(a["trapped"] - b["trapped"] for a, b in pairs) / n if n else 0.0,
                          "n": n})
    maximum = max((exit_result["dT90"] for exit_result in exits), default=0)
    critical = [{"kind": "exit", "id": e["id"], "floor": e["floor"],
                 "score": round(100 * max(0, e["dT90"]) / maximum, 1) if maximum > 0 else 0.0,
                 "why": _exit_why(e, building)} for e in exits if e["n"]]
    replaced = {(e["floor"], e["id"]) for e in critical}
    existing = [item for item in batch["top"]
                if not (item["kind"] == "exit" and (item["floor"], item["id"]) in replaced)]
    result.update(exits=exits, top=sorted(critical + existing, key=lambda item: -item["score"])[:5])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("building", type=Path)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--occupants", type=int, help="override total occupants, preserving the mix")
    parser.add_argument("--fire-type", help="override the fire preset and remove growth overrides")
    parser.add_argument("--rooms", type=int)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--budget-min", type=float, help="estimate sampled rooms from one inline pilot (not a hard deadline)")
    parser.add_argument("--exits", action="store_true", help="rerun worst ignition rooms with each exit blocked")
    parser.add_argument("--whatif", action="store_true", help="run paired default what-if variants")
    parser.add_argument("--whatif-rooms", type=int, help="compare only N highest-risk ignition rooms")
    parser.add_argument("--fixes", action="store_true", help="measure suggested fixes")
    parser.add_argument("--fix-rooms", type=int, help="fix only N highest-risk ignition rooms")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    building = json.loads(args.building.read_text(encoding="utf-8"))
    base = json.loads(args.scenario.read_text(encoding="utf-8"))
    try:
        base = apply_overrides(base, args.occupants, args.fire_type)
    except ValueError as error:
        parser.error(str(error))
    seeds = tuple(sorted({int(seed) for seed in args.seeds.split(",")}))
    args.workers = _workers(args.workers)
    if args.workers < 1:
        parser.error("--workers must be positive")
    started = time.perf_counter()
    if args.budget_min is not None:
        if not math.isfinite(args.budget_min) or args.budget_min <= 0:
            parser.error("--budget-min must be positive and finite")
        candidates = _ignitions(building, base, len([r for f in building["floors"] for r in f["rooms"]]))
        if not candidates:
            parser.error("--budget-min needs at least one eligible ignition room")
        _init(building)
        pilot = _run_one(_tasks(building, base, candidates[:1], seeds[:1])[0])
        if not pilot["ok"]:
            parser.error(f"budget pilot failed: {pilot['error']}")
        variants = 0
        if args.whatif:
            from fire.whatif import default_variants
            variants = len(default_variants(building, base, [pilot]))
        fixes = 0
        if args.fixes:
            from fire.fixes import planned_fix_runs
            fixes = planned_fix_runs(building, base)
        count = plan_rooms(args.budget_min * 60, pilot["wallS"], seeds, args.workers, variants + fixes)
        args.rooms = min(count, len(candidates), args.rooms if args.rooms is not None else len(candidates))
        if args.rooms < 1:
            parser.error("--budget-min needs --rooms to be positive")
        if args.whatif:
            args.whatif_rooms = args.rooms
        if args.fixes:
            args.fix_rooms = args.rooms
        fix_plan = f", {fixes} fixes" if args.fixes else ""
        estimate = args.rooms * len(seeds) * (1 + variants + fixes) * pilot["wallS"] * 2 / args.workers / 60
        print(f"pilot {pilot['wallS']:.1f} s; budget {args.budget_min:g} min, {args.workers} workers, "
              f"{len(seeds)} seeds, {variants} what-ifs{fix_plan} -> {args.rooms} rooms (est. {estimate:.1f} min)", flush=True)
    batch = run_many(building, base, _ignitions(building, base, args.rooms), seeds, args.workers)
    if args.exits:
        batch = add_exit_criticality(building, base, batch, workers=args.workers)
    if args.whatif:
        from fire.whatif import add_whatif
        batch = add_whatif(building, base, batch, rooms=args.whatif_rooms, workers=args.workers)
    if args.fixes:
        from fire.fixes import add_fixes
        batch = add_fixes(building, base, batch, rooms=args.fix_rooms, workers=args.workers)
    out = args.out if args.out is not None else Path(f"data/runs/batch-{building['id']}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(batch, separators=(",", ":")), encoding="utf-8")
    print(f"runtime {time.perf_counter() - started:.1f} s", flush=True)
    print(f"wrote {out} ({len(batch['runs'])} runs, {len(batch['failed'])} failed)", flush=True)
    for item in batch["top"]:
        print(item["why"], flush=True)
    if "stability" in batch:
        print(batch["stability"]["why"], flush=True)
    printed = {item["why"] for item in batch["top"]}
    for exit_result in batch.get("exits", []):
        why = _exit_why(exit_result, building)
        if exit_result["n"] and why not in printed:
            print(why, flush=True)

    for comparison in batch.get("whatIf", []):
        print(comparison["why"], flush=True)

    for fix in batch.get("fixes", []):
        print(fix["why"], flush=True)
    for skipped in batch.get("fixesSkipped", []):
        print(f"Skipped {skipped['id']}: {skipped['reason']}", flush=True)


if __name__ == "__main__":
    main()
