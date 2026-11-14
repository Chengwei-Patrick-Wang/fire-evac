"""Run the office or clinic demo fires: python -m sim.scale BUILDING BASE_SCENARIO."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import time

from shapely.geometry import Polygon
from sim.run import run

OFFICE_FIRES = {"kitchen": ("F1", "R125", "kitchen"),
               "lobby": ("F1", "R101", "trash"),
               "stair": ("F1", "RS101", "trash")}


CLINIC_FIRES = {"waiting": ("F1", "R1AC1", "kitchen"),
                "activity": ("F1", "R1DC1", "trash"),
                "kitchenette": ("F2", "R2B17", "kitchen"),
                "stair": ("F1", "R1AS1", "trash")}
FIRES = {"office": OFFICE_FIRES, "clinic": CLINIC_FIRES}


def fire_scenarios(building, base, fires=OFFICE_FIRES, agents=300):
    scenarios = {}
    for name, (fid, rid, preset) in fires.items():
        room = next((r for f in building["floors"] if f["id"] == fid
                     for r in f["rooms"] if r["id"] == rid), None)
        if room is None:
            raise ValueError(f"missing fire room {fid}/{rid}")
        point = Polygon(room["polygon"]).representative_point()
        scenario = deepcopy(base)
        scenario.update(id=f"{base['id']}-{name}", buildingId=building["id"],
                        maxTime=600, brain="rules",
                        occupants={"total": agents, "mix": deepcopy(base["occupants"]["mix"])})
        scenario["fire"] = {"floor": fid, "room": rid, "type": preset,
                            "x": point.x, "y": point.y,
                            "start": base.get("fire", {}).get("start", 0)}
        scenarios[name] = scenario
    return scenarios


def _run_one(building, name, scenario):
    started = time.perf_counter()
    result = run(building, scenario)
    size = len(json.dumps(result, separators=(",", ":")).encode()) / 1e6
    if size > 8:
        scenario.update(frameInterval=1.0, smokeInterval=5)
        result = run(building, scenario)
        reduced = len(json.dumps(result, separators=(",", ":")).encode()) / 1e6
        print(f"{name}: recording fallback {size:.2f} -> {reduced:.2f} MB")
        size = reduced
    row = {"name": name, **{k: result["metrics"][k] for k in
           ("agents", "evacuated", "trapped", "remaining", "inStairs", "t50", "t90", "t100")},
           "stuck": sum(e["type"] == "stuck" for e in result["events"]),
           "wallS": round(time.perf_counter() - started, 2),
           "simS": result["frames"][-1]["t"], "mb": round(size, 3)}
    return row, result


def run_scale(building, scenarios):
    return [_run_one(building, name, scenario)[0] for name, scenario in scenarios.items()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("building", type=Path)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--fires", help="comma-separated fire names")
    parser.add_argument("--agents", type=int, default=300)
    parser.add_argument("--out", type=Path, default=Path("data/runs"))
    args = parser.parse_args(argv)
    building = json.loads(args.building.read_text(encoding="utf-8"))
    base = json.loads(args.scenario.read_text(encoding="utf-8"))
    if building["id"] not in FIRES:
        raise ValueError(f"unknown building {building['id']!r}; known ids: {', '.join(FIRES)}")
    fires = FIRES[building["id"]]
    if args.fires:
        names = args.fires.split(",")
        unknown = set(names) - fires.keys()
        if unknown:
            raise ValueError(f"unknown fires {sorted(unknown)}; known fires: {', '.join(fires)}")
        fires = {name: fires[name] for name in names}
    args.out.mkdir(parents=True, exist_ok=True)
    for name, scenario in fire_scenarios(building, base, fires=fires, agents=args.agents).items():
        row, result = _run_one(building, name, scenario)
        prefix = args.out / f"{building['id']}-{name}"
        prefix.with_suffix(".run.json").write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
        prefix.with_suffix(".scenario.json").write_text(json.dumps(scenario, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(row), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
