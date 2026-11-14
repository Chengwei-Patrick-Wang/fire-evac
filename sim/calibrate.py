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
from sim.run import floor_walkable, run, smoke_speed

ROOT = Path(__file__).resolve().parents[1]
WIDTHS = (0.8, 0.9, 1.0, 1.2, 1.6)
STEADY_DENSITIES = (0.25, 0.5, 1.0, 1.5, 2.0)
VISIBILITIES = (1.0, 1.5, 2.0, 2.5, 3.0, 5.0, 30.0)
SMOKE_RULE_LIMIT = ("Walking speed in smoke: the published rule is a model input; this curve "
                    "checks that the simulator applies it as published, not independent validation.")


class UniformSmoke(NoFire):
    """Constant visibility without heat, smoke snapshots or blocked routes."""

    def __init__(self, visibility):
        if not math.isfinite(visibility) or visibility <= 0:
            raise ValueError("visibility must be finite and positive")
        super().__init__({}, {})
        self.distance = visibility

    def visibility(self, floor_id, x, y):
        return self.distance


def smoke_walk(visibility, agents=8, seed=1):
    building = corridor_building(length=30.0, width=3.0, door=1.2)
    scenario = _scenario(building, agents, 1.2, seed)
    scenario["maxTime"] = 200
    result = run(building, scenario, UniformSmoke(visibility))
    v0 = {a["idx"]: a["v0"] for a in result["agents"]}
    speeds, expected = [], []
    for first, second in zip(result["frames"], result["frames"][1:]):
        dt = second["t"] - first["t"]
        if first["t"] < 1 or dt <= 0:
            continue
        following = {r[0]: r for r in second["a"]}
        for row in first["a"]:
            after = following.get(row[0])
            if (row[4] != 1 or not 2 <= row[1] <= 24 or after is None
                    or after[4] != 1 or after[3] != row[3]):
                continue
            speeds.append(math.hypot(after[1] - row[1], after[2] - row[2]) / dt)
            expected.append(smoke_speed(v0[row[0]], visibility))
    if not speeds:
        raise ValueError("corridor walk produced no moving frame-pair samples")
    return {"visibility": visibility, "simulated": round(mean(speeds), 4),
            "formula": round(mean(expected), 4), "samples": len(speeds)}


def speed_visibility(agents=8):
    points = []
    for visibility in VISIBILITIES:
        measurement = smoke_walk(visibility, agents)
        points.append({"label": f"{visibility:g} m visibility", "visibility": visibility,
                       "simulated": measurement["simulated"], "samples": measurement["samples"],
                       "references": [{"name": "Fridolf et al. (2018), as used by Cheong (2020)",
                                       "value": measurement["formula"]}]})
    return {"title": "Walking speed in smoke: simulation against the published rule",
            "source": f"JuPedSim 1.4.2 CollisionFreeSpeedModel, {agents} typical agents, seed 1; "
                      "30 × 3 m corridor, 1.2 m door; x = 2–24 m, t ≥ 1 s, immediate start",
            "formula": "min(v0, max(0.2, v0 − 0.34·(3 − S)))", "points": points}


def visibility_limits(curve):
    failures = []
    points = curve["points"]
    for point in points:
        reference = point["references"][0]["value"]
        if abs(point["simulated"] / reference - 1) > 0.1:
            failures.append(f"{point['visibility']:g} m visibility differs from the rule by more than 10%")
    speeds = {p["visibility"]: p["simulated"] for p in points}
    if not all(speeds[a] < speeds[b] for a, b in zip(VISIBILITIES[:4], VISIBILITIES[1:5])):
        failures.append("speeds do not decrease monotonically from 3 to 1 m visibility")
    if max(speeds[s] for s in (3, 5, 30)) - min(speeds[s] for s in (3, 5, 30)) > 0.03:
        failures.append("clear-air speeds at 3, 5 and 30 m differ by more than 0.03 m/s")
    return ["Walking speed in smoke measurement limit: " + issue + "." for issue in failures]



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


def speed_density(run, area, t_min=5.0, bin=0.5, min_samples=5, t_max=math.inf):
    """Frame-pair means in a single-floor polygon, with both times in the window."""
    return _bin_points(_pair_samples(run, area, t_min, t_max), bin, min_samples)


def _pair_samples(run, area, t_min, t_max):
    if area.area <= 0:
        raise ValueError("area must be positive")
    for first, second in zip(run["frames"], run["frames"][1:]):
        dt = second["t"] - first["t"]
        if first["t"] < t_min or second["t"] > t_max or dt <= 0:
            continue
        inside = [r for r in first["a"] if r[4] in (0, 1) and area.covers(Point(r[1:3]))]
        following = {r[0]: r for r in second["a"]}
        speeds = [math.hypot(following[r[0]][1] - r[1], following[r[0]][2] - r[2]) / dt
                  for r in inside if r[0] in following and following[r[0]][3] == r[3]]
        if not speeds:
            continue
        density = len(inside) / area.area
        yield density, mean(speeds)


def _bin_points(samples, bin, min_samples):
    if not math.isfinite(bin) or bin <= 0 or min_samples < 1:
        raise ValueError("bin and min_samples must be positive")
    bins = defaultdict(list)
    for density, speed in samples:
        bins[math.floor(density / bin)].append((density, speed))
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


def steady_corridor(density, seed=1):
    """Short, immediate-start walk; unfinished evacuation is outside this measurement."""
    if not math.isfinite(density) or density <= 0:
        raise ValueError("density must be finite and positive")
    building = corridor_building(length=60.0, width=3.0, door=2.6)
    scenario = _scenario(building, round(density * 60 * 3), 2.6, seed)
    scenario["maxTime"] = 16
    return run(building, scenario, NoFire(building, scenario))


def steady_points(densities=STEADY_DENSITIES, seed=1):
    building = corridor_building(length=60.0, width=3.0, door=2.6)
    area = box(10, 0, 20, 3).intersection(floor_walkable(building["floors"][0]))
    samples = []
    for density in densities:
        samples.extend(_pair_samples(steady_corridor(density, seed), area, 3, 15))
    return _bin_points(samples, 0.5, 5)


def corridor_points():
    return steady_points()


def corridor_limits(points):
    """Disclose failed reference checks; measurements must never be tuned to pass."""
    if len(points) < 3:
        return ["Corridor speed-density: fewer than three sampled density bins; insufficient coverage."]
    limits, failures = [], []
    low = points[0]["simulated"]
    if not 0.7 <= low <= 1.5:
        failures.append(f"lowest-density bin {low:.2f} m/s (expected 0.7–1.5)")
    if not all(a["simulated"] > b["simulated"] for a, b in zip(points, points[1:])):
        failures.append("speed does not fall strictly from bin to bin")
    if failures:
        limits.append("Corridor speed-density comparison does not meet the planned reference checks: "
                      + "; ".join(failures) + ".")
    deviations = []
    for point in points:
        refs = point["references"]
        lower = min(r["value"] for r in refs)
        upper = max(r["value"] for r in refs)
        speed = point["simulated"]
        if speed < 0.8 * lower or speed > 1.2 * upper:
            ref = refs[0]
            pct = abs(speed / ref["value"] - 1) * 100
            direction = "below" if speed < lower else "above"
            deviations.append(f"{point['density']:.2f} persons/m2 ({pct:.0f}% {direction} {ref['name']})")
    if deviations:
        limits.append("Corridor speed-density: simulated speeds differ by more than 20% from "
                      "both references at " + ", ".join(deviations)
                      + "; the crowd model differs from the reference walking speeds at these densities.")
    return limits


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
    print("density bin | density | speed m/s | Weidmann | SFPE | samples", flush=True)
    for p in speeds:
        print(f"{p['label']} | {p['density']:.2f} | {p['simulated']:.2f} | {p['references'][0]['value']:.2f} | "
              f"{p['references'][1]['value']:.2f} | {p['samples']}", flush=True)
    visibility = speed_visibility()
    limits.extend([SMOKE_RULE_LIMIT, *visibility_limits(visibility)])
    print("visibility | simulated | formula | simulated/formula | samples", flush=True)
    for p in visibility["points"]:
        reference = p["references"][0]["value"]
        print(f"{p['visibility']:g} | {p['simulated']:.2f} | {reference:.2f} | "
              f"{p['simulated'] / reference:.3f} | {p['samples']}", flush=True)
    return {"version": "calibration/v0", "title": "Door flow: simulation against published values",
            "source": f"JuPedSim 1.4.2 CollisionFreeSpeedModel, {agents} agents, seed 1, NoFire, immediate start",
            "points": points, "limits": limits,
            "speedDensity": {"title": "Corridor walking speed against density",
                             "source": "JuPedSim 1.4.2 CollisionFreeSpeedModel, typical agents at 0.25–2.0 persons/m², seed 1; "
                             "60 × 3 m corridor, 2.6 m exit 40 m past the 10 m strip (x = 10–20 m); "
                             "3–15 s, immediate start; "
                             "Weidmann (1993) and SFPE corridor reference curves",
                             "points": speeds}, "speedVisibility": visibility}


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
