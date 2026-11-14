"""Smoke test for sim v0: python -m sim.smoke_test

Runs the example scenario on the example building (NoFire) and checks the
review-focus behavior: exits vs stair sinks, spawn points, frames, determinism,
and a run that hits maxTime.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from shapely.geometry import Point, Polygon

from sim.run import run

ROOT = Path(__file__).resolve().parents[1]


def load_building() -> dict:
    path = ROOT / "contracts" / "building.example.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    from buildings.normalize import plan_to_building  # building example not generated yet
    return plan_to_building(json.loads((ROOT / "contracts" / "plan.example.json").read_text(encoding="utf-8")))


def main() -> int:
    building = load_building()
    scenario = json.loads((ROOT / "contracts" / "scenario.example.json").read_text(encoding="utf-8"))

    t0 = time.perf_counter()
    r = run(building, scenario)
    runtime = time.perf_counter() - t0
    m = r["metrics"]
    events = r["events"]

    assert r["version"] == "run/v0" and r["frameInterval"] == 0.5
    agents = r["agents"]
    assert [a["idx"] for a in agents] == list(range(len(agents))) == list(range(m["agents"]))
    f1 = {a["idx"] for a in agents if a["floor"] == "F1"}
    f2 = {a["idx"] for a in agents if a["floor"] == "F2"}
    assert f1 and f2, "expected occupants on both floors"

    exited = [e["idx"] for e in events if e["type"] == "exit"]
    stair = [e["idx"] for e in events if e["type"] == "stair"]
    trapped = [e["idx"] for e in events if e["type"] == "trapped"]
    assert len(exited) == len(set(exited)) and len(stair) == len(set(stair)), "duplicate exit/stair events"
    assert f1 <= set(exited), f"{len(f1 - set(exited))} F1 agents never exited"
    assert f2 <= set(stair), f"{len(f2 - set(stair))} F2 agents have no stair event"
    assert not set(stair) & set(exited), "an agent both reached a stair and exited"
    assert all(e["group"] in ("SA", "SB") and e["floor"] == "F2" for e in events if e["type"] == "stair")
    assert m["evacuated"] == len(exited), "evacuated must count exit events only"
    assert m["inStairs"] == len(stair)
    assert m["exitCounts"].get("E1", 0) > 0 and m["exitCounts"].get("E2", 0) > 0, f"exits used: {m['exitCounts']}"
    assert not set(exited) & set(trapped), "an agent both exited and was trapped"
    assert m["evacuated"] + m["trapped"] + m["inStairs"] + m["remaining"] == m["agents"]

    times = [fr["t"] for fr in r["frames"]]
    assert times[0] == 0.0 and all(abs(b - a - 0.5) < 1e-9 for a, b in zip(times, times[1:])), "frame times"

    # Spawn points = frame 0 (all agents are added at t=0, coordinates on the 0.01 grid).
    first = r["frames"][0]["a"]
    assert len(first) == len(agents)
    room_poly = {rm["id"]: Polygon(rm["polygon"]) for f in building["floors"] for rm in f["rooms"]}
    by_floor: dict[int, list] = {}
    for idx, x, y, fi, status in first:
        fl = building["floors"][fi]
        walk = Polygon(fl["walkable"][0]["outer"], fl["walkable"][0]["holes"])
        assert walk.contains(Point(x, y)), f"agent {idx} spawned outside walkable at ({x}, {y})"
        assert room_poly[agents[idx]["room"]].contains(Point(x, y)), f"agent {idx} outside its room"
        assert status == 0
        by_floor.setdefault(fi, []).append((x, y))
    min_gap = float("inf")
    for pts in by_floor.values():
        p = np.array(pts)
        d = np.sqrt(((p[:, None, :] - p[None, :, :]) ** 2).sum(-1))
        np.fill_diagonal(d, np.inf)
        min_gap = min(min_gap, float(d.min()))
    assert min_gap >= 0.5 - 1e-9, f"spawn points only {min_gap:.3f} m apart"

    r2 = run(building, scenario)
    assert r2["metrics"] == m, "same seed gave different metrics"
    assert r2["events"] == events, "same seed gave different events"

    short = run(building, dict(scenario, maxTime=20))
    assert short["metrics"]["t100"] is None, "20 s run should not reach t100"
    assert short["frames"][-1]["t"] == 20.0

    print(f"agents {m['agents']}: evacuated {m['evacuated']}, inStairs {m['inStairs']}, trapped {m['trapped']}, "
          f"remaining {m['remaining']}; exits {m['exitCounts']}; min spawn gap {min_gap:.2f} m")
    print(f"t50 {m['t50']}  t90 {m['t90']}  t100 {m['t100']}  (t-values count exits only; "
          f"v0 stairs are sinks, so F2 agents never exit)")
    print(f"runtime {runtime:.1f} s for {times[-1]:.1f} s simulated ({len(times)} frames)")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
