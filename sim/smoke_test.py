"""Smoke test for multi-floor sim: python -m sim.smoke_test

Runs the example scenario on the example building (NoFire) and checks the
review-focus behavior: stair transfers, spawn points, frames, determinism,
and a run that hits maxTime.
"""
from __future__ import annotations

import json
import io
from contextlib import redirect_stderr
from copy import deepcopy
import sys
import time
from pathlib import Path

import numpy as np
from shapely.geometry import Point, Polygon

from sim.run import run, StuckWatch, floor_walkable, smoke_speed
from fire.stub import NoFire
from sim.floors import StairNet, find_spot
from sim.brain import RuleBrain, should_switch, route_length, ROUTING_MODE, mobility_options

ROOT = Path(__file__).resolve().parents[1]


def load_building() -> dict:
    path = ROOT / "contracts" / "building.example.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    from buildings.normalize import plan_to_building  # building example not generated yet
    return plan_to_building(json.loads((ROOT / "contracts" / "plan.example.json").read_text(encoding="utf-8")))


def check_llm(building, scenario, baseline):
    from unittest.mock import patch
    from sim.brain import LLMBrain

    observations = []
    def farthest(obs):
        observations.append(deepcopy(obs))
        return {"target": max(obs["options"], key=lambda o: o["dist"])["id"],
                "action": "go", "reason": "stub"}

    mixed = dict(scenario, brain="mixed")
    with patch("sim.run.load_llm_decider", return_value=farthest):
        result = run(building, mixed, NoFire(building, mixed))
    flagged = {a["idx"] for a in result["agents"] if a.get("llm")}
    assert 10 <= len(flagged) <= 20
    logs = [e for e in result["events"] if e["type"] == "llm"]
    assert logs and len(logs) == len(observations)
    last = {}
    for event, obs in zip(logs, observations):
        assert event["idx"] in flagged and event["reason"] == "stub"
        assert event["target"] == max(obs["options"], key=lambda o: o["dist"])["id"]
        assert event["t"] - last.get(event["idx"], -100) >= 10
        last[event["idx"]] = event["t"]
        if obs["current"] is not None and obs["current"] != event["target"]:
            assert any(e["type"] == "reroute" and e["idx"] == event["idx"]
                       and e["t"] == event["t"] and e["to"] == event["target"]
                       for e in result["events"])
    assert result["metrics"]["evacuated"] == len(result["agents"])
    with patch("sim.run.load_llm_decider", return_value=lambda obs: None):
        fallback = run(building, mixed, NoFire(building, mixed))
    assert {a["idx"] for a in fallback["agents"] if a.get("llm")} == flagged
    assert all(e.get("fallback") for e in fallback["events"] if e["type"] == "llm")
    assert fallback["metrics"]["evacuated"] == len(fallback["agents"])
    obs = observations[0]
    def slow(obs):
        time.sleep(1)
        return farthest(obs)
    started = time.perf_counter()
    slow_brain = LLMBrain(RuleBrain(scenario["seed"]), slow, timeout=0.2)
    assert slow_brain.decide(obs)["fallback"]
    assert time.perf_counter() - started < 0.7
    assert slow_brain.decide(obs)["fallback"]  # no queued call while provider is busy
    slow_brain.pending.result(timeout=2)
    def broken(obs):
        raise RuntimeError("offline")
    for provider in (broken, lambda obs: {"target": "missing", "action": "go", "reason": "bad"}):
        assert LLMBrain(RuleBrain(scenario["seed"]), provider).decide(obs)["fallback"]
    rules = dict(scenario, brain="rules")
    with patch("sim.run.load_llm_decider", side_effect=AssertionError("rules imported provider")):
        explicit = run(building, rules, NoFire(building, rules))
    assert explicit["events"] == baseline["events"]
    assert not any(e["type"] == "llm" for e in explicit["events"])
    print(f"mixed LLM OK: {len(flagged)} flagged, {len(logs)} decisions; timeout and rules fallback OK")


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


def check_watch_and_geometry():
    watch = StuckWatch()
    assert [t for t in range(101) if watch.update(0, t, 0, 0)] == [60]
    assert [t for t in range(101) if watch.update(1, t, 0 if t < 30 else 0.6, 0)] == [90]
    building = load_building()
    walk = {f["id"]: floor_walkable(f) for f in building["floors"]}
    broken = deepcopy(building)
    far = [[1000, 1000], [1001, 1000], [1001, 1001], [1000, 1001]]
    for stair in broken["floors"][0]["stairs"]:
        stair["polygon"] = far
    net = StairNet(broken, walkable=walk)
    assert not net.links("F2"), "detached arrivals must drop links"
    for ex in broken["floors"][0]["exits"]:
        ex["polygon"] = far
    try:
        StairNet(broken, walkable=walk).check({"F1"})
    except ValueError as exc:
        assert "F1" in str(exc)
    else:
        raise AssertionError("detached exits must not make a floor reachable")
    invalid = {"id": "invalid", "walkable": [{"outer": [[0, 0], [2, 2], [0, 2], [2, 0]], "holes": []}]}
    assert floor_walkable(invalid).is_valid
    pieces = {"id": "pieces", "walkable": [
        {"outer": [[0, 0], [2, 0], [2, 2], [0, 2]], "holes": []},
        {"outer": far, "holes": []}]}
    assert floor_walkable(pieces).area == 4
    print("watchdog and geometry guards OK")


def check_300(building, scenario):
    scenario = deepcopy(scenario)
    scenario["occupants"].pop("perRoom", None)
    scenario["occupants"]["total"] = 300
    start = time.perf_counter()
    result = run(building, scenario, NoFire(building, scenario))
    elapsed = time.perf_counter() - start
    size = len(json.dumps(result))
    metrics = result["metrics"]
    check_reroutes(result)
    assert metrics["evacuated"] == 300 and metrics["inStairs"] == metrics["remaining"] == 0
    assert not any(e["type"] == "stuck" for e in result["events"])
    assert elapsed < 120 and size < 8e6, (elapsed, size)
    transfers = {e["idx"]: e for e in result["events"] if e["type"] == "stair"}
    transit_counts, first_moving = {}, {}
    for frame in result["frames"]:
        for idx, x, y, fi, state in frame["a"]:
            if state == 3:
                transit_counts[idx] = transit_counts.get(idx, 0) + 1
            elif state == 1 and idx in transfers and fi == result["floors"].index(transfers[idx]["to"]):
                first_moving.setdefault(idx, frame["t"])
        for fi in range(len(result["floors"])):
            pts = np.array([[r[1], r[2]] for r in frame["a"] if r[3] == fi and r[4] in (0, 1)])
            if len(pts) > 1:
                distances = np.linalg.norm(pts[:, None] - pts[None, :], axis=2)
                np.fill_diagonal(distances, np.inf)
                assert distances.min() >= 0.3 - 1e-9
    for idx, event in transfers.items():
        assert transit_counts.get(idx, 0) * result["frameInterval"] <= event["arrive"] - event["t"] + 5
        assert first_moving[idx] - event["arrive"] <= 5
    print(f"300 agents: {elapsed:.2f} s, {size / 1e6:.2f} MB; {len(transfers)} transfers, zero stuck")


def check_brain():
    assert should_switch(10, 7.99) and not should_switch(10, 8.0)
    # A hole forces a detour; this detects an accidentally permanent fallback.
    poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)],
                   [[(4, 2), (6, 2), (6, 8), (4, 8)]])
    if ROUTING_MODE == "RoutingEngine":
        assert route_length(poly, (2, 5), (8, 5)) > 6
    brain = RuleBrain(42)
    obs = {"idx": 0, "t": 0, "floor": "F1", "speed": 1, "current": None,
           "trigger": "start", "options": [
               {"id": "A", "dist": 10, "queue": 0, "flow": 1.3, "tail": 0}]}
    assert brain.decide(obs)["target"] == "A"
    obs.update(current="A", trigger="tick", options=[
        {"id": "A", "dist": 1000, "queue": 0, "flow": 1.3, "tail": 0},
        {"id": "B", "dist": 4, "queue": 0, "flow": 1.3, "tail": 0}])
    obs["t"] = 14
    assert brain.decide(obs) is None
    obs["t"] = 15
    assert brain.decide(obs)["target"] == "B"
    obs.update(current="B", t=30)
    obs["options"][0]["dist"], obs["options"][1]["dist"] = 4, 1000
    assert brain.decide(obs) is None  # A was left only 15 seconds ago.
    obs["t"] = 45
    assert brain.decide(obs)["target"] == "A"
    obs.update(current="A", t=75)
    obs["options"][0]["dist"], obs["options"][1]["dist"] = 1000, 4
    assert brain.decide(obs)["target"] == "B"
    obs.update(current="B", t=105)
    obs["options"][0]["dist"], obs["options"][1]["dist"] = 4, 1000
    assert brain.decide(obs) is None  # Three-switch cap.


def check_reroutes(result):
    counts, left = {}, {}
    for event in result["events"]:
        if event["type"] != "reroute":
            continue
        idx, floor, t = event["idx"], event["floor"], event["t"]
        counts[idx] = counts.get(idx, 0) + 1
        assert counts[idx] <= 3
        assert t - left.get((idx, floor, event["to"]), -float("inf")) >= 30
        left[idx, floor, event["from"]] = t
    print(f"routing: {ROUTING_MODE}; reroutes {sum(counts.values())}; t90 {result['metrics']['t90']}")


def check_fire(building, scenario, clear):
    assert smoke_speed(1.2, 30) == 1.2
    assert abs(smoke_speed(1.2, 1) - 0.52) < 1e-9
    assert smoke_speed(1, 0) == 0.2
    scenario = dict(scenario, maxTime=900)
    blocked = dict(scenario, doors={"E1": "blocked"})
    result = run(building, blocked, NoFire(building, blocked))
    assert result["metrics"]["exitCounts"]["E1"] == 0
    assert result["metrics"]["evacuated"] == clear["metrics"]["agents"]
    assert [e for e in result["events"] if e["type"] == "door_blocked"] == [
        {"t": 0.0, "type": "door_blocked", "door": "E1", "floor": "F1"}]
    for door in ("DSA1", "DSA2"):
        net = StairNet(building, blocked={door})
        assert {s["group"] for s in net.links("F2")} == {"SB"}
    try:
        StairNet(building, blocked={"E1", "E2"}).check({"F1", "F2"})
    except ValueError:
        pass
    else:
        raise AssertionError("blocked exits must not count as escape routes")

    class BlockE1(NoFire):
        def step(self, t):
            self.t = t

        def blocked_doors(self):
            return {"E1"} if self.t >= 60 else set()

    result = run(building, scenario, BlockE1(building, scenario))
    assert [e for e in result["events"] if e["type"] == "door_blocked"] == [
        {"t": 60.0, "type": "door_blocked", "door": "E1", "floor": "F1"}]
    assert not any(e["type"] == "exit" and e["exit"] == "E1" and e["t"] > 70
                   for e in result["events"])
    reroutes = [e for e in result["events"] if e["type"] == "reroute" and "blocked" in e["reason"]]
    assert reroutes and all(e["t"] == 60 for e in reroutes)
    assert result["metrics"]["evacuated"] == clear["metrics"]["agents"]

    # Loss of every option must park people safely, including agents still delayed.
    class BlockAll(BlockE1):
        def blocked_doors(self):
            return {"E1", "E2", "DSA2", "DSB2"}

    stranded_scenario = dict(scenario, maxTime=100, occupants={"total": 4})
    stranded = run(building, stranded_scenario, BlockAll(building, stranded_scenario))
    assert stranded["metrics"]["remaining"] == 4
    assert stranded["metrics"]["evacuated"] == stranded["metrics"]["inStairs"] == 0
    assert len([e for e in stranded["events"] if e["type"] == "door_blocked"]) == 4

    class LowVisibility(NoFire):
        def visibility(self, floor_id, x, y):
            return 1.0

    slow = run(building, scenario, LowVisibility(building, scenario))
    assert slow["metrics"]["t90"] >= 1.2 * clear["metrics"]["t90"]
    room = next(r for r in building["floors"][0]["rooms"] if r["id"] == "R101")
    poly = Polygon(room["polygon"])

    class TrapRoom(NoFire):
        def step(self, t):
            self.t = t

        def untenable(self, floor_id, x, y):
            return self.t >= 40 and floor_id == "F1" and poly.contains(Point(x, y))

    trapped = run(building, scenario, TrapRoom(building, scenario))
    victims = {e["idx"]: e["t"] for e in trapped["events"] if e["type"] == "trapped"}
    assert victims
    assert not any(e["type"] == "exit" and e["idx"] in victims for e in trapped["events"])
    assert not any(idx in victims and frame["t"] >= victims[idx]
                   for frame in trapped["frames"] for idx, *_ in frame["a"])
    print(f"fire coupling OK: {len(reroutes)} blocked reroutes, slow t90 {slow['metrics']['t90']}, "
          f"{len(victims)} trapped")


def check_mobility(building, scenario):
    scenario = dict(scenario, maxTime=900, occupants={"total": 160, "mix": {
        "typical": 0.8, "older": 0.05, "cane": 0.03, "walker": 0.02, "wheelchair": 0.1}})
    options = [{"id": "E", "kind": "exit"}, {"id": "S", "kind": "stair"}]
    assert mobility_options(options, False) == options[:1]
    assert mobility_options(options[1:], False)[0]["assist"]
    for delay in (180, 60):
        configured = scenario if delay == 180 else dict(scenario, assistDelay=delay)
        warnings = io.StringIO()
        with redirect_stderr(warnings):
            result = run(building, configured, NoFire(building, configured))
        assert "unknown profiles" not in warnings.getvalue()
        assert result["metrics"]["evacuated"] == 160
        assert result["metrics"]["remaining"] == result["metrics"]["inStairs"] == 0
        wheelchairs = {a["idx"]: a for a in result["agents"] if a["profile"] == "wheelchair"}
        assert {a["floor"] for a in wheelchairs.values()} == {"F1", "F2"}
        waits = [e for e in result["events"] if e["type"] == "wait"]
        assert {e["idx"] for e in waits} == {i for i, a in wheelchairs.items() if a["floor"] == "F2"}
        assert len(waits) == len({e["idx"] for e in waits})
        for wait in waits:
            assert abs(wait["until"] - wait["t"] - delay) < 1e-9
            stair = next(e for e in result["events"] if e["type"] == "stair" and e["idx"] == wait["idx"])
            assert stair["enter"] >= wait["until"]
            assert abs(stair["arrive"] - stair["enter"] - 35) < 0.1
            zone = next(z for z in building["floors"][1]["stairs"] if z["group"] == stair["group"])
            assert Polygon(zone["polygon"]).contains(Point(wait["x"], wait["y"]))
            for frame in result["frames"]:
                if wait["t"] <= frame["t"] < wait["until"] - 1e-9:
                    rows = [r for r in frame["a"] if r[0] == wait["idx"]]
                    assert rows == [[wait["idx"], wait["x"], wait["y"], result["floors"].index("F2"), 2]]
        print(f"mobility OK: {len(waits)} waiters, longest wait {max(e['until'] - e['t'] for e in waits):.0f} s")


def main() -> int:
    check_brain()
    check_floors()
    check_watch_and_geometry()
    building = load_building()
    scenario = json.loads((ROOT / "contracts" / "scenario.example.json").read_text(encoding="utf-8"))

    scenario["maxTime"] = 900

    t0 = time.perf_counter()
    r = run(building, scenario, NoFire(building, scenario))
    runtime = time.perf_counter() - t0
    m = r["metrics"]
    events = r["events"]
    check_reroutes(r)

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
        run(broken, scenario, NoFire(broken, scenario))
    except ValueError as exc:
        assert "F2" in str(exc)
    else:
        raise AssertionError("run must reject disconnected occupied F2")

    r2 = run(building, scenario, NoFire(building, scenario))
    assert r2["metrics"] == m, "same seed gave different metrics"
    assert r2["events"] == events, "same seed gave different events"

    short = run(building, dict(scenario, maxTime=20), NoFire(building, scenario))
    assert short["metrics"]["t100"] is None, "20 s run should not reach t100"
    assert short["frames"][-1]["t"] == 20.0

    # Stop while stairs are occupied: transit must remain active and count once.
    first_transfer = next(e for e in events if e["type"] == "stair")
    cutoff = np.ceil(first_transfer["t"] * 2) / 2
    midway = run(building, dict(scenario, maxTime=cutoff), NoFire(building, scenario))
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
    chained = run(three, chained_scenario, NoFire(three, chained_scenario))
    assert chained["metrics"]["evacuated"] == 2
    for idx in range(2):
        transfers = [e for e in chained["events"] if e["idx"] == idx and e["type"] == "stair"]
        assert [e["floor"] for e in transfers] == ["F3", "F2"]
        assert [e["to"] for e in transfers] == ["F2", "F1"]
        assert transfers[0]["group"] == transfers[1]["group"]
        assert transfers[0]["arrive"] <= transfers[1]["t"] < transfers[0]["arrive"] + 0.011
        assert not any(row[0] == idx and row[3] == 1 and row[4] == 1
                       for frame in chained["frames"] for row in frame["a"])
    chained_scenario["occupants"]["mix"] = {"wheelchair": 1}
    assisted_chain = run(three, chained_scenario, NoFire(three, chained_scenario))
    assert assisted_chain["metrics"]["evacuated"] == 2
    for idx in range(2):
        waits = [e for e in assisted_chain["events"] if e.get("idx") == idx and e["type"] == "wait"]
        transfers = [e for e in assisted_chain["events"] if e.get("idx") == idx and e["type"] == "stair"]
        assert len(waits) == 1 and waits[0]["floor"] == "F3"
        assert [e["floor"] for e in transfers] == ["F3", "F2"]
        assert all(abs(e["arrive"] - e["enter"] - 35) < 0.1 for e in transfers)
    print("in-transit cutoff and three-floor chain (including one assistance wait) OK")

    print(f"agents {m['agents']}: evacuated {m['evacuated']}, inStairs {m['inStairs']}, trapped {m['trapped']}, "
          f"remaining {m['remaining']}; exits {m['exitCounts']}; min spawn gap {min_gap:.2f} m")
    print(f"t50 {m['t50']}  t90 {m['t90']}  t100 {m['t100']}  (t-values count exits only; "
          f"stairs transfer to lower floors)")
    print(f"runtime {runtime:.1f} s for {times[-1]:.1f} s simulated ({len(times)} frames)")
    check_fire(building, scenario, r)
    check_300(building, scenario)
    check_mobility(building, scenario)
    check_llm(building, scenario, r)
    from tools.toy_fire import ToyFire
    sampled = dict(scenario, maxTime=10, frameInterval=1.0, smokeInterval=5)
    recorded = run(building, sampled, ToyFire(building, sampled))
    assert recorded["frameInterval"] == 1.0
    assert [f["t"] for f in recorded["frames"]] == list(range(11))
    assert recorded["smoke"]
    for smoke in recorded["smoke"]:
        assert smoke["interval"] == 5
        assert [f["t"] for f in smoke["frames"]] == [0, 5, 10]
    print("recording intervals OK")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
