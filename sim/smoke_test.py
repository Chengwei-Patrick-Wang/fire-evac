"""Smoke test for multi-floor sim: python -m sim.smoke_test

Runs the example scenario on the example building (NoFire) and checks the
review-focus behavior: stair transfers, spawn points, frames, determinism,
and a run that hits maxTime.
"""
from __future__ import annotations

import json
from copy import deepcopy
import sys
import time
from pathlib import Path

import numpy as np
from shapely.geometry import Point, Polygon

from sim.run import run
from sim.floors import StairNet, find_spot

ROOT = Path(__file__).resolve().parents[1]


def load_building() -> dict:
    path = ROOT / "contracts" / "building.example.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    from buildings.normalize import plan_to_building  # building example not generated yet
    return plan_to_building(json.loads((ROOT / "contracts" / "plan.example.json").read_text(encoding="utf-8")))


def check_floors() -> None:
    building = load_building()
    net = StairNet(building)
    net.check({"F1", "F2"})
    assert not net.links("F1")
    links = net.links("F2")
    assert {link["stair"] for link in links} == {"SA2", "SB2"}
    assert all(link["to"] == "F1" and link["width"] == 1.0
               and link["length"] == 7.0 and link["tail"] > 12.7 for link in links)
    rng = np.random.default_rng(42)
    entries = [net.enter(i, 0.0, "F2", "SA", rng) for i in range(5)]
    assert all(b["enter"] - a["enter"] >= 0.909 for a, b in zip(entries, entries[1:]))
    assert all(abs(e["arrive"] - e["enter"] - 12.73) < 0.01 for e in entries)
    assert all(links[0]["arrival"].contains(Point(e["pos"])) for e in entries)
    assert net.backlog("F2", "SA", 0.0) == 4
    assert net.backlog("F2", "SA", entries[-1]["enter"]) == 0
    assert net.backlog("F2", "SB", 0.0) == 0
    repeat = StairNet(building)
    repeat_rng = np.random.default_rng(42)
    assert entries == [repeat.enter(i, 0.0, "F2", "SA", repeat_rng) for i in range(5)]

    broken = deepcopy(building)
    for floor in broken["floors"]:
        if floor["id"] == "F2":
            for stair in floor["stairs"]:
                stair["group"] = "ZZ"
    broken_net = StairNet(broken)
    broken_net.check({"F1"})
    try:
        broken_net.check({"F2"})
    except ValueError as exc:
        assert "F2" in str(exc)
    else:
        raise AssertionError("disconnected F2 should have no exit route")

    region = Polygon([(0, 0), (3, 0), (3, 3), (0, 3)])
    packed = np.array([(x, y) for x in np.arange(0, 3.01, 0.45)
                       for y in np.arange(0, 3.01, 0.45)])
    assert find_spot(region, packed, rng) is None
    half = packed[packed[:, 0] < 1.5]
    pos = find_spot(region, half, rng)
    assert pos is not None and region.contains(Point(pos))
    assert np.all(np.linalg.norm(half - pos, axis=1) >= 0.5)
    print("floors OK")


def main() -> int:
    check_floors()
    building = load_building()
    scenario = json.loads((ROOT / "contracts" / "scenario.example.json").read_text(encoding="utf-8"))

    scenario["maxTime"] = 900

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
    assert set(exited) == set(range(len(agents))), "every agent must exit"
    exit_times = {e["idx"]: e["t"] for e in events if e["type"] == "exit"}
    assert all(e["t"] < e["arrive"] < exit_times[e["idx"]]
               for e in events if e["type"] == "stair")
    assert all(e["group"] in ("SA", "SB") and e["floor"] == "F2" for e in events if e["type"] == "stair")
    assert m["evacuated"] == len(exited), "evacuated must count exit events only"
    assert m["inStairs"] == 0
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

    transit_frames = {}
    first_moving = {}
    for frame in r["frames"]:
        rows = frame["a"]
        assert len({row[0] for row in rows}) == len(rows), "duplicate frame agent"
        for idx, x, y, fi, state in rows:
            assert state in (0, 1, 2, 3), "invalid run/v0 status"
            assert frame["t"] < exit_times[idx], "exited agent still drawn"
            if state == 3:
                transit_frames[idx] = transit_frames.get(idx, 0) + 1
                assert fi == r["floors"].index("F1")
            elif state == 1 and idx in f2 and fi == r["floors"].index("F1"):
                first_moving.setdefault(idx, frame["t"])
        for fi in range(len(building["floors"])):
            pts = np.array([[row[1], row[2]] for row in rows
                            if row[3] == fi and row[4] in (0, 1)])
            if len(pts) > 1:
                distances = np.linalg.norm(pts[:, None] - pts[None, :], axis=2)
                np.fill_diagonal(distances, np.inf)
                assert distances.min() >= 0.3 - 1e-9, "agents stacked after re-entry"
    delays = []
    for idx in f2:
        transfers = [e for e in events if e["type"] == "stair" and e["idx"] == idx]
        assert 0.5 * transit_frames.get(idx, 0) <= transfers[-1]["arrive"] - transfers[0]["t"] + 5
        delays.append(first_moving[idx] - transfers[-1]["arrive"])
    print(f"transfers {len(stair)}; longest re-add delay ≤ {max(delays):.2f} s (frame resolution)")

    broken = deepcopy(building)
    for floor in broken["floors"]:
        if floor["id"] == "F2":
            for stair_zone in floor["stairs"]:
                stair_zone["group"] = "ZZ"
    try:
        run(broken, scenario)
    except ValueError as exc:
        assert "F2" in str(exc)
    else:
        raise AssertionError("run must reject disconnected occupied F2")

    r2 = run(building, scenario)
    assert r2["metrics"] == m, "same seed gave different metrics"
    assert r2["events"] == events, "same seed gave different events"

    short = run(building, dict(scenario, maxTime=20))
    assert short["metrics"]["t100"] is None, "20 s run should not reach t100"
    assert short["frames"][-1]["t"] == 20.0

    # Stop while stairs are occupied: transit must remain active and count once.
    first_transfer = next(e for e in events if e["type"] == "stair")
    cutoff = np.ceil(first_transfer["t"] * 2) / 2
    midway = run(building, dict(scenario, maxTime=cutoff))
    mm = midway["metrics"]
    assert mm["inStairs"] > 0
    assert sum(row[4] == 3 for row in midway["frames"][-1]["a"]) == mm["inStairs"]
    assert sum(mm[key] for key in ("evacuated", "trapped", "inStairs", "remaining")) == mm["agents"]

    # An intermediate floor without exits chains the same stair without spawning.
    three = deepcopy(building)
    upper = deepcopy(three["floors"][1])
    upper.update(id="F3", level=upper["level"] + 1, elevation=upper["elevation"] + upper["height"])
    for room in upper["rooms"]:
        room["id"] = "third-" + room["id"]
    for door in upper["doors"]:
        door["connects"] = ["third-" + rid if rid != "outside" else rid for rid in door["connects"]]
    for stair_zone in upper["stairs"]:
        stair_zone["room"] = "third-" + stair_zone["room"]
    three["floors"].append(upper)
    chained_scenario = deepcopy(scenario)
    room = next(room for room in upper["rooms"] if room["type"] not in
                {"corridor", "stair", "restroom", "storage"})
    chained_scenario["occupants"] = {"perRoom": {room["id"]: 2}, "mix": {"typical": 1}}
    chained = run(three, chained_scenario)
    assert chained["metrics"]["evacuated"] == 2
    for idx in range(2):
        transfers = [e for e in chained["events"] if e["idx"] == idx and e["type"] == "stair"]
        assert [e["floor"] for e in transfers] == ["F3", "F2"]
        assert [e["to"] for e in transfers] == ["F2", "F1"]
        assert transfers[0]["group"] == transfers[1]["group"]
        assert transfers[0]["arrive"] <= transfers[1]["t"] < transfers[0]["arrive"] + 0.011
        assert not any(row[0] == idx and row[3] == 1 and row[4] == 1
                       for frame in chained["frames"] for row in frame["a"])
    print("in-transit cutoff and three-floor chain OK")

    print(f"agents {m['agents']}: evacuated {m['evacuated']}, inStairs {m['inStairs']}, trapped {m['trapped']}, "
          f"remaining {m['remaining']}; exits {m['exitCounts']}; min spawn gap {min_gap:.2f} m")
    print(f"t50 {m['t50']}  t90 {m['t90']}  t100 {m['t100']}  (t-values count exits only; "
          f"stairs transfer to lower floors)")
    print(f"runtime {runtime:.1f} s for {times[-1]:.1f} s simulated ({len(times)} frames)")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
