"""Reproducible robustness sweep: python -m sim.sweep --workers 4. Every room on fire: --all-rooms."""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from contextlib import redirect_stderr
from copy import deepcopy
import argparse
import io
import json
import math
import multiprocessing
from pathlib import Path
import time
import traceback

import numpy as np
import shapely
from shapely.geometry import Point, Polygon

from fire.presets import PRESETS, fire_params, hrr_kw
from sim.run import BATCH_RECORDING, FIRE_KEEPOUT_M, WALL_CLEARANCE, fire_room, floor_walkable, keepout_cut, run

REJECTIONS = ("cannot fit", "no room to place", "no stair route", "no exits or stairs")
ROOT = Path(__file__).resolve().parents[1]
# A's precompute occupancy (tools/precompute_demo.py PRESETS); other buildings use their base scenario's total.
DESIGN_OCCUPANTS = {"office": 250, "clinic": 280}
# Keep-out classes, riskiest first: no cut, the 0.5 and 0.75 m fallback discs, a sealed room, then 1.0, 1.5 and 2.5 m.
KEEPOUT_ORDER = ("none", "0.5", "0.75", "sealed", "1.0", "1.5", "2.5")
FALLBACK = ("0.75", "0.5", "sealed", "none")
ROOM_SETTINGS = ("seed", "agents", "maxTime", "preset")  # a resumed report must match on these


def building_path(name):
    return ROOT / ("contracts/building.example.json" if name == "example" else f"data/buildings/{name}.json")


def load_buildings(names):
    result = {}
    for name in names:
        path = building_path(name)
        base = ROOT / "contracts/scenario.example.json" if name == "example" else path.with_suffix(".scenario.json")
        if not path.exists() or not base.exists():
            print(f"skip {name}: missing building or scenario", flush=True)
            continue
        result[name] = (json.loads(path.read_text()), json.loads(base.read_text()))
    return result


def sweep_cases(buildings, n, seed=0, agents=(10, 40, 120, 300)):
    if n < 0 or not agents or any(a <= 0 for a in agents):
        raise ValueError("cases must be nonnegative and agents positive")
    cases = []
    names = list(buildings)
    if not names:
        return cases
    for k in range(n):
        rng = np.random.default_rng([seed, k])
        name = names[k % len(names)]
        building, base = buildings[name]
        scenario = deepcopy(base)
        scenario.update(id=f"{name}-{k}", seed=int(rng.integers(1, 1000)), maxTime=900, brain="rules")
        mix = deepcopy(base.get("occupants", {}).get("mix", {"typical": 1}))
        if rng.random() < 1/3:
            others = {key: value for key, value in mix.items() if key != "wheelchair"}
            if not others or sum(others.values()) <= 0:
                others = {"typical": 1}
            mix = {key: value * .95 / sum(others.values()) for key, value in others.items()}
            mix["wheelchair"] = .05
        scenario["occupants"] = {"total": int(rng.choice(agents)), "mix": mix}
        rooms = [(f, r) for f in building["floors"] for r in f["rooms"]]
        floor, room = rooms[int(rng.integers(len(rooms)))]
        p = Polygon(room["polygon"]).representative_point()
        scenario["fire"] = dict(floor=floor["id"], room=room["id"], x=p.x, y=p.y,
                                type=str(rng.choice(list(PRESETS))), start=60 if rng.random() < .25 else 0)
        scenario["sprinklers"] = bool(rng.integers(2))
        doors = [d for f in building["floors"] for d in f["doors"]]
        stair_doors = [d for f in building["floors"] for d in f["doors"]
                       if any(s["room"] in d["connects"] for s in f["stairs"])]
        exits = [e["door"] for f in building["floors"] for e in f["exits"]]
        interior = [d["id"] for d in doors if "outside" not in d["connects"]]
        scenario["doors"] = deepcopy(base.get("doors", {}))
        for choices, probability, state in (([d["id"] for d in stair_doors], .5, "propped"),
                                            (exits, 1/3, "blocked"), (interior, .2, "blocked")):
            if rng.random() < probability and choices:
                scenario["doors"][str(rng.choice(choices))] = state
        cases.append(dict(id=scenario["id"], building=name, scenario=scenario))
    return cases


def radius_label(radius):
    """The keep-out class of a radius: "none" (no cut), "sealed" (the room itself) or the disc in metres."""
    if not radius:
        return "none"
    return "sealed" if math.isinf(radius) else str(float(radius))


def case_keepout(building, scenario, walkable=None):
    """What run() cuts out of the fire floor: (floor id, removed region, radius), or None when it cuts nothing.

    Built from the inputs run() uses: the blocked doors, fireKeepout (2.5 m by default), sealing only when
    no perRoom count puts people in the fire room, and only while the fire burns at maxTime. walkable
    optionally maps floor ids to floor_walkable(floor, blocked) for those same blocked doors.
    """
    fire = scenario.get("fire") or {}
    radius = float(scenario.get("fireKeepout", FIRE_KEEPOUT_M))
    if not radius or not fire:
        return None
    params = fire_params(fire, scenario.get("sprinklers", False))
    if hrr_kw(params, float(scenario.get("maxTime", 600)) - float(fire.get("start", 0))) <= 0:
        return None
    floor = next((f for f in building["floors"] if f["id"] == fire.get("floor")), None)
    if floor is None:
        return None
    blocked = {key for key, state in scenario.get("doors", {}).items() if state == "blocked"}
    with redirect_stderr(io.StringIO()):  # run() prints these warnings itself
        walk = floor_walkable(floor, blocked) if walkable is None else walkable[floor["id"]]
        origin = fire_room(floor, fire.get("room"), fire["x"], fire["y"])
        per_room = scenario.get("occupants", {}).get("perRoom", {})
        retained, used = keepout_cut(walk, floor, fire.get("room"), fire["x"], fire["y"], radius,
                                     seal=origin is None or per_room.get(origin["id"], 0) <= 0)
    return floor["id"], walk.difference(retained), used


def keepout_problems(building, scenario, result, cut=None):
    """Frame rows of any status on the fire floor inside the removed region (shrunk 0.01 m for rounding).

    cut is case_keepout's answer when the caller already has it: it is computed once per case.
    """
    cut = case_keepout(building, scenario) if cut is None else cut
    if cut is None:
        return []
    floor_id, removed, _ = cut
    region = removed.buffer(-0.01)
    if region.is_empty:
        return []
    index = [f["id"] for f in building["floors"]].index(floor_id)
    rows = [(frame["t"], *row) for frame in result["frames"] for row in frame["a"] if row[3] == index]
    if not rows:
        return []
    inside = shapely.contains_xy(region, [r[2] for r in rows], [r[3] for r in rows])
    hits = {}
    for row, flag in zip(rows, inside):
        if flag:
            hits.setdefault(row[1], []).append(row)
    return [f"keep-out: agent {idx}: {len(found)} frame rows inside the fire keep-out on {floor_id}, "
            f"first at t={found[0][0]} ({found[0][2]}, {found[0][3]}), status {found[0][5]}"
            for idx, found in sorted(hits.items())]


def click_point(region, rng, tries=2000):
    """A uniform point of the region, rounded to 0.01 m like the picker's click; None for an empty region."""
    if region.is_empty:
        return None
    minx, miny, maxx, maxy = region.bounds
    for _ in range(tries):
        x, y = (round(float(v), 2) + 0.0 for v in rng.uniform((minx, miny), (maxx, maxy)))
        if region.contains(Point(x, y)):
            return x, y
    point = region.representative_point()  # a sliver the bounding box almost misses
    return round(point.x, 2) + 0.0, round(point.y, 2) + 0.0


def room_cases(buildings, seed=1, agents=None, preset="kitchen", max_time=300, clicks=False):
    """One fire per room (corridors and stairs too) at its representative point, riskiest keep-outs first.

    Ids are <building>-<room>. With clicks, every non-stair room gets a second fire at a judge-style click
    point (<building>-<room>-click), after all the representative ones.
    """
    if agents is not None and agents <= 0:
        raise ValueError("agents must be positive")
    if max_time <= 0:
        raise ValueError("max_time must be positive")
    fire_params({"type": preset})
    ordinary, clicked = [], []
    for name, (building, base) in buildings.items():
        total = agents if agents is not None else DESIGN_OCCUPANTS.get(
            name, int(base.get("occupants", {}).get("total", 160)))
        mix = base.get("occupants", {}).get("mix", {"typical": 1})
        blocked = {key for key, state in base.get("doors", {}).items() if state == "blocked"}
        with redirect_stderr(io.StringIO()):
            walkable = {f["id"]: floor_walkable(f, blocked) for f in building["floors"]}

        def make(case_id, floor, room, x, y):
            scenario = deepcopy(base)
            scenario.update(id=case_id, seed=seed, maxTime=max_time, brain="rules",
                            occupants={"total": total, "mix": deepcopy(mix)},
                            fire=dict(floor=floor["id"], room=room["id"], x=x, y=y, type=preset, start=0))
            return scenario

        mine = []
        for k, (floor, room) in enumerate((f, r) for f in building["floors"] for r in f["rooms"]):
            point = Polygon(room["polygon"]).representative_point()
            scenario = make(f"{name}-{room['id']}", floor, room, point.x, point.y)
            cut = case_keepout(building, scenario, walkable)
            mine.append(dict(id=scenario["id"], building=name, scenario=scenario,
                             radius=radius_label(None if cut is None else cut[2])))
            if clicks and room.get("type") != "stair":
                region = Polygon(room["polygon"]).intersection(walkable[floor["id"]]).buffer(-WALL_CLEARANCE)
                click = click_point(region, np.random.default_rng([seed, k]))
                if click is not None:
                    case_id = f"{name}-{room['id']}-click"
                    clicked.append(dict(id=case_id, building=name, scenario=make(case_id, floor, room, *click)))
        ids = [case["id"] for case in mine]
        if len(set(ids)) != len(ids):
            raise ValueError(f"{name}: room ids are not unique")
        mine.sort(key=lambda case: KEEPOUT_ORDER.index(case["radius"]) if case["radius"] in KEEPOUT_ORDER
                  else len(KEEPOUT_ORDER))
        ordinary += mine
    return ordinary + clicked


def fallback_lists(cases):
    """Per building, the rooms (from the representative-point cases) whose fire keep-out is a fallback."""
    lists = {}
    for case in cases:
        lists.setdefault(case["building"], {key: [] for key in FALLBACK})
        if case.get("radius") in FALLBACK:
            lists[case["building"]][case["radius"]].append(case["scenario"]["fire"]["room"])
    return lists


def cases_left(cases, report, rerun_failed=False):
    """The cases a resumed sweep still has to run: those whose id is not in the report's rows."""
    done = {row["id"] for row in (report or {}).get("rows", []) if not (rerun_failed and row["outcome"] == "failed")}
    return [case for case in cases if case["id"] not in done]


def check_case(building, scenario, keepout=False):
    started = time.perf_counter()
    row = dict(id=scenario.get("id"), building=building["id"], outcome="ok", problems=[], error=None,
               **{key: None for key in ("agents", "evacuated", "trapped", "remaining", "inStairs", "t100")})
    if keepout:
        row.update(radius=None, stuck=None)
    try:
        result = run(building, {**BATCH_RECORDING, **scenario})
    except Exception as exc:
        row["outcome"] = "rejected" if isinstance(exc, ValueError) and any(s in str(exc) for s in REJECTIONS) else "failed"
        row["error"] = "\n".join(traceback.format_exc().strip().splitlines()[-3:])
    else:
        row.update({key: result["metrics"].get(key) for key in ("agents", "evacuated", "trapped", "remaining", "inStairs", "t100")})
        problems = row["problems"]
        if row["remaining"] + row["inStairs"] > 0:
            problems.append(f"unfinished: remaining={row['remaining']}, inStairs={row['inStairs']}")
        terminal = Counter()
        stuck = Counter()
        exits = {}
        for event in result["events"]:
            kind = event["type"]
            if kind in ("exit", "trapped"):
                terminal[event["idx"]] += 1
            if kind == "trapped" and not event.get("reason"):
                problems.append(f"agent {event['idx']}: trapped without reason")
            if kind == "exit":
                exits[event["idx"]] = event["t"]
            if kind == "stuck":
                stuck[event["idx"]] += 1
        for agent in result["agents"]:
            idx = agent["idx"]
            if terminal[idx] != 1:
                problems.append(f"agent {idx}: {terminal[idx]} terminal events")
            if stuck[idx] >= 2:
                problems.append(f"agent {idx}: {stuck[idx]} stuck events")
        for frame in result["frames"]:
            seen = set()
            for idx, x, y, floor, status in frame["a"]:
                if status not in (0, 1, 2, 3) or idx in seen or frame["t"] >= exits.get(idx, float("inf")):
                    problems.append(f"invalid frame row at {frame['t']}: agent {idx}")
                seen.add(idx)
        if keepout:
            row["stuck"] = sum(stuck.values())
            try:
                cut = case_keepout(building, scenario)
                row["radius"] = "sealed" if cut and math.isinf(cut[2]) else (cut[2] if cut else 0.0)
                problems.extend(keepout_problems(building, scenario, result, cut))
            except Exception:
                problems.append("keep-out check failed: " + " | ".join(traceback.format_exc().strip().splitlines()[-2:]))
        if problems:
            row["outcome"] = "failed"
    row["wallS"] = round(time.perf_counter() - started, 3)
    return row


def _one(case, building, keepout=False):
    row = check_case(building, case["scenario"], keepout=keepout)
    row.update(id=case["id"], building=case["building"])
    return row


def sweep(cases, buildings, workers=1, budget_min=None, keepout=False, on_row=None):
    if workers < 1:
        raise ValueError("workers must be positive")
    deadline = time.monotonic() + (budget_min * 60 if budget_min is not None else float("inf"))
    rows = {}
    if workers == 1:
        for index, case in enumerate(cases):
            if time.monotonic() >= deadline:
                break
            rows[index] = _one(case, buildings[case["building"]][0], keepout)
            if on_row:
                on_row(rows[index])
    else:
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
            pending = {}
            index = 0
            while pending or index < len(cases):
                while index < len(cases) and len(pending) < workers and time.monotonic() < deadline:
                    case = cases[index]
                    pending[pool.submit(_one, case, buildings[case["building"]][0], keepout)] = index
                    index += 1
                if not pending:
                    break
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    finished = pending.pop(future)
                    rows[finished] = future.result()
                    if on_row:
                        on_row(rows[finished])
    return [rows[i] for i in sorted(rows)]


def report_dict(rows, seed, wall_s, **extra):
    counts = Counter(row["outcome"] for row in rows)
    return dict(seed=seed, cases=len(rows), **{k: counts[k] for k in ("ok", "rejected", "failed")},
                wallS=round(wall_s, 3), rows=rows, **extra)


def report_failure(case, row, out):
    """Save a failed case's scenario next to the report and print how to rerun it."""
    path = out / f"{row['id']}.scenario.json"
    path.write_text(json.dumps(case["scenario"], indent=2) + "\n")
    print(f"FAIL {row['id']}: {row['error'] or '; '.join(row['problems'])}", flush=True)
    print(f"python -m sim.run {building_path(case['building'])} {path} {out / (row['id'] + '.run.json')}", flush=True)


def write_report(cases, rows, out, seed, wall_s):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    report = report_dict(rows, seed, wall_s)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    by_id = {case["id"]: case for case in cases}
    for row in rows:
        if row["outcome"] == "failed":
            report_failure(by_id[row["id"]], row, out)
    print(f"sweep: {len(rows)} cases, {report['ok']} ok, {report['rejected']} rejected, {report['failed']} failed in {wall_s / 60:.1f} min", flush=True)
    return report


def room_report(cases, rows, settings, wall_s, old=None):
    """report.json of the room sweep: every row so far, the fallback rooms and the cases still unrun.

    old is the report a resumed sweep started from: its fallback lists and unrun ids for buildings or
    cases outside this run's case list (say, an office-only click run after the clinic's rooms) stay.
    """
    old = old or {}
    position = {case["id"]: i for i, case in enumerate(cases)}
    rows = sorted(rows, key=lambda row: position.get(row["id"], len(cases)))
    done = {row["id"] for row in rows}
    unrun = [case["id"] for case in cases if case["id"] not in done]
    return report_dict(rows, settings["seed"], wall_s, settings=settings,
                       fallback={**old.get("fallback", {}), **fallback_lists(cases)},
                       unrun=[i for i in old.get("unrun", []) if i not in position and i not in done] + unrun)


def write_json(path, data):
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n")
    temp.replace(path)  # a killed sweep never leaves a half-written report


def rooms_main(args):
    buildings = load_buildings((args.buildings or "office,clinic").split(","))
    if not buildings:
        raise SystemExit("no buildings to sweep")
    settings = dict(seed=1 if args.seed is None else args.seed, agents=None if args.agents is None else int(args.agents),
                    maxTime=300 if args.max_time is None else args.max_time, preset="kitchen")
    cases = room_cases(buildings, settings["seed"], settings["agents"], settings["preset"], settings["maxTime"], args.clicks)
    out = Path(args.out or "data/runs/rooms")
    out.mkdir(parents=True, exist_ok=True)
    path = out / "report.json"
    old = json.loads(path.read_text()) if args.resume and path.exists() else None
    if old and any(old.get("settings", {}).get(key) != settings[key] for key in ROOM_SETTINGS):
        raise SystemExit(f"--resume: {path} was made with other settings {old.get('settings')}, not {settings}")
    todo = cases_left(cases, old, args.rerun_failed)
    merged = {row["id"]: row for row in (old or {}).get("rows", [])}
    by_id = {case["id"]: case for case in cases}
    before = old["wallS"] if old else 0.0
    started = time.perf_counter()
    print(f"rooms: {len(cases)} cases, {len(merged)} in the report, {len(todo)} to run on {args.workers} workers", flush=True)

    def save():
        write_json(path, room_report(cases, list(merged.values()), settings, before + time.perf_counter() - started, old))

    def on_row(row):
        merged[row["id"]] = row
        print(f"[{len(merged)}/{len(cases)}] {row['id']} {row['outcome']} radius={row['radius']} "
              f"out={row['evacuated']}/{row['agents']} trapped={row['trapped']} stuck={row['stuck']} "
              f"t100={row['t100']} {row['wallS']:.0f}s", flush=True)
        if row["outcome"] == "failed":
            report_failure(by_id[row["id"]], row, out)
        elif row["outcome"] == "rejected":
            print(f"REJECTED {row['id']}: {row['error']}", flush=True)
        if row["outcome"] != "failed":
            (out / f"{row['id']}.scenario.json").unlink(missing_ok=True)  # a rerun that passes drops its old repro
        save()

    budget = 90 if args.budget_min is None else args.budget_min
    sweep(todo, buildings, args.workers, budget, keepout=True, on_row=on_row)
    save()
    report = json.loads(path.read_text())
    rows = report["rows"]
    print(f"sweep: {len(rows)} cases, {report['ok']} ok, {report['rejected']} rejected, {report['failed']} failed, "
          f"{len(report['unrun'])} unrun in {time.perf_counter() - started:.0f} s this run "
          f"({report['wallS'] / 60:.1f} min in all)", flush=True)
    print(f"keep-out problems in {sum(any(p.startswith('keep-out') for p in r['problems']) for r in rows)} cases; "
          f"stuck events in {sum(bool(r.get('stuck')) for r in rows)} cases "
          f"({sum(r.get('stuck') or 0 for r in rows)} events)", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=48)
    parser.add_argument("--buildings", help="default: example,office,clinic (office,clinic with --all-rooms)")
    parser.add_argument("--agents", help="default: 10,40,120,300 (one number with --all-rooms: the design occupancy)")
    parser.add_argument("--seed", type=int, help="default: 0 (1 with --all-rooms)")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--budget-min", type=float, help="default: 40 (90 with --all-rooms)")
    parser.add_argument("--out", help="default: data/runs/sweep (data/runs/rooms with --all-rooms)")
    parser.add_argument("--all-rooms", action="store_true", help="a fire in every room at its representative point")
    parser.add_argument("--max-time", type=float, help="with --all-rooms: maxTime in seconds (default 300)")
    parser.add_argument("--clicks", action="store_true", help="with --all-rooms: also a click-point fire per non-stair room")
    parser.add_argument("--resume", action="store_true", help="with --all-rooms: skip the case ids already in the report")
    parser.add_argument("--rerun-failed", action="store_true", help="with --resume: run the failed cases again")
    args = parser.parse_args()
    if args.all_rooms:
        if args.rerun_failed and not args.resume:
            parser.error("--rerun-failed needs --resume")
        rooms_main(args)
        return
    if args.max_time is not None or args.clicks or args.resume or args.rerun_failed:
        parser.error("--max-time, --clicks, --resume and --rerun-failed are for --all-rooms")
    buildings = load_buildings((args.buildings or "example,office,clinic").split(","))
    seed = 0 if args.seed is None else args.seed
    cases = sweep_cases(buildings, args.cases, seed, tuple(map(int, (args.agents or "10,40,120,300").split(","))))
    started = time.perf_counter()
    rows = sweep(cases, buildings, args.workers, 40 if args.budget_min is None else args.budget_min)
    write_report(cases, rows, args.out or "data/runs/sweep", seed, time.perf_counter() - started)


if __name__ == "__main__":
    main()
