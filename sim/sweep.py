"""Reproducible robustness sweep: python -m sim.sweep --workers 4."""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from copy import deepcopy
import argparse
import json
import multiprocessing
from pathlib import Path
import time
import traceback

import numpy as np
from shapely.geometry import Polygon

from fire.presets import PRESETS
from sim.run import run

REJECTIONS = ("cannot fit", "no room to place", "no stair route", "no exits or stairs")
ROOT = Path(__file__).resolve().parents[1]


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


def check_case(building, scenario):
    started = time.perf_counter()
    row = dict(id=scenario.get("id"), building=building["id"], outcome="ok", problems=[], error=None,
               **{key: None for key in ("agents", "evacuated", "trapped", "remaining", "inStairs", "t100")})
    try:
        result = run(building, scenario)
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
        if problems:
            row["outcome"] = "failed"
    row["wallS"] = round(time.perf_counter() - started, 3)
    return row


def _one(case, building):
    row = check_case(building, case["scenario"])
    row.update(id=case["id"], building=case["building"])
    return row


def sweep(cases, buildings, workers=1, budget_min=None):
    if workers < 1:
        raise ValueError("workers must be positive")
    deadline = time.monotonic() + (budget_min * 60 if budget_min is not None else float("inf"))
    rows = {}
    if workers == 1:
        for index, case in enumerate(cases):
            if time.monotonic() >= deadline:
                break
            rows[index] = _one(case, buildings[case["building"]][0])
    else:
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
            pending = {}
            index = 0
            while pending or index < len(cases):
                while index < len(cases) and len(pending) < workers and time.monotonic() < deadline:
                    case = cases[index]
                    pending[pool.submit(_one, case, buildings[case["building"]][0])] = index
                    index += 1
                if not pending:
                    break
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    rows[pending.pop(future)] = future.result()
    return [rows[i] for i in sorted(rows)]


def write_report(cases, rows, out, seed, wall_s):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    counts = Counter(row["outcome"] for row in rows)
    report = dict(seed=seed, cases=len(rows), **{k: counts[k] for k in ("ok", "rejected", "failed")}, wallS=round(wall_s, 3), rows=rows)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    by_id = {case["id"]: case for case in cases}
    for row in rows:
        if row["outcome"] != "failed":
            continue
        case = by_id[row["id"]]
        path = out / f"{row['id']}.scenario.json"
        path.write_text(json.dumps(case["scenario"], indent=2) + "\n")
        print(f"FAIL {row['id']}: {row['error'] or '; '.join(row['problems'])}", flush=True)
        print(f"python -m sim.run {building_path(case['building'])} {path} {out / (row['id'] + '.run.json')}", flush=True)
    print(f"sweep: {len(rows)} cases, {counts['ok']} ok, {counts['rejected']} rejected, {counts['failed']} failed in {wall_s / 60:.1f} min", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=48)
    parser.add_argument("--buildings", default="example,office,clinic")
    parser.add_argument("--agents", default="10,40,120,300")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--budget-min", type=float, default=40)
    parser.add_argument("--out", default="data/runs/sweep")
    args = parser.parse_args()
    buildings = load_buildings(args.buildings.split(","))
    cases = sweep_cases(buildings, args.cases, args.seed, tuple(map(int, args.agents.split(","))))
    started = time.perf_counter()
    rows = sweep(cases, buildings, args.workers, args.budget_min)
    write_report(cases, rows, args.out, args.seed, time.perf_counter() - started)


if __name__ == "__main__":
    main()
