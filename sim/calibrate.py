"""Measure crowd-model limits: python -m sim.calibrate [--agents 200]."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from statistics import mean
import time

from shapely.geometry import Point, box

from buildings.normalize import plan_to_building
from fire.stub import NoFire
from sim.run import floor_walkable, run

ROOT = Path(__file__).resolve().parents[1]
WIDTHS = (0.8, 0.9, 1.0, 1.2, 1.6)


def corridor_building(length=30.0, width=2.4, door=1.0):
    """One rectangular room with a real opening and exterior exit stub."""
    if not all(math.isfinite(v) and v > 0 for v in (length, width, door)) or door >= width:
        raise ValueError("dimensions must be positive and door narrower than room")
    plan = json.loads((ROOT / "buildings/fixtures/one_door.plan.json").read_text(encoding="utf-8-sig"))
    floor = plan["floors"][0]
    floor["rooms"][0]["polygon"] = [[0, 0], [length, 0], [length, width], [0, width]]
    floor["doors"][0].update(a=[length, (width - door) / 2],
                              b=[length, (width + door) / 2], width=door)
    return plan_to_building(plan)


def door_building(width):
    return corridor_building(length=14.0, width=10.0, door=width)


def _scenario(building, agents, width, seed=1):
    if not isinstance(agents, int) or agents < 1:
        raise ValueError("agents must be a positive integer")
    if width <= 0.3:
        raise ValueError("flow measurement requires width > 0.3 m")
    return {"version": "scenario/v0", "id": "calibration", "buildingId": building["id"],
            "seed": seed, "brain": "rules", "occupants": {"perRoom": {"R1": agents},
            "mix": {"typical": 1}}, "alarmTime": 0, "premovement": {"lobby": [0, 0]},
            "doors": {}, "sprinklers": False,
            "maxTime": 20 + 1.5 * agents / (1.3 * (width - 0.3))}


def door_flow(width, agents=200, seed=1):
    building = door_building(width)
    scenario = _scenario(building, agents, width, seed)
    result = run(building, scenario, NoFire(building, scenario))
    times = sorted(e["t"] for e in result["events"] if e["type"] == "exit")
    flow = None
    if len(times) >= 10:
        i10, i90 = int(0.1 * len(times)), int(0.9 * len(times))
        elapsed = times[i90] - times[i10]
        if elapsed > 0:
            flow = (i90 - i10) / elapsed
    return {"width": width, "agents": agents, "evacuated": len(times),
            "flow": flow, "lastExit": times[-1] if times else None}


def weidmann(rho):
    return 1.34 if rho <= 0 else 1.34 * (1 - math.exp(-1.913 * (1 / rho - 1 / 5.4)))


def sfpe(rho):
    return max(0, 1.4 * (1 - 0.266 * max(rho, 0.54)))


def speed_density(run, area, t_min=5.0, bin=0.5, min_samples=5):
    """Frame-pair means in a single-floor measurement polygon (m/s, persons/m²)."""
    if area.area <= 0 or not math.isfinite(bin) or bin <= 0 or min_samples < 1:
        raise ValueError("area, bin and min_samples must be positive")
    bins = defaultdict(list)
    for first, second in zip(run["frames"], run["frames"][1:]):
        dt = second["t"] - first["t"]
        if first["t"] < t_min or dt <= 0:
            continue
        inside = [r for r in first["a"] if r[4] in (0, 1) and area.covers(Point(r[1:3]))]
        following = {r[0]: r for r in second["a"]}
        speeds = [math.hypot(following[r[0]][1] - r[1], following[r[0]][2] - r[2]) / dt
                  for r in inside if r[0] in following and following[r[0]][3] == r[3]]
        if not speeds:
            continue
        density = len(inside) / area.area
        bins[math.floor(density / bin)].append((density, mean(speeds)))
    points = []
    for index, samples in sorted(bins.items()):
        if len(samples) < min_samples:
            continue
        density = round(mean(d for d, _ in samples), 2)
        points.append({"label": f"{index * bin:.1f}–{(index + 1) * bin:.1f} /m²",
                       "density": density, "simulated": round(mean(v for _, v in samples), 2),
                       "samples": len(samples), "references": [
                           {"name": "Weidmann (1993)", "value": round(weidmann(density), 4)},
                           {"name": "SFPE corridor 1.4·(1 − 0.266·D)", "value": round(sfpe(density), 4)}]})
    return points


def corridor_points():
    building = corridor_building()
    scenario = _scenario(building, 100, 1.0)
    result = run(building, scenario, NoFire(building, scenario))
    area = box(18, 0, 26, 2.4).intersection(floor_walkable(building["floors"][0]))
    return speed_density(result, area)


def corridor_limits(points):
    """Disclose failed reference checks; measurements must never be tuned to pass."""
    if len(points) < 3:
        return ["Corridor speed-density: fewer than three sampled density bins; insufficient coverage."]
    low, high = points[0]["simulated"], points[-1]["simulated"]
    if 0.7 <= low <= 1.5 and high < 0.7 * low:
        return []
    return [(f"Corridor speed-density comparison does not meet the planned reference checks: "
             f"lowest-density bin {low:.2f} m/s (expected 0.7–1.5), highest-density bin "
             f"{high:.2f} m/s (expected below 70% of the lowest-bin speed). "
             "These are full-strip averages during a draining bottleneck queue, not a "
             "validated steady-state walking-speed curve; low average density can include "
             "slow people left behind as the queue drains.")]


def calibration(agents=200):
    points, limits = [], []
    print("width | simulated | per m | IMO | hydraulic | simulated/hydraulic", flush=True)
    for width in WIDTHS:
        result = door_flow(width, agents)
        flow = result["flow"]
        imo, hydraulic = 1.3 * width, 1.3 * (width - 0.3)
        if result["evacuated"] < agents:
            limit = (f"{width:.1f} m door: {result['evacuated']} of {agents} passed by the run limit; "
                     f"last exit at {result['lastExit']} s. Narrow-opening deadlock is a known "
                     "limit of this crowd model (0.4 m body diameter).")
            limits.append(limit)
            print(limit, flush=True)
            continue
        if flow is None:
            limits.append(f"{width:.1f} m door: fewer than 10 exits; too few to estimate flow.")
            continue
        print(f"{width:.1f} | {flow:.3f} | {flow / width:.3f} | {imo:.3f} | "
              f"{hydraulic:.3f} | {flow / hydraulic:.3f}", flush=True)
        points.append({"label": f"{width:.1f} m door", "width": width, "simulated": round(flow, 4),
                       "references": [{"name": "IMO 1.3 persons/(m·s) × width", "value": round(imo, 4)},
                                      {"name": "Hydraulic 1.3 × (width − 0.3)", "value": round(hydraulic, 4)}]})
    speeds = corridor_points()
    limits.extend(corridor_limits(speeds))
    print("density bin | density | speed m/s | samples", flush=True)
    for p in speeds:
        print(f"{p['label']} | {p['density']:.2f} | {p['simulated']:.2f} | {p['samples']}", flush=True)
    return {"version": "calibration/v0", "title": "Door flow: simulation against published values",
            "source": f"JuPedSim 1.4.2 CollisionFreeSpeedModel, {agents} agents, seed 1, NoFire, immediate start",
            "points": points, "limits": limits,
            "speedDensity": {"title": "Corridor walking speed against density",
                             "source": "JuPedSim 1.4.2 CollisionFreeSpeedModel, 100 typical agents, seed 1; "
                             "30 × 2.4 m corridor, 1 m door; 8 m measurement strip, t ≥ 5 s; "
                             "Weidmann (1993) and SFPE corridor reference curves",
                             "points": speeds}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents", type=int, default=200)
    parser.add_argument("--out", type=Path, default=ROOT / "data/calibration.json")
    args = parser.parse_args(argv)
    if args.agents < 1:
        parser.error("--agents must be positive")
    started = time.perf_counter()
    result = calibration(args.agents)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out} in {time.perf_counter() - started:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
