"""Smoke test for multi-floor sim: python -m sim.smoke_test

Runs the example scenario on the example building (NoFire) and checks the
review-focus behavior: stair transfers, spawn points, frames, determinism,
and a run that hits maxTime. The default suite uses 40 agents; --slow also
runs the full example and the 300-agent performance check.
"""
from __future__ import annotations

import argparse
import json
import io
from contextlib import redirect_stderr
from copy import deepcopy
import sys
import time
from pathlib import Path

import numpy as np
from shapely.geometry import Point, Polygon

from sim.run import profile_metrics, _t_share, run, StuckWatch, floor_walkable, smoke_speed, fire_keepout, FIRE_KEEPOUT_M, place_occupants
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


def check_llm_batch(building, scenario):
    from unittest.mock import patch
    from sim.brain import LLMBrain

    showcase = dict(scenario, brain="llm", occupants={"total": 24, "mix": {"typical": 1}},
                    premovement={"office": [0, 0], "classroom": [0, 0]}, alarmTime=0)
    calls = []
    def nearest(observations):
        calls.append(deepcopy(observations))
        return [{"target": min(o["options"], key=lambda p: p["dist"])["id"],
                 "action": "go", "reason": "batch stub"} for o in observations]

    with patch("sim.run.load_llm_batch_decider", return_value=nearest):
        result = run(building, showcase, NoFire(building, showcase))
    logs = [e for e in result["events"] if e["type"] == "llm"]
    assert all(a.get("llm") for a in result["agents"])
    assert result["metrics"]["evacuated"] == 24
    assert any(len(call) > 1 for call in calls)
    assert len(calls) == len({e["t"] for e in logs})
    assert len(calls) <= int(result["frames"][-1]["t"]) + 1
    assert len(logs) == sum(map(len, calls))
    for event, obs in zip(logs, (o for call in calls for o in call)):
        assert event["reason"] == "batch stub" and not event.get("fallback")
        assert event["target"] == min(obs["options"], key=lambda p: p["dist"])["id"]
        if obs["current"] is not None and event["target"] != obs["current"]:
            assert any(e["type"] == "reroute" and e["idx"] == event["idx"]
                       and e["t"] == event["t"] and e["to"] == event["target"]
                       for e in result["events"])
    def broken(observations):
        raise RuntimeError("offline")
    with patch("sim.run.load_llm_batch_decider", return_value=broken):
        fallback = run(building, showcase, NoFire(building, showcase))
    assert fallback["metrics"]["evacuated"] == 24
    assert all(e.get("fallback") for e in fallback["events"] if e["type"] == "llm")
    oversized = dict(showcase, occupants={"total": 151, "mix": {"typical": 1}})
    try:
        run(building, oversized, NoFire(building, oversized))
        assert False, "151-agent showcase accepted"
    except ValueError as exc:
        assert "150" in str(exc)
    observations = calls[0]
    for provider in (lambda obs: [], lambda obs: [None] * len(obs),
                     lambda obs: [{"target": "invalid"}] * len(obs)):
        answers = LLMBrain(RuleBrain(42), decide_batch=provider).decide_batch(observations)
        assert len(answers) == len(observations) and all(a.get("fallback") for a in answers)
    def slow(observations):
        time.sleep(0.2)
        return [None] * len(observations)
    timed_brain = LLMBrain(RuleBrain(42), timeout=0.01, decide_batch=slow)
    assert all(a.get("fallback") for a in timed_brain.decide_batch(observations))
    pending = timed_brain.pending
    assert all(a.get("fallback") for a in timed_brain.decide_batch(observations))
    assert timed_brain.pending is pending
    pending.result(timeout=1)
    print(f"all-LLM OK: {len(calls)} batches, {len(logs)} decisions; cap and fallbacks OK")


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

    # Loss of every option traps people, including agents still delayed.
    class BlockAll(BlockE1):
        def blocked_doors(self):
            return {"E1", "E2", "DSA2", "DSB2"}

    stranded_scenario = dict(scenario, maxTime=100, occupants={"total": 4})
    stranded = run(building, stranded_scenario, BlockAll(building, stranded_scenario))
    assert stranded["metrics"]["remaining"] == 0
    assert stranded["metrics"]["trapped"] == 4
    assert all(e["reason"] == "no route" for e in stranded["events"] if e["type"] == "trapped")
    assert stranded["metrics"]["evacuated"] == stranded["metrics"]["inStairs"] == 0
    assert len([e for e in stranded["events"] if e["type"] == "door_blocked"]) == 4

    class LowVisibility(NoFire):
        def visibility(self, floor_id, x, y):
            return 1.0

    # Start both crowds immediately to isolate smoke speed from the new cue starts.
    immediate = dict(scenario, alarmTime=0, premovement={
        r["type"]: [0, 0] for f in building["floors"] for r in f["rooms"]})
    immediate_clear = run(building, immediate, NoFire(building, immediate))
    slow = run(building, immediate, LowVisibility(building, immediate))
    assert slow["metrics"]["t90"] >= 1.2 * immediate_clear["metrics"]["t90"]
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


def check_mobility(building, scenario, total=160, delays=(180, 60)):
    scenario = dict(scenario, maxTime=900, occupants={"total": total, "mix": {
        "typical": 0.8, "older": 0.05, "cane": 0.03, "walker": 0.02, "wheelchair": 0.1}})
    options = [{"id": "E", "kind": "exit"}, {"id": "S", "kind": "stair"}]
    assert mobility_options(options, False) == options[:1]
    assert mobility_options(options[1:], False)[0]["assist"]
    for delay in delays:
        configured = dict(scenario, assistDelay=delay)
        warnings = io.StringIO()
        with redirect_stderr(warnings):
            result = run(building, configured, NoFire(building, configured))
        assert "unknown profiles" not in warnings.getvalue()
        assert result["metrics"]["evacuated"] == total
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


def check_assistance(building, scenario, total=40):
    net = StairNet(building)
    rng = np.random.default_rng(1)
    held = net.enter(0, 0, "F2", "SA", rng, hold_until=100)
    assert held["enter"] >= 100
    entries = [net.enter(i, i, "F2", "SA", rng) for i in range(1, 4)]
    assert [entry["enter"] for entry in entries] == [1, 2, 3]
    assert net.backlog("F2", "SA", 3) == 1
    # Equal readiness and a slot too close to a future reservation preserve spacing.
    extra = net.enter(4, 100, "F2", "SA", rng)
    before = net.enter(5, 99.5, "F2", "SA", rng)
    assert before["enter"] > extra["enter"] > held["enter"]
    assert net.backlog("F2", "SA", before["enter"]) == 0

    agents = [{"idx": i, "profile": profile} for i, profile in
              enumerate(("typical", "typical", "wheelchair", "wheelchair", "visitor"))]
    events = [{"type": "exit", "idx": 1, "t": 20},
              {"type": "exit", "idx": 0, "t": 10},
              {"type": "exit", "idx": 2, "t": 50},
              {"type": "trapped", "idx": 3, "t": 30},
              {"type": "wait", "idx": 2, "t": 5, "until": 35},
              {"type": "wait", "idx": 3, "t": 10, "until": 70}]
    profiles, assist = profile_metrics(agents, events)
    assert profiles == {
        "typical": dict(agents=2, evacuated=2, trapped=0, t50=10, t90=20, t100=20),
        "wheelchair": dict(agents=2, evacuated=1, trapped=1, t50=50, t90=None, t100=None),
        "visitor": dict(agents=1, evacuated=0, trapped=0, t50=None, t90=None, t100=None)}
    assert assist == dict(waiting=2, meanWait=45, maxWait=60, personSeconds=90)
    assert profile_metrics([], []) == ({}, dict(waiting=0, meanWait=None, maxWait=None, personSeconds=0))

    mix = ({"typical": 0.95, "wheelchair": 0.05} if total == 160 else
           {"typical": 0.8, "older": 0.05, "cane": 0.03, "walker": 0.02, "wheelchair": 0.1})
    times = []
    for delay in (180, 0):
        configured = dict(scenario, seed=1, maxTime=900, assistDelay=delay,
                          occupants={"total": total, "mix": mix})
        result = run(building, configured, NoFire(building, configured))
        upper_walkers = {a["idx"] for a in result["agents"]
                         if a["floor"] == "F2" and a["profile"] != "wheelchair"}
        exits = sorted(e["t"] for e in result["events"]
                       if e["type"] == "exit" and e["idx"] in upper_walkers)
        times.append(_t_share(exits, len(upper_walkers), 0.9))
        metrics = result["metrics"]
        waits = [e for e in result["events"] if e["type"] == "wait"]
        assert waits and metrics["assist"]["waiting"] == len(waits)
        assert abs(metrics["assist"]["maxWait"] - delay) < 1e-9
        assert abs(metrics["assist"]["personSeconds"] - delay * len(waits)) < 1e-9
        assert sum(p["agents"] for p in metrics["profiles"].values()) == metrics["agents"]
        assert sum(p["evacuated"] for p in metrics["profiles"].values()) == total
    assert all(t is not None for t in times)
    assert abs(times[0] - times[1]) <= 20, times
    print(f"assistance ({total} agents): F2 non-wheelchair t90 "
          f"{times[0]:.2f} s (180 s wait), {times[1]:.2f} s (0 s wait)")


def fast_scenario(scenario, total=40) -> dict:
    fast = deepcopy(scenario)
    fast["occupants"] = {"total": total, "mix": fast["occupants"]["mix"]}
    fast["maxTime"] = 900
    return fast


def check_core(building, scenario) -> dict:
    t0 = time.perf_counter()
    r = run(building, scenario, NoFire(building, scenario))
    runtime = time.perf_counter() - t0
    m = r["metrics"]
    events = r["events"]
    assert not any(e["type"] == "start" for e in events)
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
    return r


def check_keepout(building, scenario, slow=False):
    from fire.model import FireModel
    floor = next(f for f in building["floors"] if f["id"] == "F1")
    walk = floor_walkable(floor)
    lobby = next(r for r in floor["rooms"] if r["id"] == "L1")
    point = Polygon(lobby["polygon"]).representative_point()
    cut = fire_keepout(walk, floor, "L1", point.x, point.y, FIRE_KEEPOUT_M)
    assert cut.geom_type == "Polygon"
    assert abs(walk.area - cut.area - 19.6) < 0.1
    assert all(Polygon(z["polygon"]).distance(cut) <= 0.1
               for z in floor["exits"] + floor["stairs"])
    corridor = fire_keepout(walk, floor, "C1", 20, 8, FIRE_KEEPOUT_M)
    assert abs(walk.area - corridor.area - np.pi) < 0.1
    assert fire_keepout(walk, floor, None, point.x, point.y, 2.5).equals(cut)
    assert fire_keepout(walk, floor, None, -100, -100, 2.5).equals(walk)
    assert fire_keepout(walk, floor, "L1", point.x, point.y, 0).equals(walk)
    # A tiny room cannot lose three quarters of its walkable area.
    tiny = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    tiny_floor = {"id": "tiny", "rooms": [{"id": "r", "polygon": list(tiny.exterior.coords)}],
                  "exits": [], "stairs": []}
    warnings = io.StringIO()
    with redirect_stderr(warnings):
        assert fire_keepout(tiny, tiny_floor, "r", 0.5, 0.5, 2.5).equals(tiny)
    assert "WARNING (sim)" in warnings.getvalue()

    burning = deepcopy(scenario)
    burning["fire"].update(floor="F1", room="L1", x=point.x, y=point.y)
    protected = run(building, burning, FireModel(building, burning))
    assert not any(e["type"] == "trapped" and e["floor"] == "F1"
                   and np.hypot(e["x"] - point.x, e["y"] - point.y) < 2
                   for e in protected["events"])
    fid = protected["floors"].index("F1")
    assert all(np.hypot(x - point.x, y - point.y) >= 2.5
               for _, x, y, f, _ in protected["frames"][0]["a"] if f == fid)
    # Arrival clearance changes congestion and seeded trajectories. Compare
    # the intervention with its paired baseline rather than pinning one old
    # trajectory's absolute casualty count (formerly <= 15 at full size).
    if slow:
        nearby = [e for e in protected["events"] if e["type"] == "trapped"
                  and e["floor"] == "F1" and Point(e["x"], e["y"]).distance(point) < 3.2]
        print(f"full lobby traps near keep-out: {nearby}")
    burning["fireKeepout"] = 0
    unprotected = run(building, burning, FireModel(building, burning))
    assert protected["metrics"]["trapped"] <= unprotected["metrics"]["trapped"] / 2
    print(f"lobby keep-out{' full size' if slow else ''}: {unprotected['metrics']['trapped']} → "
          f"{protected['metrics']['trapped']} trapped")


def check_cues(building, scenario, slow=False):
    if slow:
        try:
            from fire.model import FireModel
        except ImportError:
            print("fire cues: skipped full FireModel (not available)")
            return
        result = run(building, scenario, FireModel(building, scenario))
        kitchen = {a["idx"] for a in result["agents"] if a["floor"] == "F1" and a["room"] == "R101"}
        starts = [e for e in result["events"] if e["type"] == "start" and e["idx"] in kitchen]
        assert kitchen and {e["idx"] for e in starts} == kitchen
        assert len(starts) == len(kitchen)
        assert all(e["cue"] == "fire" and e["t"] <= 11 for e in starts)
        print(f"full fire cues: {len(starts)} kitchen occupants started by {max(e['t'] for e in starts)} s")
        return

    class KitchenFire(NoFire):
        def hrr(self, t):
            return 100.0 if t >= 5 else 0.0

    result = run(building, scenario, KitchenFire(building, scenario))
    kitchen = {a["idx"] for a in result["agents"] if a["floor"] == "F1" and a["room"] == "R101"}
    starts = [e for e in result["events"] if e["type"] == "start"]
    assert kitchen and {e["idx"] for e in starts} == kitchen
    assert len(starts) == len(kitchen)
    assert all(e["cue"] == "fire" and 5 <= e["t"] <= 15 for e in starts)
    moving = {row[0] for f in result["frames"] if f["t"] < scenario["alarmTime"]
              for row in f["a"] if row[4] == 1}
    assert kitchen <= moving

    room = next(r for f in building["floors"] if f["id"] == "F1"
                for r in f["rooms"] if r["id"] == "R105")
    poly = Polygon(room["polygon"])

    class SmokyR105(NoFire):
        def step(self, t):
            self.t = t

        def visibility(self, floor_id, x, y):
            return 4.0 if self.t >= 20 and floor_id == "F1" and poly.contains(Point(x, y)) else 30.0

    result = run(building, scenario, SmokyR105(building, scenario))
    occupants = {a["idx"] for a in result["agents"] if a["floor"] == "F1" and a["room"] == "R105"}
    starts = [e for e in result["events"] if e["type"] == "start"]
    assert occupants and {e["idx"] for e in starts} == occupants
    assert len(starts) == len(occupants)
    assert all(e["cue"] == "smoke" and 20 <= e["t"] <= 30 for e in starts)
    # The alarm wins an outstanding cue countdown without emitting a cue start.
    early = dict(scenario, alarmTime=20, premovement={"office": [0, 0]})
    result = run(building, early, SmokyR105(building, early))
    assert not any(e["type"] == "start" for e in result["events"])

    seed = scenario["seed"]
    original = place_occupants(building, scenario, np.random.default_rng(seed))
    override = dict(scenario, premovement={"office": [100, 100]})
    changed = place_occupants(building, override, np.random.default_rng(seed))
    types = {(f["id"], r["id"]): r["type"] for f in building["floors"] for r in f["rooms"]}
    for before, after in zip(original, changed):
        expected = dict(before)
        if types[before["floor"], before["room"]] == "office":
            expected["startDelay"] = 100.0
        assert after == expected
    for invalid in ([1], [2, 1], [-1, 2], [0, float("inf")],
                    [float("nan"), 1], ["0", 1], [True, 1], None):
        try:
            place_occupants(building, dict(scenario, premovement={"office": invalid}),
                            np.random.default_rng(seed))
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid premovement accepted: {invalid}")
    print(f"fire/smoke cues and room-type delays OK: {len(kitchen)} kitchen, {len(occupants)} office occupants")


def check_recording(building, scenario):
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


def check_office_keepout():
    from sim.run import keepout_cut, body_pieces
    path = ROOT / "data/buildings/office.json"
    if not path.exists():
        print("office keep-out skipped: office building missing")
        return
    building = json.loads(path.read_text())
    floor = next(f for f in building["floors"] if f["id"] == "F1")
    walk = floor_walkable(floor)
    radii = {}
    for rid in ("R125", "R101", "RS101", "R143"):
        room = next(r for r in floor["rooms"] if r["id"] == rid)
        point = Polygon(room["polygon"]).representative_point()
        cut, radius = keepout_cut(walk, floor, rid, point.x, point.y, 2.5)
        assert radius in (2.5, 1.5, 1.0, 0.0)
        assert body_pieces(cut) <= body_pieces(walk)
        assert all(Polygon(z["polygon"]).distance(cut) <= 0.1
                   for z in floor["exits"] + floor["stairs"])
        radii[rid] = radius
    print(f"office keep-out OK: {radii}")


def check_stair_fire(building, fast, open_stair=False):
    from sim.floors import stair_doors
    floor = next(f for f in building["floors"] if f["id"] == "F1")
    stair = next(s for s in floor["stairs"] if s["room"] == "SA1")
    point = Polygon(stair["polygon"]).representative_point()
    class StairFire(NoFire):
        def step(self, t):
            self.t = t
        def hrr(self, t):
            return 500 if t >= 75 else 0
        def untenable(self, fid, x, y):
            return self.t >= 75 and fid == "F1" and point.distance(Point(x, y)) <= 1.2
    scenario = deepcopy(fast)
    scenario["fire"] = {"floor": "F1", "room": "SA1", "x": point.x,
                        "y": point.y, "type": "trash", "start": 75}
    result = run(building, scenario, StairFire(building, scenario))
    stairs = [e for e in result["events"] if e["type"] == "stair" and e["group"] == "SA"]
    assert stairs and all(e["t"] < 75 for e in stairs), stairs
    blocks = [e for e in result["events"] if e["type"] == "door_blocked"]
    assert {e["door"] for e in blocks} == stair_doors(floor, stair)
    assert all(e["t"] == 75 for e in blocks)
    cut = fire_keepout(floor_walkable(floor), floor, "SA1", point.x, point.y, 2.5).buffer(0.01)
    fid = result["floors"].index("F1")
    for frame in result["frames"]:
        rows = [a for a in frame["a"] if a[3] == fid and a[4] in (0, 1)]
        assert all(cut.covers(Point(a[1], a[2])) for a in rows)
    assert result["metrics"]["remaining"] == result["metrics"]["inStairs"] == 0
    if open_stair:
        assert not blocks
        stair_ids = {s["id"] for f in building["floors"] for s in f["stairs"]
                     if s["group"] == "SA"}
        assert all(e["reason"] == "stair SA closed" for e in result["events"]
                   if e["type"] == "reroute" and e["from"] in stair_ids and e["t"] >= 75)
        clear = run(building, scenario, NoFire(building, scenario))
        assert not any(e["type"] == "door_blocked" or
                       (e["type"] == "reroute" and "closed" in e["reason"])
                       for e in clear["events"])
        assert clear["metrics"]["evacuated"] == clear["metrics"]["agents"]
    print(f"burning stair OK: {len(stairs)} SA transfers before 75 s; none after")



def check_open_stair(building, fast):
    opened = deepcopy(building)
    for floor in opened["floors"]:
        floor["doors"] = [d for d in floor["doors"] if d["id"] not in {"DSA1", "DSA2"}]
    check_stair_fire(opened, fast, open_stair=True)


def check_keepout_slot():
    from sim.run import keepout_cut
    from sim.scale import FIRES
    poly = Polygon([(0, 0), (10, 0), (10, 8), (0, 8)])
    floor = {"id": "slot", "rooms": [{"id": "r", "polygon": list(poly.exterior.coords)}],
             "stairs": [], "exits": []}
    assert keepout_cut(poly, floor, "r", 5, 2.67, 2.5)[1] == 1.5
    assert keepout_cut(poly, floor, "r", 5, 3.0, 2.5)[1] == 2.5
    building = load_building()
    floor = building["floors"][0]
    walk = floor_walkable(floor)
    lobby = next(r for r in floor["rooms"] if r["id"] == "L1")
    point = Polygon(lobby["polygon"]).representative_point()
    for rid, x, y, expected in (("L1", point.x, point.y, 2.5),
                                ("R101", 8, 3, 2.5), ("C1", 20, 8, 1.0)):
        assert keepout_cut(walk, floor, rid, x, y, 2.5)[1] == expected
    for name, fires in FIRES.items():
        path = ROOT / f"data/buildings/{name}.json"
        if not path.exists():
            print(f"keep-out radii: {name} missing; skipped")
            continue
        building = json.loads(path.read_text())
        radii = {}
        for label, (fid, rid, _) in fires.items():
            floor = next(f for f in building["floors"] if f["id"] == fid)
            room = next(r for r in floor["rooms"] if r["id"] == rid)
            point = Polygon(room["polygon"]).representative_point()
            radii[label] = keepout_cut(floor_walkable(floor), floor, rid, point.x, point.y, 2.5)[1]
        print(f"{name} keep-out radii: {radii}")


def check_clinic_scale():
    from collections import Counter
    from unittest.mock import patch
    from sim.scale import CLINIC_FIRES, fire_scenarios, run_scale
    path = ROOT / "data/buildings/clinic.json"
    if not path.exists():
        print("clinic scale: building missing; skipped")
        return
    building = json.loads(path.read_text())
    base = json.loads(path.with_name("clinic.scenario.json").read_text())
    def checked_run(building, scenario):
        result = run(building, scenario)
        events = result["events"]
        stuck = [e for e in events if e["type"] == "stuck"]
        assert all(n == 1 for n in Counter(e["idx"] for e in stuck).values()), stuck
        exits = {e["idx"]: e["t"] for e in events if e["type"] == "exit"}
        assert all(exits.get(e["idx"], -1) > e["t"] for e in stuck), stuck
        stairs = [e for e in events if e["type"] == "stair"]
        if scenario["fire"]["room"] == "R1AS1":
            assert not any(e["group"] == "S2" for e in stairs)
        if scenario["fire"]["room"] == "R2B17":
            assert {a["idx"] for a in result["agents"] if a["floor"] == "F2"} <= {e["idx"] for e in stairs}
        return result
    with patch("sim.scale.run", side_effect=checked_run):
        rows = run_scale(building, fire_scenarios(building, base, CLINIC_FIRES))
    for row in rows:
        assert row["remaining"] == row["inStairs"] == 0, row
        assert row["trapped"] <= 3 and row["mb"] <= 8, row
        print(f"clinic scale OK: {row}")


def check_blocked_arrival(slow=False):
    from unittest.mock import patch

    if slow:
        building = json.loads((ROOT / "data/buildings/office.json").read_text())
        scenario = json.loads((ROOT / "data/buildings/office.scenario.json").read_text())
        floor = next(f for f in building["floors"] if any(r["id"] == "R106" for r in f["rooms"]))
        point = Polygon(next(r for r in floor["rooms"] if r["id"] == "R106")["polygon"]).centroid
        scenario.update(seed=2, doors={"D$77wwb": "blocked"},
                        fire={"floor": floor["id"], "room": "R106", "x": point.x,
                              "y": point.y, "type": "kitchen", "start": 0})
        scenario["occupants"]["total"] = 250
        result = run(building, scenario)
        assert result["metrics"]["inStairs"] == 0
        assert result["metrics"]["exitCounts"]["D$77wwb"] == 0
        print(f"office blocked-exit arrival OK: {result['metrics']}")
        return

    def rect(x0, y0, x1, y1):
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]

    floors = []
    for level in (0, 1):
        fid = f"F{level + 1}"
        floors.append({"id": fid, "level": level, "height": 3, "elevation": 3 * level,
                       "walkable": [{"outer": rect(0, 0, 12, 4), "holes": []}],
                       "rooms": [{"id": fid + "R", "type": "office", "name": "Office",
                                  "polygon": rect(4, 0, 10, 4)}],
                       "stairs": [{"id": fid + "S", "group": "S", "room": fid + "S",
                                   "polygon": rect(0, 0, 3, 4)}],
                       "doors": [], "exits": []})
    lower = floors[0]
    lower["doors"] = [
        {"id": "blocked", "a": [0, 1], "b": [0, 3], "width": 2,
         "connects": ["F1S", "outside"], "rect": rect(-0.1, 1, 0.8, 3)},
        {"id": "open", "a": [10, 0], "b": [10, 4], "width": 4,
         "connects": ["F1R", "outside"], "rect": rect(9.8, 0, 10.2, 4)},
        {"id": "stair-door", "a": [3, 1], "b": [3, 3], "width": 2,
         "connects": ["F1S", "F1R"], "rect": rect(2.8, 1, 3.2, 3)}]
    lower["exits"] = [{"id": "out", "door": "open", "polygon": rect(11, 0, 12, 4)}]
    building = {"id": "arrival-test", "version": "building/v0", "floors": floors}
    scenario = {"id": "arrival-test", "seed": 2, "occupants": {
        "perRoom": {"F2R": 8}, "mix": {"typical": 1}}, "alarmTime": 0,
        "premovement": {"office": [0, 0]}, "maxTime": 100, "doors": {"blocked": "blocked"}}
    walk = floor_walkable(lower, {"blocked"})
    stair = Polygon(lower["stairs"][0]["polygon"])
    calls = []

    def checked_spot(region, others, rng, **kwargs):
        # Force a temporary full landing, then allow FIFO retries to drain it.
        calls.append(region)
        if len(calls) <= 10:
            return None
        pos = find_spot(region, others, rng, **kwargs)
        if pos is not None:
            point = Point(pos)
            assert walk.boundary.distance(point) >= 0.45 - 1e-9
            assert stair.boundary.distance(point) >= 0.45 - 1e-9
        return pos

    with patch("sim.run.find_spot", side_effect=checked_spot):
        result = run(building, scenario, NoFire(building, scenario))
    assert len(calls) > 10
    assert result["metrics"]["evacuated"] == 8
    assert result["metrics"]["inStairs"] == 0

    # A permanently unsafe landing must keep people in transit, without a
    # fallback that puts their bodies through the wall.
    lower["stairs"][0]["polygon"] = rect(0, 0, 0.4, 4)
    queued = run(building, dict(scenario, maxTime=40), NoFire(building, scenario))
    assert queued["metrics"]["inStairs"] == 8
    assert queued["metrics"]["evacuated"] == 0
    print("blocked-exit arrival clearance and FIFO retry OK")


def check_scale():
    from unittest.mock import patch
    from sim.scale import fire_scenarios, run_scale
    from sim.floors import stair_doors
    building = json.loads((ROOT / "data/buildings/office.json").read_text())
    base = json.loads((ROOT / "data/buildings/office.scenario.json").read_text())
    floor = next(f for f in building["floors"] if f["id"] == "F1")
    stair = next(s for s in floor["stairs"] if s["room"] == "RS101")
    exits = {e["id"] for e in floor["exits"] if e["door"] in stair_doors(floor, stair)}
    def checked_run(building, scenario):
        result = run(building, scenario)
        events = result["events"]
        for event in events:
            if event["type"] == "stuck":
                assert any(e["type"] == "exit" and e["idx"] == event["idx"]
                           and e["t"] > event["t"] for e in events)
        if scenario["fire"]["room"] == "RS101":
            assert not any(e["type"] == "stair" and e["group"] == "S1" for e in events)
            assert not any(e["type"] == "exit" and e["exit"] in exits for e in events)
        return result
    with patch("sim.scale.run", side_effect=checked_run):
        rows = run_scale(building, fire_scenarios(building, base))
    for row in rows:
        assert row["remaining"] == row["inStairs"] == 0
        assert row["trapped"] <= 3 and row["mb"] <= 8
        # The current office has a recoverable R122 door stall in the kitchen
        # run (away from its keep-out). checked_run requires every stall to exit;
        # retain the zero-stall check for the unaffected lobby fixture.
        if row["name"] == "lobby":
            assert row["stuck"] == 0
        print(f"office scale OK: {row}")


def check_exit_choice(building, fast):
    import base64
    import shapely
    from sim.brain import option_cost, visible_smoke, main_entrance
    option = {"dist": 12, "queue": 2, "flow": 1.3, "tail": 0}
    assert abs(option_cost(option, 1.2) - 11.54) < .005
    assert abs(option_cost(dict(option, smoke=5, unfamiliar=True), 1.2) - 61.54) < .005
    vis = lambda x, y: np.where(x >= 10, 2, 30)
    assert abs(visible_smoke([(0, 0), (20, 0)], 30, vis) - 80/9) < .01
    assert visible_smoke([(0, 0), (20, 0)], 5, vis) == 0
    assert visible_smoke([(0, 0), (5, 0), (5, 20)], 30,
                         lambda x, y: np.where(y >= 5, 2, 30)) == 0
    assert main_entrance(building, {}) == "E1"
    assert main_entrance(building, {"entrance": "E2"}) == "E2"
    office = ROOT / "data/buildings/office.json"
    if office.exists():
        assert main_entrance(json.loads(office.read_text()), {}) == "DrRS91$"
    brain = RuleBrain(42)
    obs = {"idx": 0, "t": 0, "floor": "F1", "speed": 1, "current": None,
           "trigger": "start", "options": [dict(option, id="A")]}
    assert brain.decide(obs)["target"] == "A"
    obs.update(t=5, current="A", trigger="tick",
               options=[dict(option, id="A", dist=1000), dict(option, id="B", dist=4)])
    assert brain.decide(obs) is None
    obs["trigger"] = "smoke"
    decision = brain.decide(obs)
    assert decision["target"] == "B" and decision["reason"].startswith("smoke:")
    for weights in ({"smoke": -1}, {"unfamiliar": float("nan")}, {"smoke": float("inf")}):
        try:
            run(building, dict(fast, exitChoice=weights), NoFire(building, fast))
        except ValueError:
            pass
        else:
            raise AssertionError("invalid exitChoice accepted")
    try:
        main_entrance(building, {"entrance": "missing"})
    except ValueError:
        pass
    else:
        raise AssertionError("invalid entrance accepted")

    class SmokySA2(NoFire):
        def __init__(self, building, scenario):
            super().__init__(building, scenario)
            floor = next(f for f in building["floors"] if f["id"] == "F2")
            self.stair = Polygon(next(r for r in floor["rooms"] if r["id"] == "SA2")["polygon"])
            y, x = np.mgrid[0:40:.5, 0:40:.5]
            density = np.where(self.mask(x + .25, y + .25), 60, 0).astype(np.uint8)
            self.snap = {"origin": [0, 0], "cell": .5, "rows": 80, "cols": 80,
                         "d": base64.b64encode(density.tobytes()).decode()}

        def mask(self, x, y):
            return shapely.contains_xy(self.stair, x, y) | ((x < 8) & (y >= 6.5) & (y <= 9.5))

        def visibility(self, floor, x, y):
            return 100/60 if floor == "F2" and self.mask(x, y) else 30

        def snapshot(self, floor):
            return self.snap if floor == "F2" else None

    clear_choice = dict(fast, exitChoice={"smoke": 0})
    without = run(building, clear_choice, SmokySA2(building, clear_choice))
    with_smoke = run(building, fast, SmokySA2(building, fast))
    sa = lambda r: sum(e["type"] == "stair" and e["floor"] == "F2" and e["group"] == "SA" for e in r["events"])
    assert sa(without) >= 2
    assert sa(with_smoke) < sa(without), (sa(with_smoke), sa(without))
    visitors = dict(fast, occupants={"total": 40, "mix": {"visitor": 1}})
    familiar = run(building, visitors, NoFire(building, visitors))
    impartial = run(building, dict(visitors, exitChoice={"unfamiliar": 0}), NoFire(building, visitors))
    assert familiar["metrics"]["exitCounts"].get("E1", 0) > impartial["metrics"]["exitCounts"].get("E1", 0)
    print(f"exit choice: SA {sa(without)} -> {sa(with_smoke)}; visitor E1 "
          f"{impartial['metrics']['exitCounts'].get('E1', 0)} -> {familiar['metrics']['exitCounts'].get('E1', 0)}; "
          f"smoke reroutes {sum(e['type'] == 'reroute' and e['reason'].startswith('smoke:') for e in with_smoke['events'])}")


def check_calibration(slow=False):
    from shapely.geometry import box
    from sim.calibrate import weidmann, sfpe, speed_density, door_flow, corridor_points, corridor_limits

    assert abs(weidmann(1.0) - 1.058) < 0.005
    assert abs(sfpe(1.0) - 1.028) < 0.005
    # Two eligible people, one waiting-for-help person and one outside the area.
    # One eligible person disappears: count them for density, not displacement.
    frames = {"frames": [
        {"t": 5, "a": [[0, 0.2, 0.5, 0, 1], [1, 0.5, 0.5, 0, 0],
                        [2, 0.5, 0.5, 0, 2], [3, 3, 3, 0, 1]]},
        {"t": 5.5, "a": [[0, 0.7, 0.5, 0, 1], [2, 0.5, 0.5, 0, 2],
                          [3, 3, 3, 0, 1]]}]}
    points = speed_density(frames, box(0, 0, 2, 1), min_samples=1)
    assert len(points) == 1
    assert points[0]["density"] == 1.0 and points[0]["simulated"] == 1.0
    assert points[0]["samples"] == 1 and points[0]["label"] == "1.0–1.5 /m²"
    assert speed_density(frames, box(0, 0, 2, 1)) == []
    assert speed_density(frames, box(0, 0, 2, 1), t_min=6, min_samples=1) == []
    assert corridor_limits([{"simulated": 1.0}, {"simulated": 0.8}, {"simulated": 0.5}]) == []
    assert corridor_limits([{"simulated": 0.15}, {"simulated": 0.4}, {"simulated": 0.33}])
    agents = 200 if slow else 30
    result = door_flow(1.0, agents=agents)
    assert result["evacuated"] == agents, result
    lo, hi = (0.7, 1.3) if slow else (0.6, 1.5)
    assert lo <= result["flow"] <= hi, result
    assert 0.5 <= result["flow"] / (1.3 * 0.7) <= 2.0
    print(f"calibration: {agents} agents, 1 m flow {result['flow']:.3f} persons/s")
    if slow:
        points = corridor_points()
        assert len(points) >= 3, points
        assert all(p["samples"] >= 5 and 0 <= p["simulated"] <= 1.5 for p in points), points
        # C15's prescribed transient queue fails its free-flow trend expectation.
        # Keep the actual data and explicitly disclose this failed comparison.
        limits = corridor_limits(points)
        meets_reference = (0.7 <= points[0]["simulated"] <= 1.5
                           and points[-1]["simulated"] < 0.7 * points[0]["simulated"])
        assert bool(limits) == (not meets_reference)
        for limitation in limits:
            print(f"LIMIT: {limitation}")
        print(f"corridor: {len(points)} bins, speed {points[0]['simulated']:.2f} to "
              f"{points[-1]['simulated']:.2f} m/s")


def check_seeds(building, scenario, slow=False):
    from unittest.mock import patch
    from sim.seeds import run_seeds, summarize, seed_range

    rows = [{"seed": i, "t50": value, "t90": None, "t100": value if i != 2 else None,
             "evacuated": i, "trapped": 0} for i, value in enumerate((1.111, 3.333, 5.555))]
    summary = summarize(rows)
    assert summary["t50"] == {"min": 1.11, "median": 3.33, "max": 5.55, "missing": 0}
    assert summary["t100"] == {"min": 1.11, "median": 2.22, "max": 3.33, "missing": 1}
    assert summary["t90"] == {"min": None, "median": None, "max": None, "missing": 3}
    assert summarize([])["t90"]["min"] is None
    small = fast_scenario(scenario, total=12)
    small.pop("fire", None)
    original = deepcopy(small)
    repeated = run_seeds(building, small, [1, 1, 2])
    assert small == original
    clean = [{k: v for k, v in row.items() if k != "wallS"} for row in repeated]
    assert clean[0] == clean[1]
    assert any(clean[0][key] != clean[2][key] for key in ("t50", "t90", "t100"))
    base_scenario = dict(small, seed=1)
    base = run(building, base_scenario)
    with patch("sim.seeds._one", side_effect=AssertionError("base rerun")):
        assert seed_range(building, base_scenario, n=1, base=base) == summarize(repeated[:1])
    # Never mix an LLM base into a rule-only range, even with no live provider.
    with patch("sim.seeds.run_seeds", return_value=repeated[:1]) as runner:
        seed_range(building, dict(base_scenario, brain="llm"), n=1, base=base)
        assert runner.call_args.args[2] == [1]
    if slow:
        full = dict(scenario, maxTime=900)
        spread = seed_range(building, full, n=5, workers=2)
        for key in ("t50", "t90", "t100", "evacuated", "trapped"):
            stats = spread[key]
            assert stats["min"] is None or stats["min"] <= stats["median"] <= stats["max"]
        sequential = seed_range(building, base_scenario, n=3)
        assert sequential == seed_range(building, base_scenario, n=3, workers=2)
        assert sequential == seed_range(building, base_scenario, n=3, workers=2, base=base)
        print(f"seed range: full example t90 {spread['t90']}; worker and base reuse parity OK")


def check_sweep(building, fast, slow=False):
    from unittest.mock import patch
    from tempfile import TemporaryDirectory
    from sim.sweep import sweep_cases, check_case, sweep, write_report, load_buildings
    from fire.presets import PRESETS

    buildings = load_buildings(["example", "office", "clinic"])
    cases = sweep_cases(buildings, 8)
    assert cases == sweep_cases(buildings, 8)
    assert cases[3] == sweep_cases(buildings, 5)[3]
    for case in cases:
        b = buildings[case["building"]][0]
        s = case["scenario"]
        floor = next(f for f in b["floors"] if f["id"] == s["fire"]["floor"])
        assert s["fire"]["room"] in {r["id"] for r in floor["rooms"]}
        assert s["fire"]["type"] in PRESETS
        assert set(s["doors"]) <= {d["id"] for f in b["floors"] for d in f["doors"]}
    for error, expected in ((ValueError("cannot fit 9 agents in room F1/R1"), "rejected"),
                            (RuntimeError("broken"), "failed")):
        with patch("sim.sweep.run", side_effect=error):
            assert check_case(building, fast)["outcome"] == expected
    finished = dict(agents=[dict(idx=0)], events=[dict(type="trapped", idx=0, t=0, reason="no route")],
                    frames=[], metrics=dict(agents=1, evacuated=0, trapped=1, remaining=0, inStairs=0, t100=None))
    for field in ("remaining", "reason"):
        bad = deepcopy(finished)
        if field == "remaining":
            bad["metrics"]["remaining"] = 1
        else:
            del bad["events"][0]["reason"]
        with patch("sim.sweep.run", return_value=bad):
            assert check_case(building, fast)["outcome"] == "failed"
    small = deepcopy(fast)
    small.update(occupants={"total": 12, "mix": {"typical": 1}}, doors={"DSA1": "propped", "E2": "blocked"})
    small["fire"]["type"] = "kitchen"
    row = check_case(building, small)
    assert row["outcome"] == "ok", row
    assert sweep(cases, buildings, budget_min=0) == []
    # Exact seed-0 sweep repros: keep-out over a stage center, and blocked
    # interior doors leaving a geometric hairline into an isolated room.
    repros = sweep_cases(buildings, 48)
    if list(buildings) == ["example", "office", "clinic"]:
        for index in ((6, 12, 24, 42, 1, 18) if slow else (6, 12, 24)):
            case = repros[index]
            row = check_case(buildings[case["building"]][0], case["scenario"])
            assert row["outcome"] == "ok", row
    if slow:
        selected = {k: v for k, v in buildings.items() if k in ("example", "office")}
        cases = sweep_cases(selected, 4, agents=(10, 40, 120))
        rows = sweep(cases, selected, workers=2)
        assert len(rows) == 4
        with TemporaryDirectory() as directory:
            report = write_report(cases, rows, directory, 0, sum(r["wallS"] for r in rows))
            assert json.loads((Path(directory) / "report.json").read_text()) == report
    print("sweep generation, outcomes and real fire OK")


def check_runsize(building, fast, core, slow=False):
    from sim.runsize import size_report, rounding_problems, thin_frames, expand_frames
    from sim.run import BATCH_RECORDING
    from fire.model import FireModel

    assert rounding_problems(core) == []
    malformed = {"frameInterval": 0.5, "frames": [{"t": 0, "a": [[0, -0.0, 12.345, 0, 0]]}],
                 "events": [{"t": 0, "enter": 87.309}]}
    assert len(rounding_problems(malformed)) == 3
    malformed["frames"][0]["t"] = 0.1
    assert len(rounding_problems(malformed)) == 4
    original = deepcopy(core)
    thin = thin_frames(core)
    saved_thin = deepcopy(thin)
    assert expand_frames(thin) == core
    assert core == original and thin == saved_thin
    assert thin["frameHold"] is True
    assert size_report(thin)["rows"] < size_report(core)["rows"]
    assert thin_frames(thin) == thin and expand_frames(core) == core
    # Terminal events clear held rows, including an agent trapped before moving.
    terminal = {"frames": [{"t": 0, "a": [[0, 1, 2, 0, 0], [1, 2, 3, 0, 0]]},
                           {"t": 1, "a": [[1, 2, 3, 0, 0]]}, {"t": 2, "a": []}],
                "events": [{"type": "trapped", "idx": 0, "t": 1},
                           {"type": "exit", "idx": 1, "t": 2}]}
    assert expand_frames(thin_frames(terminal)) == terminal
    scenario = deepcopy(fast) if slow else fast_scenario(fast, total=12)
    results = []
    for recording in ({"frameInterval": 0.5, "smokeInterval": 2}, BATCH_RECORDING):
        sampled = {**scenario, **recording}
        fire = FireModel(building, sampled) if slow else NoFire(building, sampled)
        results.append(run(building, sampled, fire))
    full, batch = results
    assert full["metrics"] == batch["metrics"]
    assert full["events"] == batch["events"]
    by_time = {frame["t"]: frame for frame in full["frames"]}
    assert all(frame == by_time[frame["t"]] for frame in batch["frames"] if frame["a"])
    if slow:
        full_smoke = {s["floor"]: {f["t"]: f for f in s["frames"]} for s in full["smoke"]}
        assert batch["smoke"]
        for smoke in batch["smoke"]:
            assert all(f["t"] % 4 == 0 and f == full_smoke[smoke["floor"]][f["t"]]
                       for f in smoke["frames"])
    # Explicit caller intervals win over the batch defaults, without mutation.
    from unittest.mock import patch
    from sim.seeds import run_seeds
    from sim.sweep import check_case
    for override in ({}, {"frameInterval": 0.5, "smokeInterval": 2}):
        supplied = {**scenario, **override}
        before = deepcopy(supplied)
        with patch("sim.seeds.run", return_value=core) as mocked:
            run_seeds(building, supplied, [1])
            actual = mocked.call_args.args[1]
            assert all(actual[k] == supplied.get(k, v) for k, v in BATCH_RECORDING.items())
        with patch("sim.sweep.run", return_value=core) as mocked:
            check_case(building, supplied)
            actual = mocked.call_args.args[1]
            assert all(actual[k] == supplied.get(k, v) for k, v in BATCH_RECORDING.items())
        assert supplied == before
    print("run size: rounding, hold roundtrip and recording parity OK")


def check_smoke_walk(slow=False):
    from sim.calibrate import (UniformSmoke, smoke_walk, speed_visibility,
                               visibility_limits, SMOKE_RULE_LIMIT)
    from sim.run import smoke_speed

    for v0 in (0.6, 1.0, 1.5):
        for visibility in (1, 2, 3, 10):
            assert smoke_speed(v0, visibility) == min(v0, max(0.2, v0 - 0.34 * (3 - visibility)))
    assert smoke_speed(0.6, 1) == 0.2
    smoke = UniformSmoke(1.5)
    assert smoke.visibility("F1", 0, 0) == 1.5
    assert smoke.snapshot("F1") is None and smoke.hrr(100) == 0
    assert not smoke.untenable("F1", 0, 0) and not smoke.blocked_doors()
    if slow:
        curve = speed_visibility()
        failures = visibility_limits(curve)
        saved = json.loads((ROOT / "data/calibration.json").read_text())
        assert saved["speedVisibility"] == curve
        assert SMOKE_RULE_LIMIT in saved["limits"]
        # Keep and disclose measured misses instead of tuning the crowd model.
        assert all(failure in saved["limits"] for failure in failures), failures
        for failure in failures:
            print(failure)
    else:
        smoky, clear = smoke_walk(1.5, agents=4), smoke_walk(30, agents=4)
        assert smoky["samples"] > 0 and clear["samples"] > 0
        assert abs(smoky["simulated"] / smoky["formula"] - 1) <= 0.1, smoky
        assert smoky["simulated"] < clear["simulated"]
    print("smoke walking-speed measurements OK")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slow", action="store_true",
                        help="also run full-size regressions and the 300-agent benchmark")
    args = parser.parse_args(argv)
    started = time.perf_counter()

    def timed(label, check, *check_args, **kwargs):
        before = time.perf_counter()
        result = check(*check_args, **kwargs)
        print(f"{label}: {time.perf_counter() - before:.1f} s", flush=True)
        return result

    timed("calibration", check_calibration)
    timed("smoke walk", check_smoke_walk)
    timed("brain", check_brain)
    timed("floors", check_floors)
    timed("watch and geometry", check_watch_and_geometry)
    building = load_building()
    scenario = json.loads((ROOT / "contracts" / "scenario.example.json").read_text(encoding="utf-8"))
    scenario["maxTime"] = 900
    fast = fast_scenario(scenario)
    timed("fast sweep", check_sweep, building, fast)
    timed("fast seeds", check_seeds, building, fast)
    core = timed("fast core", check_core, building, fast)
    timed("run size", check_runsize, building, fast, core)
    timed("exit choice", check_exit_choice, building, fast)
    timed("fast cues", check_cues, building, fast)
    timed("office keep-out", check_office_keepout)
    timed("burning stair", check_stair_fire, building, fast)
    timed("open stair", check_open_stair, building, fast)
    timed("keep-out slot", check_keepout_slot)
    timed("blocked arrival", check_blocked_arrival)
    timed("fast keep-out", check_keepout, building, fast)
    timed("fast fire", check_fire, building, fast, core)
    timed("fast mobility", check_mobility, building, fast, total=40, delays=(60, 30))
    timed("fast assistance", check_assistance, building, fast)
    timed("fast LLM", check_llm, building, fast, core)
    timed("fast all-LLM", check_llm_batch, building, fast)
    timed("recording", check_recording, building, fast)

    if args.slow:
        timed("full sweep", check_sweep, building, fast, slow=True)
        timed("full seeds", check_seeds, building, scenario, slow=True)
        timed("full calibration", check_calibration, slow=True)
        timed("full smoke walk", check_smoke_walk, slow=True)
        timed("office blocked arrival", check_blocked_arrival, slow=True)
        timed("office scale", check_scale)
        timed("clinic scale", check_clinic_scale)
        core = timed("full core", check_core, building, scenario)
        timed("full run size", check_runsize, building, scenario, core, slow=True)
        timed("full cues", check_cues, building, scenario, slow=True)
        timed("full keep-out", check_keepout, building, scenario, slow=True)
        timed("full fire", check_fire, building, scenario, core)
        timed("300 agents", check_300, building, scenario)
        timed("full mobility", check_mobility, building, scenario)
        timed("full assistance", check_assistance, building, scenario, total=160)
        timed("full LLM", check_llm, building, scenario, core)

    print(f"suite {'slow' if args.slow else 'fast'}: {time.perf_counter() - started:.1f} s")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
