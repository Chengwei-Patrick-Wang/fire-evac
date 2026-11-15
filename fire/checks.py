"""Small executable checks: python -m fire.checks [--slow].

The office checks read data/buildings/office.json, or the building file named in $FIRE_CHECK_OFFICE. They take
exit names, door widths and exit zones from that file, so a rebuilt office stays green.
"""
import argparse
import base64
from collections import Counter
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time

import numpy as np
import shapely
from shapely.geometry import box

from fire.grid import BuildingGraph, CLOSED_DOOR_M, MAX_CELLS, get_graph, grid_specs
from fire.presets import fire_params, hrr_kw

ROOT = Path(__file__).resolve().parents[1]


def office_path() -> Path:
    """The office building file the office checks read: $FIRE_CHECK_OFFICE, else data/buildings/office.json."""
    return Path(os.environ.get("FIRE_CHECK_OFFICE") or ROOT / "data/buildings/office.json")


def load_office(path=None) -> dict:
    return json.loads(Path(path or office_path()).read_text(encoding="utf-8"))


def _ring(polygon):
    return [list(p) for p in polygon.exterior.coords[:-1]]


def fixture_building() -> dict:
    a, b, door = box(0, 0, 10, 6), box(10.2, 0, 20.2, 6), box(9.8, 0.5, 10.4, 1.4)
    walkable = shapely.union_all([a, b, door])
    return {"version": "building/v0", "id": "fire-fixture", "floors": [
        {"id": "F1", "level": 0, "stairs": [], "exits": [],
         "rooms": [{"id": "A", "polygon": _ring(a)}, {"id": "B", "polygon": _ring(b)}],
         "doors": [{"id": "D", "rect": _ring(door), "connects": ["A", "B"],
                    "a": [10.1, 0.5], "b": [10.1, 1.4], "state": "closed"}],
         "walkable": [{"outer": _ring(walkable), "holes": []}]}]}


def two_floor_fixture() -> dict:
    """fixture_building() under a floor F2 (level 1): room C stands right over B, room E beside C over nothing, and door
    DC joins C and E."""
    building = fixture_building()
    c, e, door = box(10.2, 0, 20.2, 6), box(20.4, 0, 30.4, 6), box(20.0, 0.5, 20.6, 1.4)
    building["floors"].append(
        {"id": "F2", "level": 1, "stairs": [], "exits": [],
         "rooms": [{"id": "C", "polygon": _ring(c)}, {"id": "E", "polygon": _ring(e)}],
         "doors": [{"id": "DC", "rect": _ring(door), "connects": ["C", "E"],
                    "a": [20.3, 0.5], "b": [20.3, 1.4], "state": "closed"}],
         "walkable": [{"outer": _ring(shapely.union_all([c, e, door])), "holes": []}]})
    return building


def big_fixture() -> dict:
    ring = _ring(box(0, 0, 300, 200))
    return {"version": "building/v0", "id": "big-fixture", "floors": [
        {"id": "F1", "level": 0, "stairs": [], "exits": [], "doors": [],
         "rooms": [{"id": "big", "polygon": ring}],
         "walkable": [{"outer": ring, "holes": []}]}]}


def check_presets():
    assert fire_params({"type": "kitchen"})["alpha"] == 0.04688
    assert fire_params({"type": "battery"})["smokeFactor"] == 2.0
    assert fire_params({"type": "kitchen"}, True)["peakKw"] == 500.0
    assert fire_params({"type": "KITCHEN", "growth": "Ultra_Fast"})["alpha"] == 0.1876
    assert fire_params({"type": "kitchen", "growth": "Ultra Fast"})["alpha"] == 0.1876
    liquid = fire_params({"type": "liquid"})
    assert hrr_kw(liquid, 0) == 1500.0 and hrr_kw(liquid, -1) == 0.0
    kitchen = fire_params({"type": "kitchen"})
    assert abs(hrr_kw(kitchen, 60) - 168.768) < 1e-6
    assert hrr_kw(kitchen, 1000) == 1500.0
    for fire, valid in (({"type": "lava"}, "kitchen"),
                        ({"type": "kitchen", "growth": "explosive"}, "ultra-fast")):
        try:
            fire_params(fire)
        except ValueError as error:
            assert valid in str(error)
        else:
            raise AssertionError("unknown preset/growth must raise ValueError")


def check_grid():
    building = fixture_building()
    for cell in (0.5, 2.0):
        graph = BuildingGraph(building, cell=cell)
        source = graph.node_at("F1", 9.5, 5.5)
        target = graph.node_at("F1", 10.9, 5.5)
        clear = graph.path_distance(source, {})
        closed = graph.path_distance(source, {"D": CLOSED_DOOR_M})
        if cell == 0.5:
            assert 8 <= clear[target] <= 11, clear[target]
        assert abs(closed[target] - clear[target] - 15.0) < 0.01, (cell, clear[target], closed[target])
        assert len(graph.floors[0].door_nodes["D"]) >= 1
        assert graph.floors[0].mask.shape == graph.floors[0].snap.shape
        room = building["floors"][0]["rooms"][0]["polygon"]
        node = graph.node_at("F1", -50, -50, room)
        assert shapely.contains_xy(shapely.Polygon(room), *graph.floors[0].xy[node])
        try:
            graph.node_at("unknown", 0, 0)
        except ValueError:
            pass
        else:
            raise AssertionError("unknown floor must raise ValueError")
    assert get_graph(building) is get_graph(building)
    start = time.perf_counter()
    big = BuildingGraph(big_fixture())
    elapsed = time.perf_counter() - start
    spec = big.floors[0].spec
    assert spec["cols"] * spec["rows"] <= MAX_CELLS
    assert elapsed < 10, elapsed
    print(f"large grid: {spec['cols']} x {spec['rows']}, cell={spec['cell']:g} m, {elapsed:.2f} s")
    # A large floor coarsens every floor, keeping smoke/heatmap grids aligned.
    combined = big_fixture()
    combined["floors"].extend(building["floors"])
    specs = grid_specs(combined)
    assert len({s["cell"] for s in specs}) == 1
    assert all(s["cols"] * s["rows"] <= MAX_CELLS for s in specs)
    # Disconnected islands stay unreachable even if endpoints are nearby.
    disconnected = fixture_building()
    floor = disconnected["floors"][0]
    floor["doors"] = []
    floor["walkable"] = [{"outer": r["polygon"], "holes": []} for r in floor["rooms"]]
    graph = BuildingGraph(disconnected)
    assert np.isinf(graph.path_distance(graph.node_at("F1", 5, 3), {})[graph.node_at("F1", 15, 3)])


def check_model():
    from fire.model import FireModel

    building = fixture_building()
    scenario = {"fire": {"floor": "F1", "room": "A", "x": 8, "y": 5,
                         "type": "kitchen", "start": 0},
                "sprinklers": False, "doors": {}}
    model = FireModel(building, scenario, spread=False)
    assert abs(model.hrr(60) - 168.8) < 0.5
    assert model.hrr(200) == 1500
    assert model.snapshot("F1") is None
    x, y = model.source_xy
    west = (float(x - 3), float(y))
    far = (float(x - 7.5), float(y))
    model.step(1)
    assert model.untenable("F1", x, y)
    previous = 30.0
    for t in range(10, 201, 10):
        model.step(t)
        visibility = model.visibility("F1", *west)
        assert visibility <= previous, (t, visibility, previous)
        previous = visibility
        if t == 10:
            assert visibility == 30
        if t == 60:
            assert visibility < 30
            snap = model.snapshot("F1")
            raw = base64.b64decode(snap["d"])
            assert len(raw) == snap["cols"] * snap["rows"] and max(raw) <= 100
            json.dumps(snap)
            grid = np.frombuffer(raw, dtype=np.uint8).reshape(snap["rows"], snap["cols"])
            assert not grid[~model.graph.floors[0].mask].any()
        if t == 100:
            assert model.visibility("F1", x, y) < 3
        if t in (100, 160):
            assert not model.untenable("F1", *west), t
    assert model.untenable("F1", *west)
    jump = FireModel(building, scenario, spread=False)
    jump.step(200)
    seconds = FireModel(building, scenario, spread=False)
    for t in range(1, 201):
        seconds.step(t)
    assert np.array_equal(jump._untenable, seconds._untenable)
    assert np.array_equal(jump._untenable, model._untenable)
    assert np.array_equal(jump._density, seconds._density)
    for t in range(201, 401):
        model.step(t)
        assert not model.untenable("F1", *far), t
    assert model.visibility("F1", -50, -50) == 30
    assert not model.untenable("F1", -50, -50)
    model.step(400)  # repeated times are allowed
    try:
        model.step(399)
    except ValueError:
        pass
    else:
        raise AssertionError("decreasing fire time must raise ValueError")
    for x, y in ((-50, -50), (10.1, 3.0)):
        sc = {**scenario, "fire": {**scenario["fire"], "x": x, "y": y}}
        snapped = FireModel(building, sc, spread=False)
        assert shapely.contains_xy(shapely.Polygon(building["floors"][0]["rooms"][0]["polygon"]),
                                   *snapped.source_xy)
    delayed = FireModel(building, {**scenario, "fire": {**scenario["fire"], "start": 50}}, spread=False)
    delayed.step(49)
    assert delayed.hrr(49) == 0 and delayed.snapshot("F1") is None
    assert not delayed.untenable("F1", *delayed.source_xy)
    delayed.step(110)
    reference = FireModel(building, scenario, spread=False)
    reference.step(60)
    assert delayed.snapshot("F1") == reference.snapshot("F1")
    assert delayed.blocked_doors() == set()



def check_stairs():
    from fire.model import FireModel

    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text())
    scenario = json.loads((root / "contracts/scenario.example.json").read_text())
    scenario.update(sprinklers=False, doors={})
    scenario["fire"] = {"floor": "F1", "room": "R101", "x": 8, "y": 3,
                        "type": "kitchen", "start": 0}
    closed = FireModel(building, scenario)
    propped = FireModel(building, {**scenario, "doors": {"DSA1": "propped"}})
    both = FireModel(building, {**scenario, "doors": {"DSA1": "propped", "DSA2": "propped"}})
    corridor = closed.graph.node_at("F2", 7.5, 8)
    assert np.isfinite(closed.dist[corridor]) and closed.dist[corridor] >= 40
    for floor in closed.graph.floors:
        door_nodes = set().union(*(set(nodes) for nodes in floor.door_nodes.values()))
        assert all(not door_nodes.intersection(nodes) for nodes in floor.stair_nodes.values())

    def density(model, x, y):
        snap = model.snapshot("F2")
        if snap is None:
            return 0
        col = int((x - snap["origin"][0]) // snap["cell"])
        row = int((y - snap["origin"][1]) // snap["cell"])
        return base64.b64decode(snap["d"])[row * snap["cols"] + col]

    for model in (closed, propped, both):
        model.step(60)
        assert model.blocked_doors() == set()
    assert closed.snapshot("F2") is None
    assert propped.snapshot("F2") is not None
    for model in (closed, propped, both):
        model.step(90)
    assert density(closed, 2, 8) <= 5
    assert density(propped, 2, 8) >= 15
    assert density(closed, 7.5, 8) <= 2
    assert density(both, 7.5, 8) >= 10
    closed.step(200)
    assert "D101" in closed.blocked_doors()
    returned = closed.blocked_doors()
    returned.clear()
    assert "D101" in closed.blocked_doors()
    blocked = FireModel(building, {**scenario, "doors": {"DSA1": "blocked"}})
    assert np.array_equal(closed.dist, blocked.dist)
    # The same graph is reused, but overrides must never mutate its door states.
    assert propped.dist[corridor] < closed.dist[corridor]
    flipped_flags = json.loads(json.dumps(building))
    for floor in flipped_flags["floors"]:
        for door in floor["doors"]:
            door["fireDoor"] = not door.get("fireDoor", False)
    assert np.array_equal(FireModel(flipped_flags, scenario).dist, closed.dist)
    # Sorting by level must not reorder the public floor indexes or query arrays.
    reversed_building = {**building, "floors": list(reversed(building["floors"]))}
    reversed_model = FireModel(reversed_building, scenario)
    reversed_model.step(200)
    for floor in building["floors"]:
        assert reversed_model.snapshot(floor["id"]) == closed.snapshot(floor["id"])
    # With no door penalties, direction alone adds 27 m going down versus up.
    graph = closed.graph
    low = graph.offset[0] + int(graph.floors[0].stair_nodes["SA"][0])
    high = graph.offset[1] + int(graph.floors[1].stair_nodes["SA"][0])
    assert abs(graph.path_distance(low, {})[high] - 3) < 1e-6
    assert abs(graph.path_distance(high, {})[low] - 30) < 1e-6

def check_tuning():
    """Keep the example's illustrative severity targets visible and repeatable."""
    from fire.model import FireModel

    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text())
    scenario = json.loads((root / "contracts/scenario.example.json").read_text())
    for preset in ("kitchen", "battery", "trash", "bedroom"):
        model = FireModel(building, {**scenario, "fire": {**scenario["fire"], "type": preset}}, spread=False)
        floor_index = model.graph.floor_index["F1"]
        offset = model.graph.offset[floor_index]
        count = model.graph.floors[floor_index].n
        for t in range(1, 301):
            model.step(t)
            if preset == "kitchen" and t == 100:
                visibility = model.visibility("F1", 7.5, 8)
                assert visibility < 3, visibility
            if t == 120 and preset in ("kitchen", "battery"):
                fraction = float(model._untenable[offset:offset + count].mean())
                assert fraction >= 0.30 if preset == "battery" else fraction <= 0.05, (preset, fraction)
                print(f"{preset}: {fraction:.1%} of F1 nodes untenable at 120 s")
            if preset == "kitchen" and t == 180:
                assert model.blocked_doors() == {"D101"}, model.blocked_doors()
            if preset in ("trash", "bedroom"):
                assert model.blocked_doors() == set(), (preset, t, model.blocked_doors())



def check_metrics():
    from fire.metrics import compute

    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text())
    floor = building["floors"][0]
    door = next(d for d in floor["doors"] if d["id"] == "D101")
    start, end = np.asarray(door["a"]), np.asarray(door["b"])
    midpoint = (start + end) / 2
    tangent = (end - start) / np.linalg.norm(end - start)
    normal = np.array([-tangent[1], tangent[0]])

    def row(idx, point, status=1, fi=0):
        return [idx, *map(float, point), fi, status]

    frames = []
    for k in range(10):
        # Two stationary queuers, a 1 m/s walker, and an unstarted occupant.
        occupants = [row(0, midpoint - normal * 0.5), row(1, midpoint + normal * 0.5),
                     row(2, midpoint + normal * (k * 0.5 - 2.25)),
                     row(3, midpoint + tangent * 3, status=0)]
        frames.append({"t": k * 0.5, "a": occupants})
    frames.insert(0, {"t": -0.5, "a": [row(0, midpoint - normal * 0.5, 0),
                                        row(1, midpoint + normal * 0.5, 0)]})
    run = {"floors": [f["id"] for f in building["floors"]], "frames": frames,
           "frameInterval": 0.5, "metrics": {"t90": 42, "exitCounts": {"E1": 1}, "custom": 7}}
    result = compute(run, building)
    measured = next(d for d in result["doors"] if d["id"] == "D101")
    assert measured["peakQueue"] == 2 and measured["waitPersonSeconds"] == 10, measured
    assert measured["crossed"] == 1 and measured["flow"] == 2.0, measured
    assert result["t90"] == 42 and result["custom"] == 7 and result["exitCounts"] == {"E1": 1}
    assert "doors" not in run["metrics"]
    json.dumps(result)
    for heatmap, spec in zip(result["heatmaps"], grid_specs(building)):
        assert all(heatmap[key] == value for key, value in spec.items())
        raw = base64.b64decode(heatmap["d"])
        assert len(raw) == heatmap["cols"] * heatmap["rows"]
    empty = compute({**run, "frames": []}, building)
    assert all(d["peakQueue"] == d["waitPersonSeconds"] == d["flow"] == d["crossed"] == 0
               for d in empty["doors"])
    assert all(not any(base64.b64decode(h["d"])) for h in empty["heatmaps"])

    # Unknown speed on first appearance / a floor transfer; a missing frame
    # still uses elapsed time for speed but cannot imply a door crossing.
    sparse = [{"t": 0, "a": [row(4, midpoint - normal * 0.25)]},
              {"t": 1, "a": []},
              {"t": 2, "a": [row(4, midpoint + normal * 0.25)]},
              {"t": 3, "a": [row(4, midpoint + normal * 0.25, fi=1)]},
              {"t": 4, "a": [row(4, midpoint + normal * 0.25)]}]
    measured = next(d for d in compute({**run, "frames": sparse}, building)["doors"]
                    if d["id"] == "D101")
    assert measured["waitPersonSeconds"] == 0.5 and measured["crossed"] == 0, measured

    # Repeated crossings by one agent count once, and a >30 s span sets flow.
    crossings = [{"t": t, "a": [row(5, midpoint + normal * side)]}
                 for t, side in ((0, -0.25), (1, 0.25), (40, -0.25), (61, 0.25))]
    measured = next(d for d in compute({**run, "frames": crossings}, building)["doors"]
                    if d["id"] == "D101")
    assert measured["crossed"] == 1 and measured["flow"] == 1.0, measured

    # Queue distance is to the opening segment, including a wide door's ends.
    wide = fixture_building()
    wide["floors"][0]["doors"][0].update(a=[10.1, 0], b=[10.1, 6])
    standing = [[0, 10, 0.2, 0, 1]]
    wide_run = {"floors": ["F1"], "frameInterval": 0.5,
                "frames": [{"t": 0, "a": standing}, {"t": 1, "a": standing}]}
    assert compute(wide_run, wide)["doors"][0]["peakQueue"] == 1
    # Coarsened heatmap headers match smoke, and unstarted agents add no heat.
    large = big_fixture()
    large_run = {"floors": ["F1"], "frames": [{"t": 0, "a": [[0, 5, 5, 0, 0]]}]}
    heatmap = compute(large_run, large)["heatmaps"][0]
    assert heatmap["cell"] > 0.5 and not any(base64.b64decode(heatmap["d"]))


def check_smoke_queues():
    from copy import deepcopy
    from fire.metrics import compute
    from fire.batch import aggregate

    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text())
    scenario = json.loads((root / "contracts/scenario.example.json").read_text())
    door = next(d for d in building["floors"][0]["doors"] if d["id"] == "D101")
    mx, my = (np.asarray(door["a"]) + np.asarray(door["b"])) / 2
    pair = [[0, float(mx - 0.5), float(my - 0.5), 0, 1],
            [1, float(mx + 0.5), float(my + 0.5), 0, 1]]
    for start, expected in ((100, 10.0), (0, 0.0)):
        # The early warm-up uses t=0; queue frames start at .01 to avoid negative time.
        offset = 0.01 if start == 0 else 0
        frames = [{"t": max(0, start - 0.5), "a": [[*r[:4], 0] for r in pair]}]
        frames += [{"t": start + offset + k * 0.5, "a": pair} for k in range(10)]
        run = {"floors": [f["id"] for f in building["floors"]],
               "frameInterval": 0.5, "frames": frames}
        result = compute(run, building, scenario)
        measured = next(d for d in result["doors"] if d["id"] == "D101")
        assert measured["waitPersonSeconds"] == 10.0 and measured["smokeWait"] == expected, measured
        assert all("smokeWait" not in d for d in compute(run, building)["doors"])
        json.dumps(result, allow_nan=False)

    records = [{"ok": True, "ignition": {"floor": "F1", "room": "R101"},
                "t90": 100, "trapped": 0, "heatmaps": [],
                "doors": [{"id": ident, "floor": "F1", "peakQueue": peak,
                           "waitPersonSeconds": wait, "smokeWait": smoke}
                          for ident, peak, wait, smoke in
                          (("E1", 2, 100, 0), ("DSB1", 10, 40, 40), ("D101", 1, 80, 0))]}]
    original = deepcopy(records)
    result = aggregate(building, scenario, records)
    assert {d["id"]: d["score"] for d in result["doors"]} == {"E1": 54.0, "DSB1": 70.0, "D101": 42.0}
    assert next(d for d in result["doors"] if d["id"] == "DSB1")["meanSmokeWait"] == 40
    assert "40 of them in smoke" in next(t["why"] for t in result["top"] if t["id"] == "DSB1")
    assert records == original
    # Missing doors contribute zero over successful runs, like meanWait.
    absent = {**records[0], "doors": []}
    assert next(d for d in aggregate(building, scenario, records + [absent])["doors"]
                if d["id"] == "DSB1")["meanSmokeWait"] == 20
    for record in records:
        for d in record["doors"]:
            d["smokeWait"] = 0
    assert {d["id"]: d["score"] for d in aggregate(building, scenario, records)["doors"]} == {
        "E1": 76.0, "DSB1": 58.0, "D101": 59.0}
    for d in records[0]["doors"]:
        del d["smokeWait"]
    assert all("meanSmokeWait" not in d for d in aggregate(building, scenario, records)["doors"])


def check_exposure():
    from copy import deepcopy
    from fire.metrics import DOSE_UNIT, SMOKE_D, compute, exposure
    from fire.model import FireModel

    building = fixture_building()
    scenario = {"fire": {"floor": "F1", "room": "A", "x": 8, "y": 5,
                         "type": "kitchen", "start": 0},
                "sprinklers": False, "doors": {}, "maxTime": 400}
    model = FireModel(building, scenario)
    x, y = model.source_xy
    west = [float(x - 3), float(y)]
    run = {"floors": ["F1"], "frameInterval": 0.5,
           "agents": [{"idx": idx, "room": "A" if idx != 1 else "B"} for idx in range(3)],
           "frames": [{"t": k * 0.5,
                       "a": [[0, *west, 0, 2], [1, 17, 3, 0, 3]] +
                            ([[2, *west, 0, 0]] if k <= 80 else [])} for k in range(401)]}
    original = deepcopy(run)
    result = exposure(run, building, scenario)
    assert DOSE_UNIT == 2700 and SMOKE_D == 10
    assert result["dosed"] == 2 and result["dosedIdx"] == [0, 1], result
    assert result["agentsInSmoke"] == 2 and result["personSecondsInSmoke"] > 0
    individual = []
    for idx in range(3):
        one = {**run, "agents": [run["agents"][idx]],
               "frames": [{**frame, "a": [row for row in frame["a"] if row[0] == idx]}
                          for frame in run["frames"]]}
        individual.append(exposure(one, building, scenario)["meanDose"])
    assert abs(individual[0] - 3.4) < 0.15, individual
    assert abs(individual[1] - 1.4) < 0.15 and individual[1] < individual[0], individual
    assert individual[2] < 0.05, individual
    assert np.isclose(result["meanDose"], sum(individual) / 3)
    assert np.isclose(result["maxDose"], individual[0])
    assert run == original
    assert compute(run, building, scenario)["exposure"] == result
    assert "exposure" not in compute(run, building)
    # Snap lookup equals the scalar query, including off-grid and invalid-floor rows.
    probe = {"floors": ["unknown", "F1"], "frameInterval": 0.5, "agents": [{"idx": 9}],
             "frames": [{"t": 200, "a": [[9, *west, 1, 1], [10, -50, -50, 1, 1],
                                         [11, *west, 0, 1], [12, *west, 1, -1]]}]}
    model.step(200)
    expected = float(model._density[model._node("F1", *west)]) * 0.5 / DOSE_UNIT
    assert np.isclose(exposure(probe, building, scenario)["meanDose"], expected)
    empty = exposure({"frames": [], "agents": []}, building, scenario)
    assert empty["meanDose"] == empty["maxDose"] == empty["dosed"] == 0
    json.dumps(result, allow_nan=False)
    json.dumps(empty, allow_nan=False)

    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text())
    scenario = json.loads((root / "contracts/scenario.example.json").read_text())
    stair_times = []
    for overrides in ({}, {"DSA1": "propped"}):
        measured = exposure({"frames": []}, building, {**scenario, "doors": overrides})
        stair_times.append(next(s["smokeAt"] for s in measured["stairs"]
                                if s["floor"] == "F1" and s["group"] == "SA"))
        json.dumps(measured, allow_nan=False)
    assert abs(stair_times[0] - 93) <= 3 and abs(stair_times[1] - 62) <= 3, stair_times
    print(f"exposure: doses={individual}; F1/SA closed/propped smokeAt={stair_times}")


def check_margins():
    from fire.metrics import compute
    from fire.model import FireModel, aset_by_room

    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text())
    scenario = json.loads((root / "contracts/scenario.example.json").read_text())
    available = aset_by_room(building, scenario, scenario["maxTime"])
    assert 150 <= available["R101"] <= 200, available
    assert available["R102"] is None, available
    assert aset_by_room(building, scenario, 1)["R101"] is None  # exclude flame footprint
    model = FireModel(building, scenario)
    model.step(1)
    assert model._footprint.any() and not model._smoke_untenable.any()
    assert np.array_equal(model._untenable, model._footprint | model._smoke_untenable)
    delayed = {**scenario, "fire": {**scenario["fire"], "start": 20}}
    assert aset_by_room(building, delayed, 220)["R101"] == available["R101"] + 20

    run = {"agents": [{"idx": 0, "room": "R101"}, {"idx": 1, "room": "R101"},
                      {"idx": 2, "room": "R102"}],
           "frames": [], "events": [{"type": "exit", "idx": 0, "t": 40},
                                     {"type": "exit", "idx": 1, "t": 60},
                                     {"type": "exit", "idx": 2, "t": 50}],
           "metrics": {"t90": 60, "custom": "preserved"}}
    def measured():
        result = compute(run, building, scenario)
        assert result["t90"] == 60 and result["custom"] == "preserved"
        json.dumps(result, allow_nan=False)
        return {room["id"]: room for room in result["rooms"]}

    rooms = measured()
    assert set(rooms) == {"R101", "R102"}  # omit unoccupied rooms
    assert rooms["R101"]["rset"] == 60 and rooms["R101"]["margin"] > 100
    assert rooms["R102"]["aset"] is None and rooms["R102"]["margin"] is None
    run["events"][1]["t"] = 400
    assert measured()["R101"]["margin"] < 0
    run["events"][1]["type"] = "stair"  # v0 stair-sink fallback
    assert measured()["R101"]["rset"] == 400
    run["events"].append({"type": "exit", "idx": 1, "t": 410})
    assert measured()["R101"]["rset"] == 410  # full exit supersedes stair entry
    run["events"] = [event for event in run["events"] if event["idx"] != 1]
    rooms = measured()
    assert rooms["R101"]["rset"] is None and rooms["R101"]["margin"] is None
    assert "rooms" not in compute(run, building)
    assert "rooms" not in run["metrics"]
    print(f"margins: R101 smoke ASET={available['R101']:g} s; positive/negative/null margins OK")


def check_coupled_slow():
    # Import only for --slow: the ordinary model checks do not need JuPedSim.
    from sim.run import run
    from fire.model import FireModel
    from fire.stub import NoFire

    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text())
    scenario = json.loads((root / "contracts/scenario.example.json").read_text())
    scenario["maxTime"] = 240
    baseline = run(building, scenario, NoFire(building, scenario))
    coupled = run(building, scenario, FireModel(building, scenario))
    smoke = next((entry for entry in coupled["smoke"] if entry["floor"] == "F1"), None)
    assert smoke is not None and smoke["frames"] and smoke["interval"] == 2
    hrr = coupled["fire"]["hrr"]
    assert hrr and all(a[1] <= b[1] for a, b in zip(hrr, hrr[1:])), hrr
    for label, result in (("NoFire", baseline), ("FireModel", coupled)):
        metrics = result["metrics"]
        print(f"{label}: " + " ".join(f"{key}={metrics[key]}" for key in ("t50", "t90", "t100", "trapped")),
              flush=True)
    assert baseline["metrics"] != coupled["metrics"], "sim ignores fire or smoke is too weak"
    out = root / "data/runs/ws-d-coupled.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(coupled, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {out.relative_to(root)}", flush=True)


def check_batch_setup():
    from copy import deepcopy
    from fire.batch import _ignitions, _tasks, _init, _run_one, run_many

    building = fixture_building()
    base = {"id": "batch-check", "seed": 7, "brain": "llm",
            "fire": {"type": "bedroom", "growth": "slow", "start": 12}}
    original = deepcopy(base)
    ignitions = _ignitions(building, base)
    tasks = _tasks(building, base, ignitions, (1, 3))
    assert len(tasks) == 4 and base == original
    for task in tasks:
        scenario = task["scenario"]
        room = next(r for r in building["floors"][0]["rooms"] if r["id"] == task["ignition"]["room"])
        assert shapely.Polygon(room["polygon"]).contains(shapely.Point(scenario["fire"]["x"], scenario["fire"]["y"]))
        assert scenario["brain"] == "rules"
        assert all(scenario["fire"][key] == base["fire"][key] for key in ("type", "growth", "start"))
    large = deepcopy(building)
    large["floors"][0]["rooms"] = [{"id": f"R{i}", "type": "office", "polygon": room["polygon"]}
                                       for i in range(60)]
    selected = _ignitions(large, base)
    assert len(selected) == 40 and selected == _ignitions(large, base)
    assert [int(i["room"][1:]) for i in selected] == sorted(int(i["room"][1:]) for i in selected)
    assert len(_ignitions(large, base, 4)) == 4
    large["floors"][0]["rooms"][0]["type"] = "corridor"
    large["floors"][0]["rooms"][1]["type"] = "stair"
    assert len(_ignitions(large, base, 100)) == 58
    empty = run_many(building, base, [], progress=False)
    assert empty["runs"] == empty["failed"] == [] and empty["base"] == base
    empty["base"]["fire"]["type"] = "trash"
    assert base == original
    # Bad worker input is returned as JSON data, never as an exception object.
    _init(building)
    error = _run_one({"scenario": {"id": "invalid"}, "ignition": {}})
    assert error["ok"] is False and error["scenarioId"] == "invalid" and isinstance(error["error"], str)
    json.dumps(error)


def check_aggregate():
    from copy import deepcopy
    from fire.batch import aggregate

    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text())
    base = json.loads((root / "contracts/scenario.example.json").read_text())
    records = []
    for index, (room, t90, trapped) in enumerate((("R101", 100, 1), ("R101", None, 3),
                                               ("R102", None, 0))):
        records.append({"ok": True, "scenarioId": f"hand-{index}", "seed": index,
                        "ignition": {"floor": "F1", "room": room}, "t90": t90,
                        "t100": None, "trapped": trapped,
                        "doors": [{"id": door, "floor": "F1", "peakQueue": peak,
                                   "waitPersonSeconds": wait}
                                  for door, peak, wait in (("E1", 2, 100), ("DSB1", 10, 40),
                                                           ("D101", 1, 80))],
                        "heatmaps": [{"floor": "F1", "origin": [0, 0], "cell": 0.5,
                                      "cols": 2, "rows": 1,
                                      "d": base64.b64encode(bytes(([100, 0], [0, 100], [0, 100])[index])).decode("ascii")}]})
    original = deepcopy(records)
    result = aggregate(building, base, records + [{"ok": False, "error": "ignored"}])
    assert records == original
    assert result["rooms"][0]["riskT90"] == (100 + base["maxTime"]) / 2
    assert result["rooms"][0]["riskTrapped"] == 2 and result["rooms"][0]["n"] == 2
    assert result["rooms"][1]["riskT90"] is None
    assert all("riskDosed" not in room for room in result["rooms"])
    with_dose = deepcopy(records)
    for record, dosed in zip(with_dose, (2, 4, 1)):
        record["dosed"] = dosed
    assert [r["riskDosed"] for r in aggregate(building, base, with_dose)["rooms"]] == [3, 1]
    del with_dose[-1]["dosed"]
    assert all("riskDosed" not in r for r in aggregate(building, base, with_dose)["rooms"])
    scores = {door["id"]: door["score"] for door in result["doors"]}
    assert scores == {"E1": 76.0, "DSB1": 58.0, "D101": 59.0}, scores
    top = result["top"]
    assert 3 <= len(top) <= 5 and top == sorted(top, key=lambda item: -item["score"])
    assert {item["id"]: item["kind"] for item in top if item["kind"] != "room"} == {
        "E1": "exit", "DSB1": "stair", "D101": "door"}
    assert all(item["why"].isascii() and any(c.isdigit() for c in item["why"]) for item in top)
    assert "Stair SB door" in next(item["why"] for item in top if item["id"] == "DSB1")
    heatmap = result["heatmaps"][0]
    raw = base64.b64decode(heatmap["d"])
    assert len(raw) == heatmap["cols"] * heatmap["rows"] and list(raw) == [50, 100]
    assert aggregate(building, base, []) == {"rooms": [], "doors": [], "heatmaps": [], "top": []}
    zeros = deepcopy(records[:1])
    for door in zeros[0]["doors"]:
        door.update(peakQueue=0, waitPersonSeconds=0)
    zeros[0]["heatmaps"][0]["d"] = base64.b64encode(bytes(2)).decode("ascii")
    zero_result = aggregate(building, base, zeros)
    assert all(d["score"] == 0 for d in zero_result["doors"])
    assert base64.b64decode(zero_result["heatmaps"][0]["d"]) == bytes(2)
    censored = aggregate(building, base, records[2:])
    assert "not out by" in next(item["why"] for item in censored["top"] if item["kind"] == "room")
    invalid = deepcopy(records[:1])
    invalid[0]["heatmaps"][0]["d"] = ""
    try:
        aggregate(building, base, invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("malformed heatmap must fail")
    example_path = root / "contracts/batch.example.json"
    if example_path.exists():
        from fire.batch import run_many
        batch = run_many(building, base, [], progress=False)
        batch.update(result, runs=[{k: v for k, v in records[0].items()
                                    if k in ("scenarioId", "seed", "ignition", "t90", "t100", "trapped")}])
        example = json.loads(example_path.read_text())
        assert set(batch) >= set(example) - {"placeholder"}
        assert isinstance(batch["base"], type(example["base"]))
        for key in ("runs", "rooms", "doors", "top"):
            assert set(batch[key][0]) >= set(example[key][0]), key
    json.dumps(result, allow_nan=False)


def check_ranges():
    from copy import deepcopy
    from unittest.mock import patch
    from fire.batch import aggregate, run_many, seed_ranges

    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text())
    base = json.loads((root / "contracts/scenario.example.json").read_text())
    records = []
    for seed, t90 in zip((1, 2, 3), (100, None, 120)):
        for room in ("R101", "R102"):
            records.append({"ok": True, "scenarioId": f"{room}-{seed}", "seed": seed,
                            "ignition": {"floor": "F1", "room": room},
                            "t90": t90 if room == "R101" else None, "t100": None,
                            "trapped": seed if room == "R101" else 0, "dosed": seed * 2,
                            "heatmaps": [],
                            "doors": [{"id": ident, "floor": "F1", "peakQueue": wait // 10,
                                       "waitPersonSeconds": wait}
                                      for ident, wait in (("DSB1", 100), ("E1", 80),
                                                          ("D101", 20 if seed == 3 else 60),
                                                          ("D104", 40 if seed == 3 else 10))]})
    original = deepcopy(records)
    result = seed_ranges(building, base, records + [{"ok": False, "error": "ignored"}])
    assert records == original
    rooms = {r["id"]: r for r in result["rooms"]}
    assert rooms["R101"]["riskT90Range"] == {"min": 100., "median": 120., "max": float(base["maxTime"])}
    assert rooms["R102"]["riskT90Range"] is None
    assert rooms["R101"]["riskTrappedRange"] == {"min": 1., "median": 2., "max": 3.}
    assert rooms["R101"]["riskDosedRange"] == {"min": 2., "median": 4., "max": 6.}
    assert result["stability"]["heldIn"] == 2 and not result["stability"]["stable"]
    assert result["stability"]["seeds"] == [1, 2, 3]
    assert next(t for t in result["top"] if t["id"] == "D101")["seedsInTop3"] == 2
    assert next(t for t in result["top"] if t["kind"] == "room")["seedsInTop3"] == 3
    summaries = [aggregate(building, base, [r for r in records if r["seed"] == seed])
                 for seed in (1, 2, 3)]
    for door in result["doors"]:
        for source, field in (("score", "scoreRange"), ("meanWait", "meanWaitRange")):
            values = sorted(next(d[source] for d in summary["doors"] if d["id"] == door["id"])
                            for summary in summaries)
            assert door[field] == dict(zip(("min", "median", "max"), values))
    assert result["stability"]["why"].isascii() and "ranks first in 3 of 3" in result["stability"]["why"]
    with patch("fire.batch._records", return_value=records):
        batch = run_many(building, base, [], progress=False)
    assert batch["stability"] == result["stability"]
    single = [r for r in records if r["seed"] == 1]
    assert seed_ranges(building, base, single) == {}
    with patch("fire.batch._records", return_value=single):
        batch = run_many(building, base, [], progress=False)
    assert "stability" not in batch
    assert all(not any(key.endswith("Range") for key in item)
               for item in batch["rooms"] + batch["doors"])
    missing = deepcopy(records)
    for record in missing:
        record.pop("dosed")
    assert all("riskDosedRange" not in r for r in seed_ranges(building, base, missing)["rooms"])
    json.dumps(result, allow_nan=False)
    print("ranges: room bounds, per-seed scores, ranking stability and single-seed compatibility checked", flush=True)


def check_ranges_slow():
    from fire.batch import run_many
    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text())
    base = json.loads((root / "contracts/scenario.example.json").read_text())
    base["occupants"]["total"] = 60
    base["maxTime"] = 120
    result = run_many(building, base, [dict(floor="F1", room=r) for r in ("R101", "R105")],
                      seeds=(1, 2), workers=2, timeout_s=600)
    assert not result["failed"], result["failed"]
    assert result["stability"]["n"] == 2
    for room in result["rooms"]:
        for field in ("riskT90Range", "riskTrappedRange", "riskDosedRange"):
            limits = room[field]
            assert limits is None or limits["min"] <= limits["median"] <= limits["max"]
    print(result["stability"]["why"], flush=True)


def check_timing():
    from contextlib import redirect_stdout
    from io import StringIO
    from unittest.mock import patch
    from fire.batch import main, plan_rooms, run_many
    # Load before patching batch.run_many: whatif keeps a module-level reference.
    import fire.whatif

    assert plan_rooms(1800, 60, (1, 2, 3), 12, variants=3) == 15
    assert plan_rooms(0.01, 60, (1, 2, 3), 12, variants=3) == 1
    for kwargs in ({"pilot_s": 0}, {"budget_s": float("inf")}, {"seeds": ()}, {"workers": 0}):
        values = dict(budget_s=1800, pilot_s=60, seeds=(1,), workers=2)
        values.update(kwargs)
        try:
            plan_rooms(**values)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid planning inputs must fail")
    building = fixture_building()
    base = {"id": "timing", "seed": 1, "fire": {}, "maxTime": 120}
    def fake(task):
        sc = task["scenario"]
        if sc["seed"] == 2:
            return {"ok": False, "scenarioId": sc["id"], "wallS": 2.0, "error": "fake failure"}
        return {"ok": True, "scenarioId": sc["id"], "seed": sc["seed"],
                "ignition": task["ignition"], "wallS": 6.0, "t90": 60, "t100": 80,
                "trapped": 0, "doors": [], "heatmaps": []}
    output = StringIO()
    with patch("fire.batch._run_one", side_effect=fake), redirect_stdout(output):
        batch = run_many(building, base, seeds=(1, 2), workers=1)
    timing = batch["timing"]
    assert timing["runs"] == 4 and timing["failed"] == 2 and timing["workers"] == 1
    assert timing["wallS"] >= 0 and timing["meanRunS"] == 4.0
    assert all("wallS" not in run for run in batch["runs"])
    assert "eta " in output.getvalue() and "eta 0.0 min" in output.getvalue().splitlines()[-1]
    empty = run_many(building, base, [], workers=1, progress=False)
    assert empty["timing"]["runs"] == 0 and empty["timing"]["meanRunS"] == 0.0
    json.dumps(batch, allow_nan=False)

    # Exercise the CLI budget wiring without running a simulation or writing artifacts.
    root = Path(__file__).resolve().parents[1]
    argv = ["fire.batch", str(root / "contracts/building.example.json"),
            str(root / "contracts/scenario.example.json"), "--budget-min", "3",
            "--seeds", "1,2", "--workers", "4", "--whatif", "--whatif-rooms", "99"]
    pilot = {"ok": True, "wallS": 60.0, "exitCounts": {}}
    output = StringIO()
    with (patch("sys.argv", argv), patch("fire.batch._run_one", return_value=pilot),
          patch("fire.batch.run_many", return_value={"runs": [], "failed": [], "top": []}) as sweep,
          patch("fire.whatif.add_whatif", side_effect=lambda b, s, batch, **kw: batch) as whatif,
          patch("pathlib.Path.write_text"), patch("pathlib.Path.mkdir"), redirect_stdout(output)):
        main()
    # floor(180 * 4 / (60 * 2 * 2 * 4)) == 0, clamped to one room.
    assert len(sweep.call_args.args[2]) == 1
    assert sweep.call_args.args[3:] == ((1, 2), 4)
    assert whatif.call_args.kwargs == {"rooms": 1, "workers": 4}
    assert "3 what-ifs -> 1 rooms" in output.getvalue()
    print("timing: worker durations, ETA, failure totals and pilot budget checked", flush=True)


def check_batch_pool_slow():
    from copy import deepcopy
    from fire.batch import run_many

    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text())
    base = json.loads((root / "contracts/scenario.example.json").read_text())
    base["maxTime"] = 120
    base["occupants"] = {"total": 60, "mix": base["occupants"]["mix"]}
    original = deepcopy(base)
    ignitions = [{"floor": "F1", "room": room} for room in ("R101", "R105")]
    started = time.perf_counter()
    parallel = run_many(building, base, ignitions, seeds=(1,), workers=2, timeout_s=240)
    assert len(parallel["runs"]) == 2 and parallel["failed"] == [], parallel["failed"]
    assert time.perf_counter() - started < 240
    serial = run_many(building, base, ignitions, seeds=(1,), workers=1)
    assert parallel["runs"] == serial["runs"], (parallel["runs"], serial["runs"])
    assert all(r["dosed"] >= 0 and r["smokeSeconds"] >= 0 for r in parallel["runs"])
    assert all("riskDosed" in room for room in parallel["rooms"])
    assert base == original
    # Kill a spawned batch before any simulation can finish; don't hang shutdown.
    started = time.perf_counter()
    expired = run_many(building, base, ignitions, seeds=(1,), workers=2, timeout_s=0.001, progress=False)
    assert expired["runs"] == [] and len(expired["failed"]) == 2
    assert time.perf_counter() - started < 10
    print("batch: 2 spawned runs match inline runs; timeout records both failures", flush=True)


def check_exit_comparison():
    from copy import deepcopy
    from unittest.mock import patch
    from fire.batch import add_exit_criticality

    building = {"floors": [{"id": "F1", "exits": [{"door": "E1"}, {"door": "E2"}]}]}
    base = {"maxTime": 120, "doors": {"D1": "propped"}}

    def record(room, seed, t90, trapped):
        return {"ignition": {"floor": "F1", "room": room}, "seed": seed,
                "t90": t90, "trapped": trapped}

    batch = {"rooms": [{"id": "A", "floor": "F1", "riskT90": 60},
                        {"id": "B", "floor": "F1", "riskT90": None}],
             "runs": [record("A", 1, 60, 0), record("B", 1, None, 1), record("B", 2, 80, 0)],
             "top": [{"kind": "exit", "id": "E2", "floor": "F1", "score": 30, "why": "old"}]}
    original = deepcopy(batch)

    def rerun(b, sc, ignitions, seeds, workers, timeout):
        assert ignitions == [{"floor": "F1", "room": "B"}] and seeds == [1, 2]
        assert sc["doors"]["D1"] == "propped" and timeout == 12 and workers == 1
        if sc["doors"].get("E1") == "blocked":
            return {"runs": [record("B", 1, None, 3), record("B", 2, None, 2)]}
        # Seed 1 failed: compare only seed 2 on both sides.
        return {"runs": [record("B", 2, 90, 1)]}

    with patch("fire.batch.run_many", side_effect=rerun):
        result = add_exit_criticality(building, base, batch, workers=1, timeout_s=12, top_rooms=1)
    assert result["exits"] == [
        {"id": "E1", "floor": "F1", "dT90": 20, "dTrapped": 2, "n": 2},
        {"id": "E2", "floor": "F1", "dT90": 10, "dTrapped": 1, "n": 1}]
    assert [item["score"] for item in result["top"]] == [100, 50]
    assert batch == original and base["doors"] == {"D1": "propped"}
    assert "mean of 2 fires" in result["top"][0]["why"]
    with patch("fire.batch.run_many", return_value={"runs": []}):
        empty = add_exit_criticality(building, base, batch, top_rooms=0)
    assert all(e["n"] == 0 and e["dT90"] == 0 for e in empty["exits"])
    assert empty["top"] == batch["top"]


def check_exits_slow():
    from copy import deepcopy
    from fire.batch import run_many, add_exit_criticality

    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text())
    base = json.loads((root / "contracts/scenario.example.json").read_text())
    base["maxTime"] = 120
    base["occupants"] = {"total": 60, "mix": base["occupants"]["mix"]}
    original = deepcopy(base)
    ignitions = [{"floor": "F1", "room": room} for room in ("R101", "R105")]
    batch = run_many(building, base, ignitions, seeds=(1,), workers=2, timeout_s=240)
    assert len(batch["runs"]) == 2 and not batch["failed"]
    result = add_exit_criticality(building, base, batch, workers=2, timeout_s=240)
    assert {e["id"] for e in result["exits"]} == {"E1", "E2"}
    assert all(np.isfinite(e["dT90"]) and np.isfinite(e["dTrapped"]) and e["n"] == 2
               for e in result["exits"])
    assert len(result["top"]) <= 5 and base == original and "exits" not in batch
    print("exits: E1/E2 blocked comparisons completed with two matched runs each", flush=True)


def check_whatif():
    from copy import deepcopy
    from unittest.mock import patch
    from fire.whatif import stair_doors, default_variants, compare, add_whatif, smoke_base

    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text())
    base = json.loads((root / "contracts/scenario.example.json").read_text())
    base["doors"] = {"D101": "closed", "DSA1": "closed"}
    assert set(stair_doors(building)) == {"DSA1", "DSB1", "DSA2", "DSB2"}

    def record(room, seed, t90, trapped=0, dosed=1, smoke=100):
        return {"ignition": {"floor": "F1", "room": room}, "seed": seed, "t90": t90,
                "trapped": trapped, "dosed": dosed, "smokeSeconds": smoke,
                "exitCounts": {"E1": 45, "E2": 35}}

    baseline = [record("R101", 1, 60), record("R105", 1, None, 2), record("R105", 2, 80)]
    variants = default_variants(building, base, baseline[:2])
    assert variants[1]["doors"] == {"E1": "blocked"}
    one_exit = deepcopy(building)
    for floor in one_exit["floors"]:
        floor["exits"] = [e for e in floor["exits"] if e["door"] == "E1"]
    assert "blockedExit" not in {v["id"] for v in default_variants(one_exit, base, baseline)}
    assert "sprinklers" not in {v["id"] for v in default_variants(building, {**base, "sprinklers": True}, baseline)}
    # Count ties prefer width, then id, independent of building order.
    tied = deepcopy(building)
    doors = {d["id"]: d for f in tied["floors"] for d in f["doors"]}
    doors["E2"]["width"] = doors["E1"]["width"] + 1
    assert default_variants(tied, base, [])[1]["doors"] == {"E2": "blocked"}
    doors["E2"]["width"] = doors["E1"]["width"]
    assert default_variants(tied, base, [])[1]["doors"] == {"E1": "blocked"}
    modified = [record("R101", 1, 80, 1, 3, 160), record("R105", 1, 100, 1, 2, 120)]
    stats = compare(base, baseline, modified)
    assert stats == {"n": 2, "dT90": (120 - base["maxTime"]) / 2,
                     "dT90Min": 100 - base["maxTime"], "dT90Max": 20,
                     "slower": 1, "faster": 1, "dTrapped": 0, "dDosed": 1.5, "dSmokeSeconds": 40}, stats
    old = [{k: v for k, v in r.items() if k not in ("dosed", "smokeSeconds")} for r in modified]
    assert "dDosed" not in compare(base, baseline, old)
    assert "dSmokeSeconds" not in compare(base, baseline, old)
    assert compare(base, baseline, [])["n"] == 0
    boundary = compare(base, [record("R101", 1, 60), record("R105", 1, 60)],
                       [record("R101", 1, 61), record("R105", 1, 59)])
    assert boundary["slower"] == boundary["faster"] == 0
    batch = {"runs": baseline, "rooms": [{"id": "R101", "floor": "F1", "riskT90": 60},
                                           {"id": "R105", "floor": "F1", "riskT90": None}]}
    original, original_base = deepcopy(batch), deepcopy(base)
    calls = []

    def rerun(b, sc, ignitions, seeds, workers, timeout, progress):
        assert b is building and seeds == [1, 2] and workers == 1 and timeout == 12 and not progress
        assert sc["doors"]["D101"] == "closed"
        variant = variants[len(calls) % 3]
        assert sc["id"] == f"{base['id']}-{variant['id']}"
        assert sc["doors"] == {**base["doors"], **variant["doors"]}
        assert sc["sprinklers"] == variant["sprinklers"]
        calls.append(ignitions)
        return {"runs": modified}

    with patch("fire.whatif.run_many", side_effect=rerun):
        result = add_whatif(building, base, batch, workers=1, timeout_s=12, progress=False)
        subset = add_whatif(building, base, batch, rooms=1, workers=1, timeout_s=12, progress=False)
    assert calls[:3] == [[{"floor": "F1", "room": "R101"}, {"floor": "F1", "room": "R105"}]] * 3
    assert calls[3:] == [[{"floor": "F1", "room": "R105"}]] * 3
    assert len(result["whatIf"]) == 3 and all(r["n"] == 2 for r in result["whatIf"])
    assert all(r["n"] == 1 for r in subset["whatIf"])
    assert all(r["why"].isascii() and any(c.isdigit() for c in r["why"]) for r in result["whatIf"])
    # The percent is written at the source: base mean 100 over the two matched fires, +40 person-seconds.
    assert all(r["baseSmokeSeconds"] == 100 and r["smokePct"] == 40.0 and "(+40%)" in r["why"]
               for r in result["whatIf"])
    assert all(r["baseSmokeSeconds"] == 100 and r["smokePct"] == 20.0 for r in subset["whatIf"])
    assert smoke_base(baseline, old, compare(base, baseline, old)) == {}
    nothing = [record("R101", 1, 60, smoke=0), record("R105", 1, None, 2, smoke=0)]
    assert smoke_base(nothing, modified, compare(base, nothing, modified)) == {
        "baseSmokeSeconds": 0.0, "smokePct": None}
    assert batch == original and base == original_base
    result["runs"][0]["exitCounts"]["E1"] = -1
    assert batch == original
    json.dumps(subset, allow_nan=False)


def check_whatif_slow():
    from fire.batch import run_many
    from fire.whatif import add_whatif

    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text())
    base = json.loads((root / "contracts/scenario.example.json").read_text())
    base["maxTime"] = 240
    base["occupants"] = {"total": 60, "mix": base["occupants"]["mix"]}
    ignitions = [{"floor": "F1", "room": room} for room in ("R101", "R105")]
    batch = run_many(building, base, ignitions, seeds=(1,), workers=2, timeout_s=240)
    assert len(batch["runs"]) == 2 and not batch["failed"]
    assert all(sum(r["exitCounts"].values()) > 0 for r in batch["runs"])
    result = add_whatif(building, base, batch, workers=2, timeout_s=240)
    assert len(result["whatIf"]) == 3
    assert all(r["n"] == 2 and all(np.isfinite(r[k]) for k in
               ("dT90", "dT90Min", "dT90Max", "dTrapped", "dDosed", "dSmokeSeconds"))
               for r in result["whatIf"])
    print("what-if: three variants with two matched fires each", flush=True)


def check_fixes():
    from copy import deepcopy
    from unittest.mock import patch
    from shapely.geometry import Polygon
    from fire.fixes import renormalize, widen_door, candidate_fixes, add_fixes
    from fire.batch import door_label
    from fire.presets import sprinklers_matter

    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text())
    base = json.loads((root / "contracts/scenario.example.json").read_text())
    original = deepcopy(building)
    for path in (root / "contracts/building.example.json", office_path()):
        source = json.loads(path.read_text(encoding="utf-8"))
        rebuilt = renormalize(source)
        for before, after in zip(source["floors"], rebuilt["floors"]):
            area = lambda f: sum(Polygon(w["outer"], w["holes"]).area for w in f["walkable"])
            assert abs(area(before) - area(after)) < .01
            for field in ("exits", "stairs"):
                assert [v["id"] for v in before[field]] == [v["id"] for v in after[field]]
            assert [d["connects"] for d in before["doors"]] == [d["connects"] for d in after["doors"]]
    widened = widen_door(building, "DSB1")
    floor = widened["floors"][0]
    door = next(d for d in floor["doors"] if d["id"] == "DSB1")
    assert door["width"] == 1.5 and np.isclose(np.linalg.norm(np.array(door["a"]) - door["b"]), 1.5)
    assert door["connects"] == ["SB1", "C1"]
    assert abs(sum(Polygon(w["outer"], w["holes"]).area for w in floor["walkable"]) - 542.36) < .02
    exit_area = lambda b: Polygon(next(e for f in b["floors"] for e in f["exits"] if e["id"] == "E1")["polygon"]).area
    assert np.isclose(exit_area(building), 1.9) and np.isclose(exit_area(widen_door(building, "E1")), 2.15)
    assert building == original
    for did, extra in (("missing", .5), ("DSB1", 0), ("DSB1", float("nan"))):
        try:
            widen_door(building, did, extra)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid widening accepted")
    # Reject a normalization that silently changes connectivity or components.
    altered = deepcopy(widened)
    altered["floors"][0]["walkable"].append(altered["floors"][0]["walkable"][0])
    with patch("fire.fixes.renormalize", return_value=altered):
        try:
            widen_door(building, "DSB1")
        except ValueError:
            pass
        else:
            raise AssertionError("topology change accepted")
    assert door_label(building, "F1", "missing") == ("door", "Door missing")
    unnamed = deepcopy(building)
    next(e for e in unnamed["floors"][0]["exits"] if e["door"] == "E1").pop("name", None)
    assert door_label(unnamed, "F1", "E1") == ("exit", "Exit E1")
    assert sprinklers_matter(base)
    trash = deepcopy(base)
    trash["fire"]["type"] = "trash"
    assert not sprinklers_matter(trash) and not sprinklers_matter({**base, "sprinklers": True})
    record = lambda room, seed, time, smoke: dict(ignition=dict(floor="F1", room=room), seed=seed,
                                                t90=time, trapped=0, smokeSeconds=smoke)
    batch = dict(top=[dict(kind="stair", id="DSB1", floor="F1")],
                 rooms=[dict(id="R101", floor="F1", riskT90=80), dict(id="R105", floor="F1", riskT90=None)],
                 runs=[record("R101", 1, 80, 100), record("R105", 2, 100, 300)])
    fixes, skipped = candidate_fixes(building, trash, batch)
    assert "sprinklers" in {f["id"] for f in skipped} and "sprinklers" not in {f["id"] for f in fixes}
    assert "sprinklers" in {f["id"] for f in candidate_fixes(building, base, batch)[0]}
    propped = {**base, "doors": {"DSA1": "propped", "D101": "blocked"}}
    candidates, _ = candidate_fixes(building, propped, batch)
    assert next(f for f in candidates if f["id"] == "selfClosers")["doors"] == {"DSA1": "closed"}
    assert next(f for f in candidates if f["id"] == "keepClear-D101")["doors"]["D101"] == next(
        d["state"] for d in building["floors"][0]["doors"] if d["id"] == "D101")
    snapshot, base_snapshot = deepcopy(batch), deepcopy(base)
    calls = []

    def rerun(b, scenario, ignitions, seeds, workers, timeout, progress):
        assert seeds == sorted({r["seed"] for r in batch["runs"] if r["ignition"] in ignitions})
        assert workers == 1 and timeout == 12 and not progress
        assert scenario["id"].startswith(base["id"] + "-")
        if scenario["id"].endswith("widen-DSB1"):
            assert b is not building
            assert next(d for d in b["floors"][0]["doors"] if d["id"] == "DSB1")["width"] == 1.5
            delta = -10
        else:
            assert b is building and scenario["sprinklers"]
            delta = 2
        calls.append(ignitions)
        return dict(runs=[{**r, "t90": r["t90"] + delta, "smokeSeconds": r["smokeSeconds"] * .8}
                          for r in batch["runs"] if r["ignition"] in ignitions])

    with patch("fire.fixes.run_many", side_effect=rerun):
        result = add_fixes(building, base, batch, workers=1, timeout_s=12, progress=False)
        subset = add_fixes(building, base, batch, rooms=1, workers=1, timeout_s=12, progress=False)
    assert result["fixes"][0]["id"] == "widen-DSB1"
    assert all(np.isclose(f["smokePct"], -20) for f in result["fixes"])
    # D22: the hand-made sprinkler rerun is 2 s slower (a cost) as well as 20% less smoke (a gain), so it is a
    # trade-off and sorts after the widened door, which only gains.
    assert [(f["id"], f["helps"], f["tradeoff"]) for f in result["fixes"]] == [
        ("widen-DSB1", True, False), ("sprinklers", False, True)]
    assert all(f["n"] == 1 for f in subset["fixes"])
    assert calls[0] == [dict(floor="F1", room="R101"), dict(floor="F1", room="R105")]
    assert calls[-1] == [dict(floor="F1", room="R105")]
    assert all(f["why"].isascii() and any(c.isdigit() for c in f["why"]) for f in result["fixes"])
    assert batch == snapshot and base == base_snapshot
    variant = dict(id="proppedStairs", n=2, dT90=3, dT90Min=-2, dT90Max=8,
                   slower=1, faster=0, dTrapped=.5, dDosed=1, dSmokeSeconds=40)
    derived = {**batch, "top": [], "whatIf": [variant, {**variant, "id": "blockedExit", "doors": {"E1": "blocked"}}]}
    with patch("fire.fixes.run_many", side_effect=AssertionError("derived fix reran")):
        inverses = add_fixes(building, trash, derived)
    assert len(inverses["fixes"]) == 2
    for fix in inverses["fixes"]:
        assert fix["dT90"] == -3 and fix["dT90Min"] == -8 and fix["dT90Max"] == 2
        assert fix["slower"] == 0 and fix["faster"] == 1 and fix["dTrapped"] == -.5
        assert fix["dDosed"] == -1 and fix["dSmokeSeconds"] == -40 and fix["smokePct"] is None and fix["helps"]
    # A what-if that saved its baseline mean (200) gives the derived fix a percent of the propped or
    # blocked state: -40 / (200 + 40).
    based = {**derived, "whatIf": [{**w, "baseSmokeSeconds": 200} for w in derived["whatIf"]]}
    with patch("fire.fixes.run_many", side_effect=AssertionError("derived fix reran")):
        percents = add_fixes(building, trash, based)
    assert len(percents["fixes"]) == 2
    for fix in percents["fixes"]:
        assert abs(fix["smokePct"] - -16.7) < .1 and "17% less time in smoke" in fix["why"], fix
    # A sprinkler what-if that paired every baseline fire already measured the sprinkler fix: reused, not rerun.
    sprinkled = {**batch, "whatIf": [dict(
        id="sprinklers", label="Sprinklers on", doors={}, sprinklers=True, n=2, dT90=-3.0, dT90Min=-4.0, dT90Max=-2.0,
        slower=0, faster=2, dTrapped=0.0, dDosed=0.0, dSmokeSeconds=-50.0, baseSmokeSeconds=200.0, smokePct=-25.0)]}
    reran = []

    def spy(b, scenario, *rest):
        reran.append(scenario["id"].removeprefix(base["id"] + "-"))
        return rerun(b, scenario, *rest)

    with patch("fire.fixes.run_many", side_effect=spy):
        reused = add_fixes(building, base, sprinkled, workers=1, timeout_s=12, progress=False)
        short = add_fixes(building, base, {**sprinkled, "whatIf": [{**sprinkled["whatIf"][0], "n": 1}]},
                          workers=1, timeout_s=12, progress=False)
        partial = add_fixes(building, base, sprinkled, rooms=1, workers=1, timeout_s=12, progress=False)
    # Reused: only the widened door reruns. A what-if with fewer pairs than baseline fires, or a fix limited to
    # one room, reruns the sprinklers too.
    assert reran == ["widen-DSB1", "widen-DSB1", "sprinklers", "widen-DSB1", "sprinklers"], reran
    fix = next(f for f in reused["fixes"] if f["id"] == "sprinklers")
    assert (fix["n"], fix["dT90"], fix["dSmokeSeconds"], fix["smokePct"]) == (2, -3.0, -50.0, -25.0)
    assert fix["helps"] and "derivedFrom" not in fix and fix["kind"] == "sprinklers" and fix["sprinklers"] is True
    assert fix["why"] == ("Sprinklers: 90% out 3 s sooner on average and 25% less time in smoke across 2 fires "
                          "(faster in 2); +0.0 trapped per fire.")
    assert next(f for f in short["fixes"] if f["id"] == "sprinklers")["n"] == 2  # rerun, not the what-if's 1
    assert next(f for f in partial["fixes"] if f["id"] == "sprinklers")["n"] == 1
    json.dumps(result, allow_nan=False)
    json.dumps(inverses, allow_nan=False)
    json.dumps(percents, allow_nan=False)
    json.dumps(reused, allow_nan=False)


def check_fixes_slow():
    from fire.batch import run_many
    from fire.fixes import add_fixes

    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text())
    base = json.loads((root / "contracts/scenario.example.json").read_text())
    base["maxTime"] = 240
    base["occupants"] = {"total": 60, "mix": base["occupants"]["mix"]}
    ignitions = [dict(floor="F1", room=r) for r in ("R101", "R105")]
    batch = run_many(building, base, ignitions, seeds=(1,), workers=2, timeout_s=240)
    assert not batch["failed"]
    result = add_fixes(building, base, batch, top=1, workers=2, timeout_s=240)
    assert len(result["fixes"]) == 2, result["fixesSkipped"]
    assert {f["kind"] for f in result["fixes"]} == {"widen", "sprinklers"}
    assert all(f["n"] == 2 and all(np.isfinite(f[k]) for k in ("dT90", "dTrapped", "dSmokeSeconds"))
               for f in result["fixes"])
    print("fixes: widened door and sprinklers with two matched fires each", flush=True)


def check_tradeoffs():
    from copy import deepcopy
    from unittest.mock import patch
    from fire.fixes import VERDICT, _inverse, _join, _why, add_fixes, restate, verdict
    from fire.headlines import build_headlines
    from fire.whatif import _why as whatif_why, add_whatif, room_deltas, trapped_note

    root = Path(__file__).resolve().parents[1]
    example = json.loads((root / "contracts/building.example.json").read_text(encoding="utf-8"))
    base = json.loads((root / "contracts/scenario.example.json").read_text(encoding="utf-8"))
    counting = " (people no longer trapped keep counting)"
    assert VERDICT == {"t90": 1.0, "trapped": 0.05, "smokePct": 5.0}

    def numbers(dT90, smokePct, dTrapped, n=36, **more):
        return {"n": n, "dT90": dT90, "smokePct": smokePct, "dTrapped": dTrapped, **more}

    # The verdict, on numbers measured in the demo batches (dT90, smokePct, dTrapped, in this order).
    assert verdict(numbers(-58.29, -67.7, 1.31)) == {"helps": False, "tradeoff": True,
                                                      "costs": ["1.3 more trapped per fire"]}
    assert verdict(numbers(-10.6, -2.9, -0.19)) == {"helps": True, "tradeoff": False, "costs": []}
    assert verdict(numbers(-6.7, 18.2, -2.25)) == {"helps": False, "tradeoff": True,
                                                    "costs": ["18% more time in smoke" + counting]}
    assert verdict(numbers(18, -3, 0.5)) == {"helps": False, "tradeoff": False,
                                              "costs": ["90% out 18 s later on average", "0.5 more trapped per fire"]}
    assert verdict(numbers(-58.29, -67.7, 1.31, n=0)) == {"helps": False, "tradeoff": False, "costs": []}
    assert verdict({"n": 4, "dT90": 0.0, "dTrapped": 0.0}) == {"helps": False, "tradeoff": False, "costs": []}
    assert verdict(numbers(12.0, 18.0, 1.3))["costs"] == [
        "90% out 12 s later on average", "18% more time in smoke", "1.3 more trapped per fire"]  # no gain: no note
    assert verdict(numbers(-6.7, 18.2, 0.0))["costs"] == ["18% more time in smoke"]  # trapped is no gain: no note
    # A change counts from VERDICT's size: 1 s, 0.05 people per fire, 5 points of smoke.
    assert verdict(numbers(-1.0, 0.0, 0.0))["helps"] and not verdict(numbers(-0.99, 0.0, 0.0))["helps"]
    assert verdict(numbers(0.0, 0.0, -0.05))["helps"] and not verdict(numbers(0.0, 0.0, -0.04))["helps"]
    assert verdict(numbers(0.0, -5.0, 0.0))["helps"] and not verdict(numbers(0.0, -4.9, 0.0))["helps"]
    assert verdict(numbers(1.0, 0.0, 0.0))["costs"] == ["90% out 1 s later on average"]
    assert verdict(numbers(0.99, 0.0, 0.0))["costs"] == [] and verdict(numbers(0.0, 4.9, 0.0))["costs"] == []
    assert verdict(numbers(0.0, 5.0, 0.0))["costs"] == ["5% more time in smoke"]
    assert verdict(numbers(0.0, 0.0, 0.05))["costs"] == ["0.1 more trapped per fire"]
    assert verdict(numbers(0.0, 0.0, 0.04))["costs"] == []
    # Without a percent the sign of the person-seconds decides (the null percent of a saved batch).
    raw = {"n": 3, "dT90": 0.0, "dTrapped": 0.0, "smokePct": None}
    assert verdict({**raw, "dSmokeSeconds": 427.0}) == {"helps": False, "tradeoff": False,
                                                         "costs": ["427 more person-seconds in smoke"]}
    assert verdict({**raw, "dSmokeSeconds": -20.0}) == {"helps": True, "tradeoff": False, "costs": []}
    assert verdict({**raw, "dSmokeSeconds": 427.0, "dTrapped": -1.0}) == {
        "helps": False, "tradeoff": True, "costs": ["427 more person-seconds in smoke" + counting]}
    assert verdict({**raw, "dSmokeSeconds": 0.0})["helps"] is False and verdict(raw)["helps"] is False

    # room_deltas: where a trapped change comes from, on hand-made lobby fires (16, 13 and 18 trapped, then 0).
    def run(room, seed, trapped, ok=True, floor="F1", **more):
        return {"ignition": {"floor": floor, "room": room}, "seed": seed, "trapped": trapped, "ok": ok, **more}

    before = [run("L1", 1, 16), run("L1", 2, 13), run("L1", 3, 18), run("R105", 1, 0)]
    after = [run("L1", 1, 0), run("L1", 2, 0), run("L1", 3, 0), run("R105", 1, 0)]
    lobby = {"floor": "F1", "room": "L1", "label": "Lobby (L1)", "delta": -47, "fires": 3, "opensOnto": "exit"}
    assert room_deltas(before, after, "trapped", example, ("E1",)) == [lobby]
    assert room_deltas(before, after, building=example, doors={"E1": "blocked"}) == [lobby]  # overrides, as a mapping
    assert room_deltas(before, after, "trapped", example, "E1") == [lobby]  # or one door id
    assert room_deltas(before, after, "trapped", example, ("DL1",))[0]["opensOnto"] == "door"
    assert room_deltas(before, after, "trapped", example, ("E2", "D105"))[0]["opensOnto"] is None
    assert room_deltas(before, after) == [{**lobby, "label": "L1", "opensOnto": None}]
    assert room_deltas(before, after, "trapped", {"floors": []}, ("E1",)) == [{**lobby, "label": "L1", "opensOnto": None}]
    # Failed runs and unmatched fires drop out, as in compare; the largest change comes first.
    partial = [run("L1", 1, 0), run("L1", 2, 0, ok=False), run("L1", 4, 0), run("R105", 1, 3)]
    assert room_deltas(before, partial, "trapped", example, ("E1",)) == [
        {**lobby, "delta": -16, "fires": 1},
        {"floor": "F1", "room": "R105", "label": "Office 105 (R105)", "delta": 3, "fires": 1, "opensOnto": None}]
    assert room_deltas([run("L1", 1, 16, ok=False)], [run("L1", 1, 0)]) == []
    tied = room_deltas([run("R101", 1, 0), run("L1", 1, 1), run("R201", 1, 0, floor="F2")],
                       [run("R101", 1, 1), run("L1", 1, 0), run("R201", 1, 1, floor="F2")])
    assert [(row["floor"], row["room"], row["delta"]) for row in tied] == [("F1", "L1", -1), ("F1", "R101", 1), ("F2", "R201", 1)]
    smoke = room_deltas([run("L1", 1, 0, smokeSeconds=100.5)], [run("L1", 1, 0, smokeSeconds=90.25)], "smokeSeconds")
    assert [(row["room"], row["delta"]) for row in smoke] == [("L1", -10.25)]
    named = deepcopy(example)
    next(r for r in named["floors"][0]["rooms"] if r["id"] == "L1")["name"] = "L1"
    assert room_deltas(before, after, "trapped", named, ("E1",))[0]["label"] == "L1"  # a name that is the id: once

    # trapped_note: the fires behind a number, only when one room holds half of it or more (and no more than all).
    def note(total, delta, onto="exit", n=36):
        return trapped_note({"n": n, "dTrapped": total / n, "dTrappedRooms": [dict(lobby, delta=delta, opensOnto=onto)]})

    assert note(-47, -47) == "(47 of 47 in fires in Lobby (L1), which this exit opens onto)"
    assert note(47, 47, "door") == "(47 of 47 in fires in Lobby (L1), which this door opens onto)"
    assert note(47, 47, None) == "(47 of 47 in fires in Lobby (L1))"
    assert note(-40, -20) == "(20 of 40 in fires in Lobby (L1), which this exit opens onto)"
    assert note(-1, -1) == "(1 of 1 in fires in Lobby (L1), which this exit opens onto)"
    assert note(-47, -20) == "" and note(-47, 47) == "" and note(-10, -14) == "" and note(0, -3) == ""
    assert trapped_note({"n": 36, "dTrapped": -47 / 36}) == ""
    assert trapped_note({"n": 36, "dTrapped": -47 / 36, "dTrappedRooms": []}) == ""

    # The wording. A what-if names the fires after its trapped number; without dTrappedRooms nothing changes.
    blocked = {"id": "blockedExit", "label": "Exit Main entrance blocked", "doors": {"E1": "blocked"},
               "sprinklers": False, "n": 36, "dT90": 58.29, "dT90Min": -209.6, "dT90Max": 267.08, "slower": 34,
               "faster": 2, "dTrapped": -47 / 36, "dDosed": 9.222, "dSmokeSeconds": 3021.917,
               "baseSmokeSeconds": 1439.306, "smokePct": 209.957, "dTrappedRooms": [dict(lobby)]}
    plain = {k: v for k, v in blocked.items() if k != "dTrappedRooms"}
    old_why = ("Exit Main entrance blocked: 90% out 58 s later on average (slower in 34 of 36 fires); +3,022 "
               "person-seconds in smoke (+210%), +9.2 people at an illustrative smoke dose of 1, -1.3 trapped per fire.")
    assert whatif_why(blocked["label"], plain) == old_why
    assert whatif_why(blocked["label"], blocked) == (
        old_why[:-1] + " (47 of 47 in fires in Lobby (L1), which this exit opens onto).")
    inverse = _inverse(blocked)
    assert inverse["dTrappedRooms"] == [dict(lobby, delta=47)] and blocked["dTrappedRooms"] == [lobby]
    assert inverse["dTrapped"] == 47 / 36 and inverse["dT90"] == -58.29 and "dTrappedRooms" not in _inverse(plain)
    keep = {"id": "keepClear-E1", "kind": "keepClear", "door": "E1", "floor": "F1", "derivedFrom": "whatIf.blockedExit",
            "label": "Keep Exit Main entrance clear (vs blocked)", **inverse, "smokePct": -67.737}
    trade_off = ("Trade-off: Keep Exit Main entrance clear (vs blocked): 90% out 58 s sooner on average and 68% less "
                 "time in smoke across 36 fires (faster in 34), but 1.3 more trapped per fire "
                 "(47 of 47 in fires in Lobby (L1), which this exit opens onto).")
    assert _why(keep) == trade_off and verdict(keep)["costs"] == [
        "1.3 more trapped per fire (47 of 47 in fires in Lobby (L1), which this exit opens onto)"]
    assert _why({k: v for k, v in keep.items() if k != "dTrappedRooms"}) == (
        trade_off.replace(" (47 of 47 in fires in Lobby (L1), which this exit opens onto)", ""))
    widen = {"id": "widen-E2", "kind": "widen", "label": "Widen Exit East stair exit from 1.00 m to 1.50 m", "n": 36,
             "dT90": -10.552, "faster": 23, "dTrapped": -7 / 36, "dSmokeSeconds": -41.681, "smokePct": -2.896}
    d14 = ("Widen Exit East stair exit from 1.00 m to 1.50 m: 90% out 11 s sooner on average and 3% less time in "
           "smoke across 36 fires (faster in 23); -0.2 trapped per fire.")
    assert _why(widen) == d14  # a helping fix keeps D14's sentence, and gets the fires behind its trapped number
    assert _why({**widen, "dTrappedRooms": [dict(lobby, delta=-7)]}) == (
        d14[:-1] + " (7 of 7 in fires in Lobby (L1), which this exit opens onto).")
    loser = {**widen, "dT90": 18.0, "dTrapped": 0.5, "dSmokeSeconds": -20.0, "smokePct": -3.0}
    assert _why(loser) == ("Widen Exit East stair exit from 1.00 m to 1.50 m: 90% out 18 s later on average and 3% "
                           "less time in smoke across 36 fires (faster in 23); +0.5 trapped per fire.")
    assert _why({**widen, "n": 0}) == "Widen Exit East stair exit from 1.00 m to 1.50 m: no successful matched fires (0 pairs)."
    assert _join(["a"]) == "a" and _join(["a", "b"]) == "a and b" and _join(["a", "b", "c"]) == "a, b and c"

    # restate: the example demo's five fixes as saved (before D22), then three of the office's.
    def saved(rows, n):
        fixes = []
        for ident, label, dT90, dTrapped, dSmoke, pct, derived, faster in rows:
            fix = {"id": ident, "label": label, "n": n, "dT90": dT90, "dTrapped": dTrapped, "dSmokeSeconds": dSmoke,
                   "smokePct": pct, "faster": faster, "helps": True, "why": "saved"}
            fixes.append({**fix, "derivedFrom": derived} if derived else fix)
        return {"version": "batch/v0", "id": "hand-made", "buildingId": example["id"], "fixes": fixes}

    demo = saved([
        ("keepClear-E1", "Keep Exit Main entrance clear (vs blocked)", -58.29, 47 / 36, -3021.917, -67.737, "whatIf.blockedExit", 34),
        ("widen-E2", "Widen Exit East stair exit from 1.00 m to 1.50 m", -10.552, -7 / 36, -41.681, -2.896, None, 23),
        ("sprinklers", "Sprinklers", -9.617, -47 / 36, -86.25, -5.992, None, 17),
        ("widen-DL1", "Widen Door DL1 (Lobby to Corridor 1) from 4.00 m to 4.50 m", -2.119, -5 / 36, -9.694, -0.674, None, 13),
        ("selfClosers", "Self-closers on stair doors (vs propped open)", 0.07, -1 / 36, -446.972, -23.696, "whatIf.proppedStairs", 4)], 36)
    demo["whatIf"] = [plain]
    snapshot = deepcopy(demo)
    restated = restate(demo)
    assert demo == snapshot and restated is not demo and restate(restated) == restated
    assert [f["id"] for f in restated["fixes"]] == ["widen-E2", "sprinklers", "widen-DL1", "selfClosers", "keepClear-E1"]
    assert all(f["helps"] and not f["tradeoff"] and f["costs"] == [] for f in restated["fixes"][:4])
    last = restated["fixes"][4]
    assert last["helps"] is False and last["tradeoff"] is True and last["costs"] == ["1.3 more trapped per fire"]
    assert last["why"].startswith("Trade-off: Keep Exit Main entrance clear (vs blocked):")
    assert "but 1.3 more trapped per fire" in last["why"] and "in fires in" not in last["why"]  # nothing saved to name
    assert restated["fixes"][0]["why"] == d14 and restated["whatIf"][0]["why"] == old_why
    assert restate(dict(demo, whatIf=[blocked]))["whatIf"][0]["why"].endswith(
        "(47 of 47 in fires in Lobby (L1), which this exit opens onto).")
    office = restate(saved([
        ("keepClear-D$77wwb", "Keep Exit Stair S1 (west) clear (vs blocked)", -11.487, 10 / 24, -631.333, -42.756, "whatIf.blockedExit", 21),
        ("sprinklers", "Sprinklers", -6.718, -2.25, 153.771, 18.192, None, 2),
        ("selfClosers", "Self-closers on stair doors (vs propped open)", 0.489, 10 / 24, -486.958, -36.553, "whatIf.proppedStairs", 2)], 24))
    assert [f["id"] for f in office["fixes"]] == ["keepClear-D$77wwb", "sprinklers", "selfClosers"]
    assert all(f["tradeoff"] and not f["helps"] for f in office["fixes"])
    assert [f["why"] for f in office["fixes"]] == [
        "Trade-off: Keep Exit Stair S1 (west) clear (vs blocked): 90% out 11 s sooner on average and 43% less time in "
        "smoke across 24 fires (faster in 21), but 0.4 more trapped per fire.",
        "Trade-off: Sprinklers: 90% out 7 s sooner on average and 2.2 fewer trapped per fire across 24 fires "
        "(faster in 2), but 18% more time in smoke" + counting + ".",
        "Trade-off: Self-closers on stair doors (vs propped open): 37% less time in smoke across 24 fires "
        "(faster in 2), but 0.4 more trapped per fire."]
    assert office["fixes"][1]["costs"] == ["18% more time in smoke" + counting]
    for each in (restated, office):
        assert all(f["why"].isascii() and all(c.isascii() for c in f["costs"]) for f in each["fixes"])
        json.dumps(each, allow_nan=False)
    # The headline pack keeps both fields.
    pack = build_headlines(example, restated, generated="2026-11-14T15:00:00Z")
    by_id = {f["id"]: f for f in pack["fixes"]}
    assert by_id["keepClear-E1"]["tradeoff"] is True and by_id["keepClear-E1"]["helps"] is False
    assert by_id["keepClear-E1"]["costs"] == ["1.3 more trapped per fire"] and by_id["widen-E2"]["costs"] == []

    # The sweeps write dTrappedRooms: what-if, then the fix derived from it, a rerun fix and a reused sprinkler what-if.
    def stub(room, seed, trapped, t90=100.0, smoke=1000.0):
        return {"ignition": {"floor": "F1", "room": room}, "seed": seed, "t90": t90, "trapped": trapped,
                "dosed": 1, "smokeSeconds": smoke, "exitCounts": {"E1": 80, "E2": 80}}

    baseline = [stub("L1", 1, 16), stub("L1", 2, 13), stub("L1", 3, 18), stub("R105", 1, 0)]
    batch = {"runs": baseline, "top": [], "rooms": [dict(id="L1", floor="F1", riskT90=100.0),
                                                        dict(id="R105", floor="F1", riskT90=100.0)]}
    closed = [stub("L1", s, 0, 150.0, 1500.0) for s in (1, 2, 3)] + [stub("R105", 1, 0)]
    variant = {"id": "blockedExit", "label": "Exit Main entrance blocked", "doors": {"E1": "blocked"}, "sprinklers": False}
    original = deepcopy(batch)
    with patch("fire.whatif.run_many", return_value={"runs": closed}):
        swept = add_whatif(example, base, batch, variants=[variant], workers=1, progress=False)
    entry = swept["whatIf"][0]
    assert entry["dTrappedRooms"] == [lobby]  # R105 (0 to 0) has no row
    assert entry["why"].endswith("-11.8 trapped per fire (47 of 47 in fires in Lobby (L1), which this exit opens onto).")
    trash = deepcopy(base)
    trash["fire"]["type"] = "trash"  # sprinklers cannot matter; its stair doors are closed: only the keep-clear fix remains
    with patch("fire.fixes.run_many", side_effect=AssertionError("derived fix reran")):
        derived = add_fixes(example, trash, swept)
    assert [f["id"] for f in derived["fixes"]] == ["keepClear-E1"]
    fix = derived["fixes"][0]
    assert fix["tradeoff"] is True and fix["helps"] is False and fix["dTrappedRooms"] == [dict(lobby, delta=47)]
    assert fix["why"].startswith("Trade-off: Keep Exit Main entrance clear (vs blocked): 90% out ")
    assert fix["why"].endswith(", but 11.8 more trapped per fire (47 of 47 in fires in Lobby (L1), which this exit opens onto).")
    assert fix["costs"] == ["11.8 more trapped per fire (47 of 47 in fires in Lobby (L1), which this exit opens onto)"]
    widened = {**batch, "top": [{"kind": "exit", "id": "E1", "floor": "F1"}]}

    def rerun(b, scenario, ignitions, seeds, workers, timeout, progress):
        return {"runs": [{**r, "trapped": 0 if r["ignition"]["room"] == "L1" else r["trapped"]} for r in baseline]}

    with patch("fire.fixes.run_many", side_effect=rerun):
        rerun_fixes = add_fixes(example, trash, widened, workers=1, progress=False)
    fix = next(f for f in rerun_fixes["fixes"] if f["id"] == "widen-E1")
    assert fix["dTrappedRooms"] == [lobby] and fix["helps"] is True and fix["tradeoff"] is False and fix["costs"] == []
    assert fix["why"].endswith("-11.8 trapped per fire (47 of 47 in fires in Lobby (L1), which this exit opens onto).")
    sprinkled = {**batch, "whatIf": [dict(
        id="sprinklers", label="Sprinklers on", doors={}, sprinklers=True, n=4, dT90=-3.0, dT90Min=-4.0, dT90Max=-2.0,
        slower=0, faster=3, dTrapped=-47 / 4, dDosed=0.0, dSmokeSeconds=-50.0, baseSmokeSeconds=200.0,
        smokePct=-25.0, dTrappedRooms=[dict(lobby, opensOnto=None)])]}
    with patch("fire.fixes.run_many", side_effect=AssertionError("the sprinkler what-if was not reused")):
        reused = add_fixes(example, base, sprinkled)
    assert [f["id"] for f in reused["fixes"]] == ["sprinklers"]
    assert reused["fixes"][0]["dTrappedRooms"] == [dict(lobby, opensOnto=None)]
    assert reused["fixes"][0]["why"].endswith("-11.8 trapped per fire (47 of 47 in fires in Lobby (L1)).")
    assert batch == original
    for each in (swept, derived, rerun_fixes, reused):
        json.dumps(each, allow_nan=False)
        assert all(f.get("why", "").isascii() for f in each.get("fixes", []) + each.get("whatIf", []))
    print("tradeoffs: verdicts, room deltas, wording, restate and the sweeps' dTrappedRooms checked", flush=True)


def check_tradeoffs_slow():
    from fire.batch import run_many
    from fire.whatif import add_whatif

    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text(encoding="utf-8"))
    base = json.loads((root / "contracts/scenario.example.json").read_text(encoding="utf-8"))
    base["maxTime"] = 400
    base["occupants"] = {"total": 160, "mix": base["occupants"]["mix"]}
    # D25: this check tests the trade-off wording, so concrete keeps the spread (the corridor at 300 s) out of its two fires.
    # With drywall (the corridor at 180 s) the lobby fire traps 17 and the R105 fire traps one more person once E1 is
    # blocked, so the net 16 is less than the lobby's 17 and no "(N of N in fires in ...)" note is written.
    base["fire"]["material"] = "concrete"
    # sim/ROUTING.md: a lobby or corridor fire now gets building-wide routing by default, which walks the lobby's people round the
    # fire and traps nobody, so blocking E1 changes no trapped count and there is no dTrappedRooms row to name. The check keeps the
    # legacy keep-out (buildingRouting false), which still traps the lobby's people at E1 (seed 1: two trapped, none once E1 is blocked).
    base["buildingRouting"] = False
    ignitions = [{"floor": "F1", "room": room} for room in ("L1", "R105")]
    batch = run_many(building, base, ignitions, seeds=(1,), workers=2, timeout_s=600)
    assert len(batch["runs"]) == 2 and not batch["failed"], batch["failed"]
    blocked = {"id": "blockedExit", "label": "Exit Main entrance blocked", "doors": {"E1": "blocked"}, "sprinklers": False}
    result = add_whatif(building, base, batch, variants=[blocked], workers=2, timeout_s=600, progress=False)
    entry = result["whatIf"][0]
    assert entry.get("dTrappedRooms"), f"blocking E1 changed no trapped count (baseline trapped {[(r['ignition']['room'], r['trapped']) for r in batch['runs']]})"
    first = entry["dTrappedRooms"][0]
    assert (first["floor"], first["room"], first["opensOnto"]) == ("F1", "L1", "exit") and first["delta"] < 0, first
    assert "in fires in Lobby (L1), which this exit opens onto" in entry["why"], entry["why"]
    print(f"tradeoffs: the lobby fire accounts for {-first['delta']} of the people the blocked main entrance spares", flush=True)


def check_headlines():
    from contextlib import redirect_stderr, redirect_stdout
    from copy import deepcopy
    from io import StringIO
    from fire.headlines import _shown, all_whys, build_headlines, main

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from strings(item)

    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text(encoding="utf-8"))
    base = json.loads((root / "contracts/scenario.example.json").read_text(encoding="utf-8"))
    runs = [{"scenarioId": f"hand-{room}-s{seed}", "seed": seed, "ignition": {"floor": "F1", "room": room},
             "t90": 100.0, "t100": 140.0, "trapped": 0, "dosed": 1, "smokeSeconds": smoke,
             "exitCounts": {"E1": 80, "E2": 80}}
            for room, seed, smoke in (("R101", 1, 1000.0), ("R101", 2, 1100.0), ("R105", 1, 1200.0))]
    batch = {
        "version": "batch/v0", "id": "batch-example-office-hand", "buildingId": building["id"], "base": base,
        "note": "Simulated rule-based batch; fire and smoke model is illustrative.",
        "timing": {"runs": 3, "failed": 0, "workers": 1, "wallS": 3.0, "meanRunS": 1.0},
        "runs": runs, "failed": [],
        "rooms": [{"id": "R101", "floor": "F1", "riskT90": 100.0, "riskTrapped": 0.0, "n": 2,
                   "riskT90Range": {"min": 95.0, "median": 100.0, "max": 105.0}},
                  {"id": "R105", "floor": "F1", "riskT90": None, "riskTrapped": 0.0, "n": 1,
                   "riskT90Range": None}],
        "doors": [{"id": "DSB1", "floor": "F1", "meanWait": 40.0, "peakQueue": 10, "score": 90.0,
                   "scoreRange": {"min": 70.0, "median": 90.0, "max": 95.0}},
                  {"id": "E1", "floor": "F1", "meanWait": 30.0, "peakQueue": 4, "score": 60.0}],
        "heatmaps": [],
        "top": [{"kind": "stair", "id": "DSB1", "floor": "F1", "score": 90.0, "seedsInTop3": 2, "seeds": 2,
                 "why": "Stair SB door: 10 people queued at peak; 40 person-seconds of waiting on average across 3 fires."},
                {"kind": "exit", "id": "E1", "floor": "F1", "score": 60.0, "seedsInTop3": 1, "seeds": 2,
                 "why": "Exit Main entrance: 4 people queued at peak; 30 person-seconds of waiting on average across 3 fires."},
                {"kind": "room", "id": "R101", "floor": "F1", "score": 50.0, "seedsInTop3": 2, "seeds": 2,
                 "why": "Fire in Kitchen (R101): 0.0 people trapped on average; 90% out after 100 s (2 fires)."}],
        "stability": {"seeds": [1, 2], "top3": ["DSB1", "E1"], "heldIn": 1, "n": 2, "stable": False,
                      "why": "The top 3 weak spots hold in 1 of 2 seeds: Stair SB door, Exit Main entrance. "
                             "Stair SB door ranks first in 2 of 2."},
        "whatIf": [{"id": "proppedStairs", "label": "Stair doors propped open", "doors": {"DSA1": "propped"},
                    "sprinklers": False, "n": 12, "dT90": 0.2, "dT90Min": -1.0, "dT90Max": 2.0, "slower": 3,
                    "faster": 1, "dTrapped": 0.0, "dDosed": 0.5, "dSmokeSeconds": 242.0,
                    "baseSmokeSeconds": 1100.0, "smokePct": 22.0,
                    "why": "Stair doors propped open: 90% out 0 s later on average (slower in 3 of 12 fires); "
                           "+242 person-seconds in smoke (+22%), +0.5 people at an illustrative smoke dose of 1, "
                           "+0.0 trapped per fire."}],
        "fixes": [{"id": "selfClosers", "kind": "selfClosers",
                   "label": "Self-closers on stair doors (vs propped open)", "derivedFrom": "whatIf.proppedStairs",
                   "n": 12, "dT90": -0.2, "dT90Min": -2.0, "dT90Max": 1.0, "slower": 1, "faster": 3,
                   "dTrapped": -0.0, "dDosed": -0.5, "dSmokeSeconds": -242.0, "smokePct": -18.03, "helps": True,
                   "why": "Self-closers on stair doors (vs propped open): 90% out 0 s sooner on average and "
                          "18% less time in smoke across 12 fires (faster in 3); -0.0 trapped per fire."}]}
    original = deepcopy(batch)
    headline = ("Stair doors propped open: +22% person-seconds in smoke across 12 paired fires; "
                "90% out 0 s later on average.")
    pack = build_headlines(building, batch, generated="2026-11-14T09:00:00Z")
    assert batch == original
    assert list(pack)[:5] == ["version", "buildingId", "buildingName", "generated", "note"]
    assert (pack["version"], pack["buildingId"], pack["buildingName"], pack["generated"]) == (
        "headlines/v0", building["id"], building["name"], "2026-11-14T09:00:00Z")
    assert pack["headline"] == headline and "not a compliance result" in pack["note"]
    assert pack["scenario"] == {
        "id": base["id"], "occupants": base["occupants"]["total"], "mix": base["occupants"]["mix"],
        "fireType": base["fire"]["type"], "sprinklers": base["sprinklers"], "alarmTime": base["alarmTime"],
        "maxTime": base["maxTime"], "doors": base["doors"], "seeds": [1, 2], "rooms": 2, "runs": 3, "failed": 0}
    grown = deepcopy(batch)
    grown["base"]["fire"]["growth"], grown["base"]["exitChoice"] = "fast", "hand-made"
    assert build_headlines(building, grown)["scenario"]["growth"] == "fast"
    assert build_headlines(building, grown)["scenario"]["exitChoice"] == "hand-made"
    spots = pack["weakSpots"]
    assert [(s["rank"], s["kind"], s["id"], s["label"]) for s in spots] == [
        (1, "stair", "DSB1", "Stair SB door"), (2, "exit", "E1", "Exit Main entrance"),
        (3, "room", "R101", "Kitchen (R101)")]
    assert [s["seedsInTop3"] for s in spots] == [2, 1, 2] and [s["why"] for s in spots] == [
        t["why"] for t in batch["top"]]
    assert spots[0]["scoreRange"] == {"min": 70.0, "median": 90.0, "max": 95.0}
    assert spots[2]["riskT90Range"]["median"] == 100.0
    assert all("scoreRange" not in s for s in spots[1:]) and all("riskT90Range" not in s for s in spots[:2])
    assert pack["whatIf"] == [{k: v for k, v in batch["whatIf"][0].items()
                               if k not in ("doors", "sprinklers", "dT90Min", "dT90Max")}]
    assert pack["fixes"][0]["derivedFrom"] == "whatIf.proppedStairs" and pack["fixes"][0]["helps"] is True
    assert pack["fixes"][0]["smokePct"] == -18.03 and "dDosed" not in pack["fixes"][0]
    assert pack["stability"] == {"why": batch["stability"]["why"], "heldIn": 1, "n": 2}
    assert pack["timing"] == batch["timing"] and not {"runs", "doors", "rooms", "heatmaps"} & set(pack)
    assert all_whys(pack) == [t["why"] for t in batch["top"]] + [
        batch["stability"]["why"], batch["whatIf"][0]["why"], batch["fixes"][0]["why"]]
    # Saved before the percent existed: the per-fire wording, unless every run is paired (E's rule).
    old = deepcopy(batch)
    for key in ("baseSmokeSeconds", "smokePct"):
        del old["whatIf"][0][key]
    assert build_headlines(building, old)["headline"] == (
        "Stair doors propped open: +242 person-seconds in smoke per fire across 12 paired fires; "
        "90% out 0 s later on average.")
    assert "smokePct" not in build_headlines(building, old)["whatIf"][0]
    old["whatIf"][0]["n"] = 3  # three runs, mean smokeSeconds 1100
    assert build_headlines(building, old)["headline"] == (
        "Stair doors propped open: +22% person-seconds in smoke across 3 paired fires; "
        "90% out 0 s later on average.")
    assert build_headlines(building, old)["whatIf"][0]["smokePct"] == 22.0
    sooner = deepcopy(batch)
    sooner["whatIf"][0].update(n=1, dT90=-6.4, dSmokeSeconds=-33.0, smokePct=-3.0)
    assert build_headlines(building, sooner)["headline"] == (
        "Stair doors propped open: -3% person-seconds in smoke across 1 paired fire; 90% out 6 s sooner on average.")
    # Propped stairs come first while they have fires; else the first what-if that has some.
    both = deepcopy(batch)
    both["whatIf"].insert(0, {"id": "blockedExit", "label": "Exit Main entrance blocked", "n": 4, "dT90": 12.4,
                              "dSmokeSeconds": 100.0, "baseSmokeSeconds": 500.0, "smokePct": 20.0, "why": "x"})
    assert build_headlines(building, both)["headline"] == headline
    both["whatIf"][1]["n"] = 0
    assert build_headlines(building, both)["headline"] == (
        "Exit Main entrance blocked: +20% person-seconds in smoke across 4 paired fires; "
        "90% out 12 s later on average.")
    both["whatIf"][0].pop("dSmokeSeconds"), both["whatIf"][0].pop("smokePct")
    assert build_headlines(building, both)["headline"] == (
        "Exit Main entrance blocked: 90% out 12 s later on average across 4 paired fires.")
    bare = deepcopy(batch)
    del bare["whatIf"]
    assert build_headlines(building, bare)["headline"] == batch["top"][0]["why"]
    assert "whatIf" not in build_headlines(building, bare)
    minimal = build_headlines(building, {"buildingId": building["id"]}, generated="2026-11-14T09:00:00Z")
    assert set(minimal) == {"version", "buildingId", "buildingName", "generated", "note", "scenario"}, minimal
    # D17's file, when there is one: note, why and each variant's id and why only.
    sensitivity = {"note": "Smoke model variants.", "why": "The ranking holds in both variants.",
                   "variants": [{"id": "slow", "why": "Slower smoke: same top 3.", "dT90": 1.0},
                                {"id": "fast", "why": "Faster smoke: same top 3."}]}
    with_sensitivity = build_headlines(building, batch, sensitivity, {"batch": {"file": "x.json"}})
    assert with_sensitivity["sensitivity"] == {
        "note": "Smoke model variants.", "why": "The ranking holds in both variants.",
        "variants": [{"id": "slow", "why": "Slower smoke: same top 3."}, {"id": "fast", "why": "Faster smoke: same top 3."}]}
    assert with_sensitivity["sources"] == {"batch": {"file": "x.json"}} and "sources" not in pack
    assert all_whys(with_sensitivity)[-3:] == [sensitivity["why"], "Slower smoke: same top 3.", "Faster smoke: same top 3."]
    # Plain ASCII and JSON, and small.
    accented = deepcopy(building)
    accented["name"] = "Example – office"
    next(r for r in accented["floors"][0]["rooms"] if r["id"] == "R101")["name"] = "Küche"
    plain = build_headlines(accented, batch, sensitivity)
    assert plain["weakSpots"][2]["label"] == "K?che (R101)" and plain["buildingName"] == "Example ? office"
    for each in (pack, with_sensitivity, plain, minimal):
        assert all(s.isascii() for s in strings(each))
    assert len(json.dumps(with_sensitivity, indent=1, allow_nan=False)) < 20_000
    # The CLI, in a scratch directory, because the default paths are relative to the working directory.
    with tempfile.TemporaryDirectory() as tmp:
        here = os.getcwd()
        os.chdir(tmp)
        try:
            Path("data/runs").mkdir(parents=True)
            Path("building.json").write_text(json.dumps(building), encoding="utf-8")
            Path("other.json").write_text(json.dumps({**building, "id": "other-building"}), encoding="utf-8")
            Path("batch.json").write_text(json.dumps(batch), encoding="utf-8")
            Path("data/runs/sensitivity-example-office.json").write_text(json.dumps(sensitivity), encoding="utf-8")
            assert _shown(Path("data/runs/x.json")) == "data/runs/x.json"
            assert _shown(Path.cwd() / "data" / "x.json") == "data/x.json"
            assert _shown(Path(here) / "x.json") == "x.json"
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                assert main(["building.json", "batch.json"]) == 0
            data = Path("data/runs/headlines-example-office.json").read_bytes()
            written = json.loads(data)
            assert data.decode("ascii") == json.dumps(written, indent=1) and b"\r" not in data
            assert stderr.getvalue() == "" and written["headline"] == headline
            assert written["sensitivity"] == with_sensitivity["sensitivity"]
            assert written["sources"]["batch"]["file"] == "batch.json"
            assert written["sources"]["batch"]["id"] == batch["id"]
            assert written["sources"]["sensitivity"]["file"] == "data/runs/sensitivity-example-office.json"
            assert all(s["modified"].endswith("Z") and s["modified"].isascii() for s in written["sources"].values())
            assert stdout.getvalue().splitlines() == [
                headline, *all_whys(written), f"wrote data/runs/headlines-example-office.json ({len(data)} bytes)"]
            Path("data/runs/sensitivity-example-office.json").unlink()
            with redirect_stdout(StringIO()), redirect_stderr(stderr):
                assert main(["building.json", "batch.json", "--out", "second/pack.json"]) == 0
            second = json.loads(Path("second/pack.json").read_text(encoding="utf-8"))
            assert "sensitivity" not in second and list(second["sources"]) == ["batch"]
            stdout, stderr = StringIO(), StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                assert main(["building.json", "nope.json"]) == 1
                assert main(["other.json", "batch.json"]) == 2
                assert main(["building.json", "batch.json", "--sensitivity", "nope.json"]) == 1
            lines = stderr.getvalue().splitlines()
            assert lines[0] == "no batch at nope.json: run D15's command (fire/README.md) first", lines
            assert "'example-office'" in lines[1] and "'other-building'" in lines[1], lines
            assert lines[2] == "no sensitivity file at nope.json" and stdout.getvalue() == ""
        finally:
            os.chdir(here)
    print("headlines: pack, headline wording and fallbacks, labels, ASCII and the CLI checked", flush=True)


def check_refresh():
    from contextlib import redirect_stderr, redirect_stdout
    from copy import deepcopy
    from io import StringIO
    from unittest.mock import patch
    from fire.batch import apply_overrides
    from fire.headlines import build_headlines
    from fire.refresh import (DT90_S, SMOKE_PCT_POINTS, TRAPPED, diff_headlines, exit_shift, main, refresh,
                              sim_features, stair_probe, terms_off)

    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text(encoding="utf-8"))
    base = json.loads((root / "contracts/scenario.example.json").read_text(encoding="utf-8"))
    original = deepcopy(base)
    assert (SMOKE_PCT_POINTS, DT90_S, TRAPPED) == (5.0, 5.0, 0.5)
    assert isinstance(sim_features()["smokeAwareExits"], bool)

    # apply_overrides: a copy; the mix stays, growth goes, bad values raise ValueError.
    changed = apply_overrides({**base, "fire": {**base["fire"], "growth": "slow"}}, occupants=90, fire_type="trash")
    assert changed["occupants"] == {"total": 90, "mix": base["occupants"]["mix"]}
    assert changed["fire"]["type"] == "trash" and "growth" not in changed["fire"]
    assert apply_overrides(base) == base and apply_overrides(base) is not base and base == original
    for kwargs in ({"occupants": 0}, {"fire_type": "unknown"}):
        try:
            apply_overrides(base, **kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"bad override accepted: {kwargs}")

    # terms_off: C14's weights at 0 and a new id; nothing else moves, and the input stays as it was.
    off = terms_off(base)
    assert off["exitChoice"] == {"smoke": 0, "unfamiliar": 0} and off["id"] == f"{base['id']}-c14off"
    assert {k: v for k, v in off.items() if k not in ("exitChoice", "id")} == {k: v for k, v in base.items() if k != "id"}
    assert base == original and "exitChoice" not in base

    # refresh: both sides get the same ignitions, seeds and variants; the scenarios differ in exitChoice and id only.
    calls, stages = [], []

    def fake_run_many(b, scenario, ignitions, seeds, workers, timeout, progress):
        assert b is building and workers == 3 and timeout == 99 and progress is False
        calls.append(("run_many", scenario, ignitions, seeds))
        # The blocked exit comes from the current side's counts (E1); the legacy side's would pick E2.
        counts = {"E1": 20, "E2": 60} if "exitChoice" in scenario else {"E1": 60, "E2": 20}
        runs = [{"ignition": dict(i), "seed": s, "t90": 100.0, "trapped": 0, "exitCounts": counts}
                for i in ignitions for s in seeds]
        return {"id": f"batch-{b['id']}-{scenario['id']}", "base": deepcopy(scenario), "runs": runs, "failed": []}

    def fake_whatif(b, scenario, batch, variants=None, workers=None, timeout_s=None, progress=None):
        assert b is building and workers == 3 and timeout_s == 99 and progress is False
        calls.append(("add_whatif", scenario, variants))
        return {**batch, "whatIf": [{"id": v["id"], "n": len(batch["runs"])} for v in variants]}  # only these, as the real one

    def fake_fixes(b, scenario, batch, workers=None, timeout_s=None, progress=None):
        assert b is building and workers == 3 and timeout_s == 99 and progress is False
        assert [w["id"] for w in batch["whatIf"]] == ["proppedStairs", "blockedExit", "sprinklers"]
        calls.append(("add_fixes", scenario))
        return {**batch, "fixes": []}

    ignitions = [{"floor": "F1", "room": "R101"}, {"floor": "F1", "room": "R105"}]
    with (patch("fire.refresh.run_many", side_effect=fake_run_many), patch("fire.refresh.add_whatif", side_effect=fake_whatif),
          patch("fire.refresh.add_fixes", side_effect=fake_fixes), redirect_stdout(StringIO())):
        result = refresh(building, base, ignitions, (1, 2), workers=3, timeout_s=99, progress=False,
                         on_stage=lambda side, stage, batch: stages.append((side, stage)))
    assert base == original and set(result) == {"legacy", "current"}
    assert [c[0] for c in calls] == ["run_many"] * 2 + ["add_whatif"] * 6 + ["add_fixes"] * 2
    ids = ["proppedStairs", "blockedExit", "sprinklers"]  # each variant on both sides in turn, then the fixes
    assert stages == ([("legacy", "baseline"), ("current", "baseline")]
                      + [(side, f"what-if {i}") for i in ids for side in ("legacy", "current")]
                      + [("current", "fixes"), ("legacy", "fixes")])  # the fixes of the side the demo quotes first
    legacy, current = calls[0][1], calls[1][1]
    assert legacy["exitChoice"] == {"smoke": 0, "unfamiliar": 0} and "exitChoice" not in current
    assert legacy["id"] == f"{base['id']}-c14off" and current["id"] == base["id"]
    strip = lambda scenario: {k: v for k, v in scenario.items() if k not in ("exitChoice", "id")}
    assert strip(legacy) == strip(current) == strip(base)
    assert calls[0][2:] == calls[1][2:] == (ignitions, (1, 2))
    sweeps = calls[2:8]
    assert [c[1] for c in sweeps[0::2]] == [legacy] * 3 and [c[1] for c in sweeps[1::2]] == [current] * 3
    assert [c[2] for c in sweeps[0::2]] == [c[2] for c in sweeps[1::2]]  # the same variant list on both sides
    variants = [c[2][0] for c in sweeps[0::2]]
    assert [c[2] for c in sweeps[0::2]] == [[v] for v in variants] and [v["id"] for v in variants] == ids
    assert variants[1]["doors"] == {"E1": "blocked"}  # from the current baseline, not the legacy one
    assert calls[8][1] == current and calls[9][1] == legacy
    assert result["legacy"]["base"] == legacy and result["current"]["base"] == current
    assert [w["id"] for w in result["current"]["whatIf"]] == ids
    json.dumps(result, allow_nan=False)

    # A baseline or what-if stage that lost runs is run again (once); a resumed run skips the stages it holds in full.
    log = []
    legacy_id = f"{base['id']}-c14off"

    def flaky_run_many(b, scenario, ignitions, seeds, workers, timeout, progress):
        log.append(("baseline", scenario["id"]))
        runs = [{"ignition": dict(i), "seed": s, "t90": 100.0, "trapped": 0, "exitCounts": {"E1": 60, "E2": 20}}
                for i in ignitions for s in seeds]
        lost = log.count(("baseline", legacy_id)) == 1 and scenario["id"] == legacy_id  # the first legacy attempt
        failed = [{"scenarioId": "x", "error": "BrokenProcessPool('a worker died')"}] if lost else []
        return {"id": f"batch-{b['id']}-{scenario['id']}", "base": deepcopy(scenario),
                "runs": runs[:-1] if lost else runs, "failed": failed}

    def flaky_whatif(b, scenario, batch, variants=None, **kwargs):
        key = ("whatIf", scenario["id"], variants[0]["id"])
        log.append(key)
        short = log.count(key) == 1 and key[1:] == (base["id"], "blockedExit")  # the first current blockedExit attempt
        return {**batch, "whatIf": [{"id": variants[0]["id"], "n": len(batch["runs"]) - short}]}

    def flaky_fixes(b, scenario, batch, **kwargs):
        log.append(("fixes", scenario["id"]))
        return {**batch, "fixes": []}

    def run_flaky(**kwargs):
        with (patch("fire.refresh.run_many", side_effect=flaky_run_many), patch("fire.refresh.add_whatif", side_effect=flaky_whatif),
              patch("fire.refresh.add_fixes", side_effect=flaky_fixes), redirect_stdout(StringIO())):
            return refresh(building, base, ignitions, (1, 2), progress=False, **kwargs)

    again = run_flaky()
    assert log.count(("baseline", legacy_id)) == 2 and log.count(("baseline", base["id"])) == 1
    assert not again["legacy"]["failed"] and len(again["legacy"]["runs"]) == 4
    assert log.count(("whatIf", base["id"], "blockedExit")) == 2 and log.count(("whatIf", legacy_id, "blockedExit")) == 1
    assert [w["id"] for w in again["current"]["whatIf"]] == ids and all(w["n"] == 4 for w in again["current"]["whatIf"])
    log.clear()
    assert len(run_flaky(retries=0)["legacy"]["runs"]) == 3 and log.count(("baseline", legacy_id)) == 1  # no second try

    log.clear()
    held_legacy, held_current = deepcopy(again["legacy"]), deepcopy(again["current"])
    held_legacy.pop("fixes"), held_current.pop("fixes")  # a stopped run: the fixes never ran
    held_current["whatIf"][0]["n"] = 3  # and the current propped-stairs stage came out short
    resumed = run_flaky(resume={"legacy": held_legacy, "current": held_current})
    assert [entry for entry in log if entry[0] == "baseline"] == []
    assert [entry[1:] for entry in log if entry[0] == "whatIf"] == [(base["id"], "proppedStairs")]
    assert [entry for entry in log if entry[0] == "fixes"] == [("fixes", base["id"]), ("fixes", legacy_id)]
    assert [w["id"] for w in resumed["current"]["whatIf"]] == ids and all(w["n"] == 4 for w in resumed["current"]["whatIf"])
    assert held_current["whatIf"][0]["n"] == 3  # the checkpoint itself is not touched
    wrong = deepcopy(held_legacy)
    wrong["base"]["alarmTime"] += 1
    try:
        run_flaky(resume={"legacy": wrong})
    except ValueError as error:
        assert "legacy checkpoint" in str(error)
    else:
        raise AssertionError("a checkpoint of another scenario was accepted")
    log.clear()
    short = deepcopy(held_legacy)
    short["runs"] = short["runs"][:-1]  # a baseline that lacks a planned fire is run again, and its what-ifs are dropped
    run_flaky(resume={"legacy": short, "current": held_current})
    assert log.count(("baseline", legacy_id)) == 2 and ("whatIf", legacy_id, "proppedStairs") in log
    log.clear()
    stale = deepcopy(again["current"])  # it holds fixes, but its blockedExit stage came out short: they are stale
    stale["whatIf"][1]["n"] = 3
    run_flaky(resume={"legacy": deepcopy(again["legacy"]), "current": stale})
    assert ("fixes", base["id"]) in log and ("fixes", legacy_id) not in log

    # diff_headlines: thresholds and flags, on two hand-made packs (the old one is the C14-off side).
    def item(ident, label, **fields):
        return {"id": ident, "label": label, "n": 36, **fields}

    old = {"weakSpots": [{"id": i, "label": f"Spot {i}"} for i in "ABCD"],
           "whatIf": [item("proppedStairs", "Stair doors propped open", dT90=0.1, dTrapped=0.0, smokePct=22.0, dSmokeSeconds=150.0),
                      item("blockedExit", "Exit X blocked", dT90=13.0, dTrapped=-0.2, smokePct=50.0, dSmokeSeconds=154.0),
                      item("sprinklers", "Sprinklers on", dT90=0.0, dTrapped=-1.2, dSmokeSeconds=100.0),
                      item("lessSmoke", "Less smoke", dT90=0.0, dTrapped=0.0, dSmokeSeconds=100.0)],
           "fixes": [item("widen-A", "Widen A", dT90=-2.0, dTrapped=-0.1, smokePct=-6.0, helps=True),
                     item("only-old", "Only old", dT90=0.0, dTrapped=0.0, helps=False)]}
    new = {"weakSpots": [{"id": i, "label": f"Spot {i}"} for i in "ACBD"],
           "whatIf": [item("proppedStairs", "Stair doors propped open", dT90=4.9, dTrapped=0.4, smokePct=26.0, dSmokeSeconds=190.0),
                      item("blockedExit", "Exit X blocked", dT90=18.5, dTrapped=-0.2, smokePct=56.0, dSmokeSeconds=210.0),
                      item("sprinklers", "Sprinklers on", dT90=0.0, dTrapped=-1.2, dSmokeSeconds=120.0),
                      item("lessSmoke", "Less smoke", dT90=0.0, dTrapped=0.0, dSmokeSeconds=109.0)],
           "fixes": [item("widen-A", "Widen A", dT90=-2.0, dTrapped=-0.1, smokePct=-6.0, helps=False),
                     item("only-new", "Only new", dT90=0.0, dTrapped=0.0, helps=True)]}
    before = deepcopy((old, new))
    entries = diff_headlines(old, new)
    assert (old, new) == before
    keys = [e["key"] for e in entries]
    assert len(set(keys)) == len(keys) and all(set(e) == {"key", "label", "old", "new", "changed", "why"} for e in entries)
    assert {e["key"] for e in entries if e["changed"]} == {
        "top3", "whatIf.blockedExit.smokePct", "whatIf.blockedExit.dT90", "whatIf.sprinklers.dSmokeSeconds",
        "fixes.widen-A.helps", "fixes.only-old", "fixes.only-new"}
    assert {"whatIf.proppedStairs.smokePct", "whatIf.proppedStairs.dT90", "whatIf.proppedStairs.dTrapped",
            "whatIf.blockedExit.dTrapped", "whatIf.lessSmoke.dSmokeSeconds", "fixes.widen-A.smokePct"} <= set(keys)
    assert "whatIf.proppedStairs.dSmokeSeconds" not in keys  # smokePct stands in for it when both sides have it
    by_key = {e["key"]: e for e in entries}
    assert by_key["top3"]["old"] == ["A", "B", "C"] and by_key["top3"]["new"] == ["A", "C", "B"]
    assert by_key["whatIf.proppedStairs.smokePct"]["why"] == (
        "Stair doors propped open, smoke exposure: +22% -> +26% with C14's exit-choice terms on (same 36 fires).")
    assert by_key["whatIf.blockedExit.dT90"]["why"] == (
        "Exit X blocked, 90% out time: +13 s -> +18 s with C14's exit-choice terms on (same 36 fires).")
    assert by_key["whatIf.proppedStairs.dTrapped"]["why"].startswith("Stair doors propped open, trapped per fire: +0.0 -> +0.4 ")
    assert by_key["whatIf.sprinklers.dSmokeSeconds"]["why"].startswith("Sprinklers on, smoke exposure: +100 person-seconds -> +120 person-seconds ")
    assert by_key["fixes.widen-A.helps"]["why"] == (
        "Widen A, helps: yes -> no with C14's exit-choice terms on (same 36 fires).")
    assert by_key["fixes.only-old"]["why"] == "Only old: measured only with C14's exit-choice terms off."
    assert by_key["fixes.only-new"]["why"] == "Only new: measured only with C14's exit-choice terms on."
    assert by_key["top3"]["why"] == "Top 3 weak spots: Spot A, Spot B, Spot C -> Spot A, Spot C, Spot B with C14's exit-choice terms on."
    assert all(e["why"].isascii() for e in entries)
    json.dumps(entries, allow_nan=False)
    same = diff_headlines(old, old)
    assert not any(e["changed"] for e in same) and same[0]["why"].endswith("the same with C14's exit-choice terms on.")
    # The headline example: a 13-point move, and per-fire counts that differ between the sides.
    moved = diff_headlines({"whatIf": [item("p", "Stair doors propped open", smokePct=22.0)]},
                           {"whatIf": [item("p", "Stair doors propped open", smokePct=9.0)]})
    assert moved[0]["changed"] and moved[0]["why"] == (
        "Stair doors propped open, smoke exposure: +22% -> +9% with C14's exit-choice terms on (same 36 fires).")
    uneven = diff_headlines({"whatIf": [item("p", "Stair doors propped open", smokePct=22.0)]},
                            {"whatIf": [{**item("p", "Stair doors propped open", smokePct=9.0), "n": 35}]})
    assert uneven[0]["why"].endswith("(36 fires, then 35).")
    assert diff_headlines({}, {}) == []

    # exit_shift: per-exit sums over the baseline runs, 5% of the evacuees, the two largest moves named.
    def counted(*counts):
        return {"runs": [{"exitCounts": c} for c in counts]}

    shift = exit_shift(counted({"E1": 60, "E2": 20}, {"E1": 40, "E2": 30}), counted({"E1": 70, "E2": 40}, {"E1": 10, "E2": 40}), building)
    assert shift["key"] == "exitUse" and shift["changed"] is True
    assert shift["why"] == ("Exit use across the baseline fires: Exit East stair exit 50 -> 80 people, "
                            "Exit Main entrance 100 -> 80.")
    assert shift["old"] == {"Exit Main entrance": 100, "Exit East stair exit": 50}
    small = exit_shift(counted({"E1": 100, "E2": 50}), counted({"E1": 97, "E2": 53}), building)
    assert small["changed"] is False and small["why"].startswith("Exit use across the baseline fires: ")
    assert exit_shift({}, {}, building) == {"key": "exitUse", "label": "Exit use across the baseline fires", "old": {},
                                            "new": {}, "changed": False,
                                            "why": "Exit use across the baseline fires: no exit moved."}
    assert all(e["why"].isascii() for e in (shift, small))

    # stair_probe: D15's repro, through _run_one; the geometry error is False, any other error raises.
    office = load_office()
    seen = []

    def fake_one(error):
        def run_one(task):
            seen.append(task)
            return {"ok": True} if error is None else {"ok": False, "error": error}
        return run_one

    with patch("fire.refresh._init"), patch("fire.refresh._run_one", side_effect=fake_one(None)):
        assert stair_probe(office, json.loads((root / "data/buildings/office.scenario.json").read_text())) is True
    scenario = seen[0]["scenario"]
    assert seen[0]["ignition"] == {"floor": "F1", "room": "R106"} and scenario["seed"] == 2
    assert scenario["doors"]["D$77wwb"] == "blocked" and scenario["maxTime"] == 240
    assert scenario["occupants"]["total"] == 250 and scenario["fire"]["type"] == "kitchen" and scenario["fire"]["room"] == "R106"
    with patch("fire.refresh._init"), patch("fire.refresh._run_one", side_effect=fake_one(
            "RuntimeError('Agent is too close to geometry boundaries')")):
        assert stair_probe(office, base) is False
    with patch("fire.refresh._init"), patch("fire.refresh._run_one", side_effect=fake_one("ValueError('something else')")):
        try:
            stair_probe(office, base)
        except RuntimeError as error:
            assert "something else" in str(error)
        else:
            raise AssertionError("an unrelated error was swallowed")

    # The CLI. Exit 3 without C14 or (on the office) without C13b; --check prints the line and exits 0.
    stdout, stderr = StringIO(), StringIO()
    with tempfile.TemporaryDirectory() as tmp:
        here = os.getcwd()
        os.chdir(tmp)
        try:
            Path("building.json").write_text(json.dumps(building), encoding="utf-8")
            Path("office.json").write_text(json.dumps({**building, "id": "office"}), encoding="utf-8")
            Path("scenario.json").write_text(json.dumps(base), encoding="utf-8")
            argv = ["building.json", "scenario.json", "--rooms", "2", "--seeds", "1", "--workers", "2"]
            no_c14, yes_c14 = {"smokeAwareExits": False}, {"smokeAwareExits": True}
            boom = AssertionError("refresh must not run")
            with (patch("fire.refresh.refresh", side_effect=boom), redirect_stdout(stdout), redirect_stderr(stderr)):
                with patch("fire.refresh.sim_features", return_value=no_c14):
                    assert main(argv) == 3
                    assert main(argv + ["--check"]) == 0
                with patch("fire.refresh.sim_features", return_value=yes_c14), patch("fire.refresh.stair_probe", return_value=False) as probe:
                    assert main(["office.json", "scenario.json", "--check"]) == 0
                    assert main(["office.json", "scenario.json"]) == 3
                    assert probe.call_count == 2 and probe.call_args.args[0]["id"] == "office"
                with patch("fire.refresh.sim_features", return_value=yes_c14), patch("fire.refresh.stair_probe", return_value=True):
                    assert main(["office.json", "scenario.json", "--check"]) == 0
                    assert main(["nope.json", "scenario.json"]) == 1
            assert stdout.getvalue().splitlines() == [
                "C14 smoke-aware exit choice: no; C13b stair arrivals: n/a", "nothing to refresh yet",
                "C14 smoke-aware exit choice: no; C13b stair arrivals: n/a",
                "C14 smoke-aware exit choice: yes; C13b stair arrivals: no",
                "C14 smoke-aware exit choice: yes; C13b stair arrivals: no", "nothing to refresh yet",
                "C14 smoke-aware exit choice: yes; C13b stair arrivals: yes"], stdout.getvalue()
            assert stderr.getvalue().strip() == "no such file: nope.json"
            assert not Path("data").exists()

            # A whole run with refresh patched: files, renames, checkpoints and the changed lines.
            def hand_batch(scenario, pct, counts, top):
                runs = [{"scenarioId": f"hand-{r}-s1", "seed": 1, "ignition": {"floor": "F1", "room": r}, "t90": 100.0,
                         "t100": 120.0, "trapped": 0, "dosed": 0, "smokeSeconds": 100.0, "exitCounts": counts}
                        for r in ("R101", "R105")]
                return {"version": "batch/v0", "id": f"batch-{building['id']}-{scenario['id']}", "buildingId": building["id"],
                        "base": deepcopy(scenario), "runs": runs, "failed": [], "rooms": [], "doors": [], "heatmaps": [],
                        "top": [{"kind": "exit", "id": i, "floor": "F1", "score": 50.0,
                                 "why": f"Exit {i}: 3 people queued at peak; 20 person-seconds of waiting on average across 2 fires."}
                                for i in top],
                        "whatIf": [{"id": "proppedStairs", "label": "Stair doors propped open", "n": 2, "dT90": 0.0,
                                    "dTrapped": 0.0, "dSmokeSeconds": pct, "baseSmokeSeconds": 100.0, "smokePct": pct,
                                    "why": f"Stair doors propped open: 90% out 0 s later on average (slower in 0 of 2 fires); {pct:+.0f} person-seconds in smoke."}],
                        "fixes": []}

            seen_files = []

            def fake_refresh(b, sc, ignitions, seeds, workers=None, **kwargs):
                assert len(ignitions) == 2 and seeds == (1,) and workers == 2
                batches = {"legacy": hand_batch(terms_off(sc), 22.0, {"E1": 80, "E2": 80}, ["E1", "E2"]),
                           "current": hand_batch(sc, 9.0, {"E1": 60, "E2": 100}, ["E2", "E1"])}
                for side in batches:
                    kwargs["on_stage"](side, "baseline", batches[side])
                seen_files.append(sorted(p.name for p in Path("data/runs").iterdir()))
                return batches

            runs = Path("data/runs")
            runs.mkdir(parents=True)
            (runs / "batch-example-office.json").write_text("old batch", encoding="utf-8")
            (runs / "headlines-example-office.json").write_text(json.dumps({"headline": "Old headline."}), encoding="utf-8")
            (runs / "headlines-example-office.prev.json").write_text("older pack", encoding="utf-8")
            stdout = StringIO()
            with (patch("fire.refresh.sim_features", return_value=yes_c14), patch("fire.refresh.refresh", side_effect=fake_refresh),
                  redirect_stdout(stdout)):
                assert main(argv) == 0
            assert seen_files == [["batch-example-office-c14off.partial.json", "batch-example-office.json",
                                   "batch-example-office.partial.json", "headlines-example-office.json",
                                   "headlines-example-office.prev.json"]], seen_files
            names = sorted(p.name for p in runs.iterdir())
            assert names == ["batch-example-office-c14off.json", "batch-example-office.json", "batch-example-office.prev.json",
                             "headlines-example-office-c14off.json", "headlines-example-office.json",
                             "headlines-example-office.prev.json", "headlines-example-office.prev2.json"], names
            assert (runs / "batch-example-office.prev.json").read_text() == "old batch"
            assert (runs / "headlines-example-office.prev.json").read_text() == "older pack"  # never overwritten
            assert json.loads((runs / "headlines-example-office.prev2.json").read_text())["headline"] == "Old headline."
            batch_data = json.loads((runs / "batch-example-office-c14off.json").read_text())
            assert batch_data["base"]["exitChoice"] == {"smoke": 0, "unfamiliar": 0}
            data = (runs / "headlines-example-office.json").read_bytes()
            pack = json.loads(data)
            assert data.decode("ascii") == json.dumps(pack, indent=1) and b"\r" not in data and len(data) < 20_000
            assert pack["features"] == {"smokeAwareExits": True}  # stairArrivalsFixed is n/a off the office
            assert pack["legacyHeadline"] == ("Stair doors propped open: +22% person-seconds in smoke across 2 paired fires; "
                                              "90% out 0 s later on average.")
            assert pack["headline"].startswith("Stair doors propped open: +9% person-seconds in smoke")
            assert list(pack).index("legacyHeadline") == list(pack).index("headline") + 1
            assert list(pack).index("features") == list(pack).index("scenario") - 1
            assert all(c["changed"] is True for c in pack["changes"])
            assert [c["key"] for c in pack["changes"]] == ["top3", "whatIf.proppedStairs.smokePct", "exitUse"], pack["changes"]
            assert pack["sources"]["batch"]["file"] == "data/runs/batch-example-office.json"
            assert pack["sources"]["batch"]["id"] == f"batch-{building['id']}-{base['id']}"
            legacy_pack = json.loads((runs / "headlines-example-office-c14off.json").read_text())
            assert not {"features", "legacyHeadline", "changes"} & set(legacy_pack)
            assert legacy_pack["scenario"]["exitChoice"] == {"smoke": 0, "unfamiliar": 0}
            assert legacy_pack["sources"]["batch"]["file"] == "data/runs/batch-example-office-c14off.json"
            lines = stdout.getvalue().splitlines()
            assert "previous pack: Old headline." in lines
            assert "3 of 5 compared numbers changed:" in lines
            assert [c["why"] for c in pack["changes"]] == lines[lines.index("3 of 5 compared numbers changed:") + 1:][:3]
            assert any(line.startswith("unchanged: ") for line in lines) and lines[-1].startswith("runtime ")

            # --resume hands the checkpoints to refresh; without it nothing is loaded.
            (runs / "batch-example-office.partial.json").write_text(json.dumps({"marker": "current"}), encoding="utf-8")
            (runs / "batch-example-office-c14off.partial.json").write_text(json.dumps({"marker": "legacy"}), encoding="utf-8")
            handed = []

            def spy_refresh(b, sc, ignitions, seeds, workers=None, **kwargs):
                handed.append(kwargs.get("resume"))
                return {"legacy": hand_batch(terms_off(sc), 22.0, {"E1": 80, "E2": 80}, ["E1", "E2"]),
                        "current": hand_batch(sc, 9.0, {"E1": 60, "E2": 100}, ["E2", "E1"])}

            resume_out = StringIO()
            with (patch("fire.refresh.sim_features", return_value=yes_c14), patch("fire.refresh.refresh", side_effect=spy_refresh),
                  redirect_stdout(resume_out)):
                assert main(argv + ["--resume"]) == 0
                assert main(argv) == 0
            assert handed == [{"legacy": {"marker": "legacy"}, "current": {"marker": "current"}}, None], handed
            assert ("resuming from data/runs/batch-example-office.partial.json, "
                    "data/runs/batch-example-office-c14off.partial.json") in resume_out.getvalue()
            assert not list(runs.glob("*.partial.json"))

            # A stopped run: the files hold what each side finished, the comparison only what both finished.
            from fire.refresh import publish
            stopped = {"legacy": hand_batch(terms_off(base), 22.0, {"E1": 80, "E2": 80}, ["E1", "E2"]),
                       "current": hand_batch(base, 9.0, {"E1": 60, "E2": 100}, ["E1", "E2"])}
            stopped["current"]["fixes"] = [{
                "id": "widen-E1", "kind": "widen", "label": "Widen E1", "helps": True, "n": 2, "dT90": -1.0, "dTrapped": 0.0,
                "why": "Widen E1: 90% out 1 s sooner on average across 2 fires (faster in 1); +0.0 trapped per fire."}]
            with redirect_stdout(StringIO()):
                assert "fixes.widen-E1" in [c["key"] for c in publish(building, stopped, yes_c14, Path("full"))]
                cut = {side: {k: v for k, v in batch.items() if k != "fixes"} for side, batch in stopped.items()}
                kept = publish(building, stopped, yes_c14, Path("stopped"), compare=cut)
            assert not any(c["key"].startswith("fixes.") for c in kept) and any(c["changed"] for c in kept)
            held = json.loads(Path("stopped/headlines-example-office.json").read_text())
            assert [f["id"] for f in held["fixes"]] == ["widen-E1"]
            assert not any(c["key"].startswith("fixes.") for c in held["changes"])
            assert json.loads(Path("stopped/batch-example-office.json").read_text())["fixes"][0]["id"] == "widen-E1"
        finally:
            os.chdir(here)
    print("refresh: sides, overrides, diff thresholds, exit use, the C13b probe and the CLI checked", flush=True)


def check_refresh_slow():
    from fire.refresh import refresh, sim_features

    if not sim_features()["smokeAwareExits"]:
        print("refresh: skipped (the simulator has no smoke-aware exit choice, C14)", flush=True)
        return
    root = Path(__file__).resolve().parents[1]
    building = json.loads((root / "contracts/building.example.json").read_text(encoding="utf-8"))
    base = json.loads((root / "contracts/scenario.example.json").read_text(encoding="utf-8"))
    base["maxTime"] = 240
    base["occupants"] = {"total": 60, "mix": base["occupants"]["mix"]}
    ignitions = [{"floor": "F1", "room": room} for room in ("R101", "R105")]
    result = refresh(building, base, ignitions, (1,), workers=2, timeout_s=900, progress=False)
    for side in ("legacy", "current"):
        batch = result[side]
        assert not batch["failed"] and len(batch["runs"]) == 2, (side, batch["failed"])
        assert len(batch["whatIf"]) == 3 and all(w["n"] == 2 for w in batch["whatIf"]), side
        assert batch["fixes"], side
    assert result["legacy"]["base"]["exitChoice"] == {"smoke": 0, "unfamiliar": 0}
    assert "exitChoice" not in result["current"]["base"]
    print("refresh: both sides finished two fires, three what-ifs and the fixes", flush=True)


def _long_side(polygon) -> float:
    corners = list(polygon.minimum_rotated_rectangle.exterior.coords)
    return max(math.dist(corners[i], corners[i + 1]) for i in range(4))


def office_checks(path) -> str:
    """Labels, widths and exit zones of the office file at `path`; every expected value comes from that file.

    Labels are readable (an exit's label carries its name, or the stair or room it leaves when that name is
    machine text), widening uses the file's door width, and exit zones are positive and inside walkable.
    """
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from fire.batch import door_label
    from fire.fixes import widen_door

    office = load_office(path)
    doors = {d["id"]: d for f in office["floors"] for d in f["doors"]}

    def label(floor, door_id):
        kind, text = door_label(office, floor["id"], door_id)
        assert text.isascii() and ":" not in text, text  # a Revit family string never reaches a reader
        return kind, text

    def walkable(floor):
        return unary_union([Polygon(w["outer"], w["holes"]) for w in floor["walkable"]])

    count = 0
    for floor in office["floors"]:
        rooms, walk, seen = {r["id"]: r for r in floor["rooms"]}, walkable(floor), []
        for zone in floor["exits"]:
            area = Polygon(zone["polygon"])
            assert area.area > 0 and area.difference(walk).area < .01, (floor["id"], zone["id"])
            name = zone.get("name", "")
            inside = next(rooms[r] for r in doors[zone["door"]]["connects"] if r in rooms)
            if name and ":" not in name and len(name) <= 30:  # readable, by door_label's own cut-off
                want = f"Exit {name}"
            elif inside.get("type") == "stair":
                want = f"Stair {inside.get('group', inside['id'])} exit"
            else:
                want = f"Exit from {inside.get('name', inside['id'])} ({inside['id']})"
            assert label(floor, zone["door"]) == ("exit", want), (label(floor, zone["door"]), want)
            seen.append(want)
        assert len(set(seen)) == len(seen), seen  # exits read differently from each other
        count += len(seen)
    assert count, "no exits in the office file"
    floor, door, stair = next((f, d, r) for f in office["floors"] for d in f["doors"] for r in f["rooms"]
                              if r.get("type") == "stair" and r["id"] in d["connects"] and "outside" not in d["connects"])
    assert label(floor, door["id"]) == ("stair", f"Stair {stair.get('group', stair['id'])} door")
    # D23: a plain interior door whose two differently named rooms no other plain door of its floor joins reads
    # `Door between <A> and <B>`, the names in floor order (the file's own, so a rebuilt office stays green).
    for floor in office["floors"]:
        plain = [(d, [r.get("name") or r["id"] for r in floor["rooms"] if r["id"] in d["connects"]])
                 for d in floor["doors"] if "outside" not in d["connects"]
                 and not any(r.get("type") == "stair" and r["id"] in d["connects"] for r in floor["rooms"])]
        pairs = Counter(tuple(sorted(names)) for _, names in plain)
        pick = next(((d, names) for d, names in plain if len(names) == 2 and names[0] != names[1]
                     and pairs[tuple(sorted(names))] == 1 and all(n.isascii() and ":" not in n for n in names)), None)
        if pick:
            break
    else:
        raise AssertionError("no plain interior door with a pair of room names of its own in the office file")
    door, names = pick
    assert label(floor, door["id"]) == ("door", f"Door between {names[0]} and {names[1]}")
    # Widening uses the width the file declares, and the exit zone follows it.
    floor, zone = min(((f, z) for f in office["floors"] for z in f["exits"]),
                      key=lambda fz: (doors[fz[1]["door"]]["width"], fz[1]["door"]))
    did = zone["door"]
    after_floor = next(f for f in widen_door(office, did)["floors"] if f["id"] == floor["id"])
    before, after = doors[did], next(d for d in after_floor["doors"] if d["id"] == did)
    assert after["width"] == round(before["width"] + .5, 3), (before["width"], after["width"])
    opening = lambda d: float(np.linalg.norm(np.array(d["a"]) - d["b"]))
    assert abs(opening(after) - opening(before) - .5) < .01
    wide = Polygon(next(e for e in after_floor["exits"] if e["door"] == did)["polygon"])
    assert wide.area > 0 and wide.difference(walkable(after_floor)).area < .01
    assert abs((_long_side(wide) - after["width"]) - (_long_side(Polygon(zone["polygon"])) - before["width"])) < .05
    return f"{count} exits, widen {did} {before['width']:g} -> {after['width']:g} m"


def _office_variant(office: dict) -> dict:
    """The office as a rebuild could leave it: its narrowest exit door 5 cm narrower, every exit renamed."""
    from copy import deepcopy
    from fire.fixes import renormalize

    variant = deepcopy(office)
    doors = {d["id"]: d for f in variant["floors"] for d in f["doors"]}
    door = doors[min((z for f in variant["floors"] for z in f["exits"]),
                     key=lambda z: (doors[z["door"]]["width"], z["door"]))["door"]]
    a, b = np.array(door["a"]), np.array(door["b"])
    u = (b - a) / np.linalg.norm(b - a)
    door["a"], door["b"] = (a + u * .025).tolist(), (b - u * .025).tolist()
    door["width"] = round(door["width"] - .05, 3)
    door.pop("rect", None)  # the normalizer cuts the opening again from a and b
    variant = renormalize(variant)
    for floor in variant["floors"]:
        for i, zone in enumerate(floor["exits"]):  # the first keeps an unreadable name, the rest get new ones
            zone["name"] = "M_Single-Flush:0915 x 2134mm:0915 x 2134mm:184259" if i == 0 else f"Renamed exit {i}"
    return variant


def check_labels():
    from contextlib import redirect_stdout, redirect_stderr
    from copy import deepcopy
    from io import StringIO
    from unittest.mock import patch
    from fire.batch import door_label, main
    from fire.fixes import planned_fix_runs
    from fire.whatif import default_variants, stair_doors

    root = Path(__file__).resolve().parents[1]
    path = office_path()
    office = load_office(path)
    base = json.loads((root / "data/buildings/office.scenario.json").read_text())
    example = json.loads((root / "contracts/building.example.json").read_text())
    summary = office_checks(path)
    with tempfile.TemporaryDirectory() as tmp:  # the same checks on a renamed, narrowed copy of the file
        copy = Path(tmp) / "office.json"
        copy.write_text(json.dumps(_office_variant(office)), encoding="utf-8")
        variant_summary = office_checks(copy)
    for did, label in {"E1": "Exit Main entrance", "DSB1": "Stair SB door",
                       "D101": "Door between Kitchen and Corridor 1"}.items():
        assert door_label(example, "F1", did)[1] == label
    trash = deepcopy(base)
    trash["fire"]["type"] = "trash"
    kitchen = deepcopy(base)
    kitchen["fire"].update(type="kitchen", growth="slow")
    assert "sprinklers" not in {v["id"] for v in default_variants(office, trash, [])}
    assert "sprinklers" in {v["id"] for v in default_variants(office, kitchen, [])}
    stairs = stair_doors(office)
    states = {d["id"]: d["state"] for f in office["floors"] for d in f["doors"]}
    open_stairs = int(any(states[did] in ("open", "propped") for did in stairs))  # as the file has them
    assert planned_fix_runs(office, trash) == 2 + open_stairs
    assert planned_fix_runs(office, kitchen) == 3 + open_stairs
    changed = deepcopy(kitchen)
    changed["doors"] = {stairs[0]: "propped", office["floors"][0]["exits"][0]["door"]: "blocked"}
    assert planned_fix_runs(office, changed) == 5
    argv = ["fire.batch", str(path),
            str(root / "data/buildings/office.scenario.json"), "--occupants", "250",
            "--fire-type", "kitchen", "--rooms", "1", "--seeds", "1"]
    empty = {"runs": [], "failed": [], "top": []}
    with (patch("sys.argv", argv), patch("fire.batch.run_many", return_value=empty) as sweep,
          patch("pathlib.Path.write_text"), patch("pathlib.Path.mkdir"), redirect_stdout(StringIO())):
        main()
    passed = sweep.call_args.args[1]
    assert passed["occupants"] == {"total": 250, "mix": base["occupants"]["mix"]}
    assert passed["fire"]["type"] == "kitchen" and "growth" not in passed["fire"]
    with (patch("sys.argv", argv + ["--budget-min", "30", "--whatif", "--fixes", "--workers", "2"]),
          patch("fire.batch._run_one", return_value={"ok": True, "wallS": 30.0}),
          patch("fire.batch.run_many", return_value=empty),
          patch("fire.whatif.add_whatif", side_effect=lambda b, s, batch, **kw: batch) as whatif,
          patch("fire.fixes.add_fixes", side_effect=lambda b, s, batch, **kw: batch) as fixes,
          patch("pathlib.Path.write_text"), patch("pathlib.Path.mkdir"), redirect_stdout(StringIO()) as output):
        main()
    assert whatif.call_args.kwargs["rooms"] == fixes.call_args.kwargs["rooms"] == 1
    assert "3 what-ifs, 3 fixes -> 1 rooms" in output.getvalue()
    for flag, value in (("--occupants", "0"), ("--fire-type", "unknown")):
        with patch("sys.argv", argv + [flag, value]), redirect_stderr(StringIO()):
            try:
                main()
            except SystemExit as error:
                assert error.code == 2
            else:
                raise AssertionError("bad override accepted")
    print(f"labels: {path.name} ({summary}) and a renamed, narrowed copy ({variant_summary}); "
          "overrides and fix budgeting checked", flush=True)


def _names_fixture() -> dict:
    """One floor that holds every case of D23's rule: pairs of names of their own, one pair of names joined by two
    doors (the rooms in either order), two rooms of one name with three doors between them, a door with one known
    room and one with none, a colon, a non-ASCII name, an unnamed room, an exit and a stair door."""
    rooms = [{"id": rid, "type": "room", **({"name": name} if name else {})} for rid, name in (
        ("R1", "Lab: West"), ("R2", "Hall"), ("R3", "Hall"), ("R4", None), ("R5", "Café"), ("R6", "Hall"),
        ("R10", "Office"), ("R11", "Store"), ("R12", "Store"), ("R13", "Office"))]
    rooms.append({"id": "S1", "name": "Stair 1", "type": "stair", "group": "S1"})

    def door(ident, connects, x=0.0, y=0.0):  # the middle of the opening is (x, y)
        return {"id": ident, "connects": connects, "a": [x, y - .5], "b": [x, y + .5], "width": 1.0, "state": "open"}

    doors = [door("d1", ["R1", "R2"]), door("d7", ["R1", "R6"]),
             door("d2", ["R2", "R3"], 10, 5), door("d3", ["R3", "R2"], 10, 1), door("d9", ["R2", "R3"], 4, 9),
             door("d8", ["R4", "R1"]), door("d4", ["R4", "R5"]), door("d5", ["R5", "R99"]), door("d6", ["R98", "R99"]),
             door("dx", ["R10", "R11"]), door("dy", ["R13", "R12"]),
             door("E9", ["R2", "outside"]), door("dS", ["R3", "S1"])]
    return {"version": "building/v0", "id": "names-fixture", "floors": [
        {"id": "F1", "level": 0, "rooms": rooms, "doors": doors, "exits": [], "stairs": [], "walkable": []}]}


def check_door_names():
    """D23: a plain interior door reads `Door between <A> and <B>` in every text, never by its id."""
    from copy import deepcopy
    from unittest.mock import patch
    from fire.batch import aggregate, door_label, relabel, seed_ranges
    from fire.fixes import candidate_fixes, restate, widen_door
    from fire.headlines import all_whys, build_headlines

    root = Path(__file__).resolve().parents[1]
    example = json.loads((root / "contracts/building.example.json").read_text(encoding="utf-8"))
    base = json.loads((root / "contracts/scenario.example.json").read_text(encoding="utf-8"))
    office = load_office()
    clinic_path = root / "data/buildings/clinic.json"
    clinic = json.loads(clinic_path.read_text(encoding="utf-8")) if clinic_path.is_file() else None
    leak = re.compile(r"Door [A-Za-z0-9_$]+ \(")  # a label of the old kind: the door's id, then its rooms

    def has_door(building, floor_id, door_id):
        return any(d["id"] == door_id for f in building["floors"] if f["id"] == floor_id for d in f["doors"])

    # The pinned labels: the example's always, the office's and the clinic's when their files hold those doors.
    assert door_label(example, "F1", "D101") == ("door", "Door between Kitchen and Corridor 1")
    assert door_label(example, "F1", "DL1") == ("door", "Door between Lobby and Corridor 1")
    pinned = {("F1", "D$77xwP"): "Door between CORRIDOR and SCIF OPEN OFFICE",
              ("F1", "D$77xVs"): "Door between OPEN OFFICE (R113a) and CORRIDOR (R141)",
              ("F1", "D$77xaz"): "Door between OPEN OFFICE (R114) and CORRIDOR (R142)",
              ("F2", "DQnt_pi"): "Door between SECURE DOC ROOM and OPEN OFFICE"}
    office_pinned = all(has_door(office, *key) for key in pinned)  # a rebuilt office has ids of its own
    for key, want in pinned.items() if office_pinned else ():
        assert door_label(office, *key) == ("door", want), (key, door_label(office, *key))
    clinic_pinned = clinic is not None and has_door(clinic, "F1", "Dv$nmj8") and has_door(clinic, "F1", "Dv$nmZR")
    if clinic_pinned:  # two doors join the same two rooms: told apart by the middle of the opening (x, then y)
        both = "Door between TEAM INTERACTION (R1D22) and WAITING / ACTIVITY AREA (R1DC1)"
        assert door_label(clinic, "F1", "Dv$nmj8") == ("door", both + ", 1 of 2")
        assert door_label(clinic, "F1", "Dv$nmZR") == ("door", both + ", 2 of 2")
        assert door_label(clinic, "F1", "Dv$nnMB")[1] == "Door between CORRIDOR (R1AC3) and CORRIDOR (R1CC1)"
    assert door_label(example, "F1", "missing") == ("door", "Door missing")  # an unknown id keeps today's label

    # On every floor of the three buildings: a plain door's label is unique, ASCII, colon-free and without its own id.
    counted = 0
    for building in (example, office, clinic):
        for floor in (building or {"floors": []})["floors"]:
            rooms, seen = {r["id"]: r for r in floor["rooms"]}, {}
            for door in floor["doors"]:
                if "outside" in door["connects"] or any(rooms.get(c, {}).get("type") == "stair" for c in door["connects"]):
                    continue
                kind, text = door_label(building, floor["id"], door["id"])
                assert kind == "door" and text.startswith("Door ") and text.isascii() and ":" not in text, text
                assert door["id"] not in text, (building["id"], door["id"], text)
                assert text not in seen, (building["id"], floor["id"], text, door["id"], seen[text])
                seen[text] = door["id"]
            counted += len(seen)

    # Every branch of the rule, on a floor made for it.
    fixture = _names_fixture()
    want = {"d1": "Door between Lab - West (R1) and Hall (R2)", "d7": "Door between Lab - West (R1) and Hall (R6)",
            "d9": "Door between Hall (R2) and Hall (R3), 1 of 3", "d3": "Door between Hall (R2) and Hall (R3), 2 of 3",
            "d2": "Door between Hall (R2) and Hall (R3), 3 of 3", "d8": "Door between Lab - West and R4",
            "d4": "Door between R4 and Caf?", "d5": "Door from Caf?", "d6": "Door d6",
            "dx": "Door between Office (R10) and Store (R11)", "dy": "Door between Store (R12) and Office (R13)"}
    for did, text in want.items():
        assert door_label(fixture, "F1", did) == ("door", text), (did, door_label(fixture, "F1", did))
    assert door_label(fixture, "F1", "E9") == ("exit", "Exit E9")
    assert door_label(fixture, "F1", "dS") == ("stair", "Stair S1 door")
    assert len(set(want.values())) == len(want) and all(t.isascii() and ":" not in t for t in want.values())

    # widen_door names the door, not its id. An unknown id has no label, so it stays the one id in the messages.
    widened = widen_door(example, "DL1")
    altered = deepcopy(widened)
    altered["floors"][0]["walkable"].append(altered["floors"][0]["walkable"][0])
    flat = deepcopy(example)
    kitchen_door = next(d for d in flat["floors"][0]["doors"] if d["id"] == "D101")
    kitchen_door["b"] = list(kitchen_door["a"])  # an opening of no length

    def refused(building, door_id):
        try:
            widen_door(building, door_id)
        except ValueError as error:
            return str(error)
        raise AssertionError(f"widening {door_id} was accepted")

    with patch("fire.fixes.renormalize", return_value=altered):
        assert refused(example, "DL1") == ("widening Door between Lobby and Corridor 1 "
                                           "changes room connections or walkable pieces")
    assert refused(flat, "D101") == "Door between Kitchen and Corridor 1 has no opening"
    assert refused(example, "missing") == "unknown door missing"
    fixes, _ = candidate_fixes(example, base, {"top": [{"kind": "door", "id": "DL1", "floor": "F1"}]})
    assert fixes[0]["label"] == "Widen Door between Lobby and Corridor 1 from 4.00 m to 4.50 m", fixes[0]["label"]

    # The callers that write the label into a text: aggregate's `why` and the stability line.
    def record(seed):
        return {"ok": True, "scenarioId": f"hand-{seed}", "seed": seed, "ignition": {"floor": "F1", "room": "R101"},
                "t90": 100.0, "t100": None, "trapped": 0,
                "doors": [{"id": "D101", "floor": "F1", "peakQueue": 3, "waitPersonSeconds": 80.0}],
                "heatmaps": [{"floor": "F1", "origin": [0, 0], "cell": 0.5, "cols": 1, "rows": 1,
                              "d": base64.b64encode(bytes([100])).decode("ascii")}]}

    top = next(item for item in aggregate(example, base, [record(1)])["top"] if item["id"] == "D101")
    assert top["why"].startswith("Door between Kitchen and Corridor 1: 3 people queued at peak;"), top["why"]
    stability = seed_ranges(example, base, [record(1), record(2)])["stability"]["why"]
    assert stability == ("The top 3 weak spots hold in 2 of 2 seeds: Door between Kitchen and Corridor 1. "
                         "Door between Kitchen and Corridor 1 ranks first in 2 of 2."), stability

    # relabel: a hand-made office batch whose texts carry the old labels of three doors.
    picks = [("F1", "D$77xwP"), ("F1", "D$77xVs"), ("F2", "DQnt_pi")] if office_pinned else [
        (f["id"], d["id"]) for f in office["floors"] for d in f["doors"]
        if door_label(office, f["id"], d["id"])[0] == "door"][:3]

    def old(floor_id, door_id):  # the label before D23, written out here and not taken from fire.batch
        floor = next(f for f in office["floors"] if f["id"] == floor_id)
        door = next(d for d in floor["doors"] if d["id"] == door_id)
        return f"Door {door_id} ({' to '.join(r.get('name', r['id']) for r in floor['rooms'] if r['id'] in door['connects'])})"

    (fa, a), (fb, b), (fc, c) = picks
    was = [old(*pick) for pick in picks]
    now = [pinned[pick] if office_pinned else door_label(office, *pick)[1] for pick in picks]
    batch = {
        "version": "batch/v0", "id": "hand-made", "buildingId": office["id"],
        "top": [{"kind": "door", "id": a, "floor": fa, "score": 61.0,
                 "why": f"{was[0]}: 15 people queued at peak; 52 person-seconds of waiting on average across 294 fires."},
                {"kind": "room", "id": "R203c", "floor": "F2", "score": 100.0,
                 "why": "Fire in OPEN OFFICE (R203c): 0.2 people trapped on average; 90% out after 120 s (24 fires)."}],
        "stability": {"seeds": [1, 2, 3], "top3": [a, b, c], "heldIn": 2, "n": 3, "stable": False,
                      "why": f"The top 3 weak spots hold in 2 of 3 seeds: {was[0]}, {was[1]}, {was[2]}. {was[0]} ranks first in 3 of 3."},
        "whatIf": [{"id": "blockedDoor", "label": f"{was[1]} blocked", "doors": {b: "blocked"}, "sprinklers": False,
                    "n": 4, "dT90": 3.0, "slower": 3, "faster": 0, "dTrapped": 0.0,
                    "why": f"{was[1]} blocked: 90% out 3 s later on average (slower in 3 of 4 fires); +0.0 trapped per fire."}],
        "fixes": [{"id": f"widen-{a}", "kind": "widen", "door": a, "floor": fa, "n": 24, "dT90": -4.0, "faster": 15,
                   "dTrapped": -0.1, "dSmokeSeconds": -30.0, "smokePct": -6.0, "helps": True,
                   "label": f"Widen {was[0]} from 0.86 m to 1.36 m",
                   "why": f"Widen {was[0]} from 0.86 m to 1.36 m: 90% out 4 s sooner on average and 6% less time in smoke "
                          "across 24 fires (faster in 15); -0.1 trapped per fire."},
                  {"id": f"keepClear-{c}", "kind": "keepClear", "door": c, "floor": fc, "n": 24, "dT90": -2.0, "faster": 9,
                   "dTrapped": 0.0, "dSmokeSeconds": -10.0, "smokePct": -7.0, "helps": True,
                   "label": f"Keep {was[2]} clear",
                   "why": f"Keep {was[2]} clear: 90% out 2 s sooner on average and 7% less time in smoke "
                          "across 24 fires (faster in 9); +0.0 trapped per fire."}],
        "fixesSkipped": [{"id": f"widen-{b}", "reason": f"widening {b} changes room connections or walkable pieces"},
                         {"id": f"widen-{c}", "reason": f"door {c} has no opening"},
                         {"id": "widen-nowhere", "reason": "unknown door nowhere"},
                         {"id": "sprinklers", "reason": "Sprinklers already on or preset peak does not exceed the sprinkler cap."},
                         {"id": "widen-text", "reason": f"Widen {was[0]}: not measured."}]}

    def swapped(value, pairs):
        if isinstance(value, str):
            for before, after in pairs:
                value = value.replace(before, after)
            return value
        if isinstance(value, list):
            return [swapped(item, pairs) for item in value]
        if isinstance(value, dict):
            return {key: swapped(item, pairs) for key, item in value.items()}
        return value

    def texts(value, key=None):  # every string value, with the field it sits in
        if isinstance(value, str):
            yield key, value
        elif isinstance(value, dict):
            for field, item in value.items():
                yield from texts(item, field)
        elif isinstance(value, list):
            for item in value:
                yield from texts(item, key)

    snapshot = deepcopy(batch)
    expected = swapped(batch, list(zip(was, now)))
    expected["fixesSkipped"][0]["reason"] = f"widening {now[1]} changes room connections or walkable pieces"
    expected["fixesSkipped"][1]["reason"] = f"{now[2]} has no opening"
    result = relabel(office, batch)
    assert batch == snapshot and result is not batch  # pure
    assert result == expected  # only the texts moved: ids, numbers and every other text are as they were
    assert relabel(office, result) == result  # and a second pass changes nothing
    assert not any(leak.search(text) for _, text in texts(result)), [t for _, t in texts(result) if leak.search(t)]
    shown = [text for field, text in texts(result) if field in ("why", "label", "reason")]
    assert not any(ident in text for ident in (a, b, c) for text in shown)
    assert result["fixesSkipped"][2]["reason"] == "unknown door nowhere"  # no door, no label to give
    assert restate(relabel(office, batch)) == relabel(office, restate(batch))  # D22's rewrite and this one commute
    pack = build_headlines(office, batch, generated="2026-11-14T15:00:00Z")  # the pack relabels its input itself
    first = pack["weakSpots"][0]
    assert first["label"] == now[0] and first["why"].startswith(now[0] + ": ")
    assert pack["fixes"][0]["label"] == f"Widen {now[0]} from 0.86 m to 1.36 m"
    assert not any(leak.search(text) or ident in text for text in all_whys(pack) for ident in (a, b, c))
    assert not any(leak.search(text) for _, text in texts(pack))
    folded = {"top": [{"why": "Door d4 (R4 to Caf?): 3 people queued."}, {"why": "Door d4 (R4 to Café): 3 people queued."}]}
    assert [t["why"] for t in relabel(fixture, folded)["top"]] == ["Door between R4 and Caf?: 3 people queued."] * 2
    # An old label that two floors would name differently is left alone, never guessed.
    twin = {"version": "building/v0", "id": "twin", "floors": [
        {"id": "F1", "rooms": [{"id": f"{n}{i}", "name": n.upper()} for i in (1, 2) for n in ("a", "b")],
         "doors": [{"id": "dd", "connects": ["a1", "b1"]}, {"id": "dz", "connects": ["a2", "b2"]}]},
        {"id": "F2", "rooms": [{"id": "a3", "name": "A"}, {"id": "b3", "name": "B"}],
         "doors": [{"id": "dd", "connects": ["a3", "b3"]}]}]}
    assert door_label(twin, "F1", "dd")[1] != door_label(twin, "F2", "dd")[1]
    assert relabel(twin, {"top": [{"why": "Door dd (A to B): 2 people queued."}]}) == {"top": [{"why": "Door dd (A to B): 2 people queued."}]}
    json.dumps(pack, allow_nan=False)
    print(f"door names: {counted} plain doors in {'three buildings' if clinic else 'two buildings'}, unique per floor; "
          f"every branch of the rule, widen messages, aggregate, relabel ({'pinned' if office_pinned else 'office file'} "
          "doors) and the headline pack checked", flush=True)


def _tiny_rooms(building: dict) -> list:
    """D24: (floor id, room) for each room with no grid node inside it, a room thinner than a smoke cell."""
    graph = get_graph(building)
    return [(floor["id"], room) for floor, grid in zip(building["floors"], graph.floors) for room in floor["rooms"]
            if not shapely.contains_xy(shapely.Polygon(room["polygon"]), grid.xy[:, 0], grid.xy[:, 1]).any()]


def check_tiny_room():
    """D24: a fire in a room thinner than a smoke cell starts at the nearest node a straight walk reaches."""
    from fire.model import FireModel

    # The fixture: A ends at x = 10, a 0.2 m wall stands before B, and the grid's nodes sit at x = 9.75 and 10.25.
    building = fixture_building()
    graph = get_graph(building)
    grid, in_a = graph.floors[0], shapely.Polygon(building["floors"][0]["rooms"][0]["polygon"])
    side = _ring(box(9.9, 3, 9.99, 5))  # 0.09 x 2 m along A's east side: no node inside, one 0.15 m away in A
    node = graph.node_at("F1", 9.945, 4, side)
    assert in_a.contains(shapely.Point(*grid.xy[node])) and math.dist(grid.xy[node], (9.945, 4)) < 0.5, grid.xy[node]
    assert graph.node_at("F1", 0, 0, side) == node  # a point off the room anchors at its representative point
    walled = _ring(box(10.02, 3, 10.18, 5))  # inside the wall: every node beside it is behind a wall
    try:
        graph.node_at("F1", 10.1, 4, walled)
    except ValueError as error:
        assert str(error) == "No grid nodes inside or beside the requested room on F1", error
    else:
        raise AssertionError("a room inside a wall must raise ValueError")

    # The office: each thin room gets a node within a cell of it, one a straight walk over walkable floor reaches.
    office = load_office()
    graph = get_graph(office)
    tiny = _tiny_rooms(office)
    for floor_id, room in tiny:
        index, polygon = graph.floor_index[floor_id], shapely.Polygon(room["polygon"])
        grid, anchor = graph.floors[index], polygon.representative_point()
        xy = grid.xy[graph.node_at(floor_id, anchor.x, anchor.y, room["polygon"]) - graph.offset[index]]
        assert polygon.distance(shapely.Point(*xy)) <= grid.spec["cell"], (room["id"], xy)
        assert grid.walk.covers(shapely.LineString([xy, (anchor.x, anchor.y)])), (room["id"], xy)
    r203b = next((r for f, r in tiny if (f, r["id"]) == ("F2", "R203b")), None)
    if r203b and np.allclose(shapely.Polygon(r203b["polygon"]).bounds, (0.331, 23.818, 5.897, 24.026), atol=1e-3):
        index = graph.floor_index["F2"]  # pinned: the node at (3.25, 23.75) in R201, 0.22 m from the room's point
        xy = graph.floors[index].xy[graph.node_at("F2", 3.114, 23.922, r203b["polygon"]) - graph.offset[index]]
        assert np.allclose(xy, (3.25, 23.75)), xy
        scenario = json.loads((ROOT / "data/buildings/office.scenario.json").read_text(encoding="utf-8"))
        scenario["fire"].update(type="kitchen", floor="F2", room="R203b", x=3.114, y=23.922)
        assert np.allclose(FireModel(office, scenario).source_xy, (3.25, 23.75))
    print(f"tiny rooms: fixture sliver, wall sliver, and {len(tiny)} thin office rooms "
          f"({', '.join(r['id'] for _, r in tiny) or 'none'}) checked", flush=True)


def check_tiny_room_slow():
    """D24: a fire in the office's thin room runs to the end, and every room of the clinic has a node."""
    from fire.batch import _init, _run_one, _tasks, apply_overrides

    office = load_office()
    tiny = _tiny_rooms(office)
    pick = next((p for p in tiny if (p[0], p[1]["id"]) == ("F2", "R203b")), tiny[0] if tiny else None)
    if pick:
        base = apply_overrides(json.loads((ROOT / "data/buildings/office.scenario.json").read_text(encoding="utf-8")),
                               60, "kitchen")
        base["maxTime"] = 240
        _init(office)
        record = _run_one(_tasks(office, base, [{"floor": pick[0], "room": pick[1]["id"]}], (1,))[0])
        assert record["ok"] is True, record
        print(f"tiny rooms: {pick[1]['id']}, seed 1, 60 occupants: t90={record['t90']} trapped={record['trapped']}",
              flush=True)
    path = ROOT / "data/buildings/clinic.json"
    if path.is_file():  # the clinic file is optional, as in check_door_names
        clinic = json.loads(path.read_text(encoding="utf-8"))
        graph = get_graph(clinic)
        for floor in clinic["floors"]:
            for room in floor["rooms"]:
                point = shapely.Polygon(room["polygon"]).representative_point()
                graph.node_at(floor["id"], point.x, point.y, room["polygon"])  # raises when the room has no node
        print(f"tiny rooms: all {sum(len(f['rooms']) for f in clinic['floors'])} clinic rooms have a node", flush=True)


def _rows(entries) -> list:
    return [(e["floor"], e["room"], e["ignite"]) for e in entries]


def check_spread():
    """D25: the presets, the room graph, the ignition schedule, and the doors and heat the model adds as rooms ignite."""
    from copy import deepcopy
    from fire.model import FireModel
    from fire.spread import DEFAULT_MATERIAL, MATERIALS, ignition_schedule, material_name, room_hrr_kw, room_links
    from fire.stub import NoFire

    # Presets: wood is faster than drywall, which is faster than concrete, in every column; a door beats a wall, and the
    # floor (D26) is slower than a door.
    for column in ("flashover", "door", "wall", "floor"):
        assert MATERIALS["wood"][column] < MATERIALS["drywall"][column] < MATERIALS["concrete"][column], column
    assert all(preset["door"] < preset["wall"] and preset["door"] < preset["floor"] for preset in MATERIALS.values())
    assert DEFAULT_MATERIAL == "drywall" and list(MATERIALS) == ["concrete", "drywall", "wood"]
    assert room_hrr_kw(1500.0, 300.0, -1) == 0.0 and room_hrr_kw(1500.0, 300.0, 0) == 0.0
    assert room_hrr_kw(1500.0, 300.0, 150) == 375.0 and room_hrr_kw(1500.0, 300.0, 300) == 1500.0
    assert room_hrr_kw(1500.0, 300.0, 3000) == 1500.0

    # Names: a missing key is drywall; anything but the exact names raises the same message, from the model too.
    assert material_name({}) == "drywall" and material_name({"type": "kitchen"}) == "drywall"
    assert [material_name({"material": name}) for name in MATERIALS] == list(MATERIALS)
    for bad in ("Wood", "steel", "", None, 3, ["wood"]):
        try:
            material_name({"material": bad})
        except ValueError as error:
            assert str(error) == f"Unknown fire material {bad!r}; valid names: concrete, drywall, wood", error
        else:
            raise AssertionError(f"material {bad!r} must raise ValueError")
    building = fixture_building()
    base = {"fire": {"floor": "F1", "room": "A", "x": 8, "y": 5, "type": "kitchen", "start": 0},
            "sprinklers": False, "doors": {}, "maxTime": 1300}
    for spread in (True, False):
        try:
            FireModel(building, {**base, "fire": {**base["fire"], "material": "steel"}}, spread=spread)
        except ValueError as error:
            assert str(error) == "Unknown fire material 'steel'; valid names: concrete, drywall, wood", error
        else:
            raise AssertionError("a bad material must fail the model")

    # The two-room fixture: A and B stand 0.2 m apart along 6 m, joined by door D. A fire in A.
    def schedule(b, material=None, start=0, **changes):
        fire = {**base["fire"], "start": start, **({"material": material} if material else {})}
        return ignition_schedule(b, {**base, "fire": fire, **changes})

    links = room_links(building)
    assert links[("F1", "A")] == {("F1", "B"): "door"} and links[("F1", "B")] == {("F1", "A"): "door"}
    assert schedule(building, "drywall") == [{"room": "A", "floor": "F1", "ignite": 0.0},
                                             {"room": "B", "floor": "F1", "ignite": 180.0}]
    assert [_rows(schedule(building, m))[1] for m in ("wood", "concrete")] == [("F1", "B", 90.0), ("F1", "B", 300.0)]
    assert _rows(schedule(building)) == _rows(schedule(building, "drywall"))  # the default
    walled = deepcopy(building)
    walled["floors"][0]["doors"] = []
    assert room_links(walled)[("F1", "A")] == {("F1", "B"): "wall"}
    assert [_rows(schedule(walled, m))[1] for m in ("drywall", "wood", "concrete")] == [
        ("F1", "B", 600.0), ("F1", "B", 240.0), ("F1", "B", 1200.0)]
    assert _rows(schedule(building, "drywall", start=50)) == [("F1", "A", 50.0), ("F1", "B", 230.0)]
    assert _rows(schedule(building, "drywall", maxTime=170)) == [("F1", "A", 0.0)]
    assert _rows(schedule(building, "drywall", maxTime=180)) == [("F1", "A", 0.0), ("F1", "B", 180.0)]
    assert _rows(schedule(building, "drywall", sprinklers=True)) == [("F1", "A", 0.0)]
    assert _rows(schedule(building, "wood", maxTime=None)) == [("F1", "A", 0.0), ("F1", "B", 90.0)]  # the sim's default
    cut = deepcopy(walled)  # 0.6 m of shared wall is too short; 1.2 m is enough
    cut["floors"][0]["rooms"][1]["polygon"] = _ring(box(10.2, 0, 20.2, 0.6))
    assert room_links(cut)[("F1", "A")] == {} and _rows(schedule(cut, "wood")) == [("F1", "A", 0.0)]
    cut = deepcopy(walled)
    cut["floors"][0]["rooms"][1]["polygon"] = _ring(box(10.2, 0, 20.2, 1.2))
    assert room_links(cut)[("F1", "A")] == {("F1", "B"): "wall"}
    odd = deepcopy(building)  # a degenerate room links to nothing and breaks nothing
    odd["floors"][0]["rooms"].append({"id": "Z", "polygon": [[0, 0], [1, 1]]})
    assert room_links(odd)[("F1", "Z")] == {} and schedule(odd, "wood") == schedule(building, "wood")
    # With no room named, the room around the fire point is the origin; a point in no room gives no schedule.
    anonymous = {key: value for key, value in base["fire"].items() if key != "room"}
    assert _rows(ignition_schedule(building, {**base, "fire": {**anonymous, "x": 15, "y": 3}})) == [
        ("F1", "B", 0.0), ("F1", "A", 180.0)]
    assert ignition_schedule(building, {**base, "fire": {**anonymous, "x": 10.1, "y": 3}}) == []  # in the wall
    assert ignition_schedule(building, {**base, "fire": {**anonymous, "x": 50, "y": 3}}) == []

    # Doors and heat: a drywall kitchen fire against its spread=False twin.
    model, twin = FireModel(building, base), FireModel(building, base, spread=False)
    wanted = [{"room": "A", "floor": "F1", "ignite": 0.0}, {"room": "B", "floor": "F1", "ignite": 180.0}]
    assert model.material == twin.material == "drywall"
    assert model.ignition_times() == wanted and twin.ignition_times() == wanted[:1]
    assert model.burning_rooms(-1) == set()
    for t in range(1, 181):
        model.step(t)
        twin.step(t)
        assert np.array_equal(model._footprint, twin._footprint), t
        if t < 180:
            assert model.hrr(t) == twin.hrr(t), t
            assert np.array_equal(model._density, twin._density), t
            assert model.blocked_doors() == twin.blocked_doors(), t
    assert "D" in model.blocked_doors() and "D" not in twin.blocked_doors()
    assert model.hrr(330) - twin.hrr(330) == 375.0 and model.hrr(480) - twin.hrr(480) == 1500.0
    assert model.burning_rooms(179.9) == {("F1", "A")}
    assert model.burning_rooms(180) == {("F1", "A"), ("F1", "B")} and twin.burning_rooms(400) == {("F1", "A")}
    for t in range(181, 401):
        model.step(t)
        twin.step(t)
        assert np.array_equal(model._footprint, twin._footprint), t
    returned = model.ignition_times()
    returned[1]["ignite"] = -1.0
    returned.clear()
    assert model.ignition_times() == wanted
    # Smoke grows with every burning room: a trash fire peaks at 0.5 MW, so wood's second room (90 s) adds smoke.
    trash = {**base, "fire": {**base["fire"], "type": "trash", "material": "wood"}}
    model, twin = FireModel(building, trash), FireModel(building, trash, spread=False)
    for t in (60, 89):
        model.step(t)
        twin.step(t)
        assert np.array_equal(model._density, twin._density), t
    model.step(200)
    twin.step(200)
    assert model.hrr(200) > twin.hrr(200) == 500.0 and model._density.max() > twin._density.max()

    # The example: a kitchen fire in R101 at (8, 3) over 400 s, each material.
    example = json.loads((ROOT / "contracts/building.example.json").read_text(encoding="utf-8"))
    scenario = json.loads((ROOT / "contracts/scenario.example.json").read_text(encoding="utf-8"))
    scenario.update(maxTime=400, sprinklers=False)
    assert (scenario["fire"]["room"], scenario["fire"]["x"], scenario["fire"]["y"]) == ("R101", 8, 3)

    def burn(material, **fire):
        return {**scenario, "fire": {**scenario["fire"], "material": material, **fire}}

    ten = ("R102", "L1", "R103", "R104", "R105", "R106", "R107", "R108", "SA1", "SB1")
    expected = {"drywall": [("F1", "R101", 0.0), ("F1", "C1", 180.0)] + [("F1", r, 360.0) for r in ten],
                "wood": ([("F1", "R101", 0.0), ("F1", "C1", 90.0)] + [("F1", r, 180.0) for r in ten]
                         + [("F2", "SA2", 270.0), ("F2", "SB2", 270.0), ("F2", "R201", 300.0), ("F2", "C2", 360.0)]),
                # D26: R201 stands over the kitchen R101, so with wood it ignites through the floor at 300 s
                "concrete": [("F1", "R101", 0.0), ("F1", "C1", 300.0)]}
    for material, want in expected.items():
        got = ignition_schedule(example, burn(material))
        assert _rows(got) == want, (material, got)
    lobby = shapely.Polygon(next(r for r in example["floors"][0]["rooms"] if r["id"] == "L1")["polygon"])
    point = lobby.representative_point()
    assert _rows(ignition_schedule(example, burn("drywall", room="L1", x=point.x, y=point.y))) == (
        [("F1", "L1", 0.0), ("F1", "C1", 180.0)]
        + [("F1", r, 360.0) for r in ("R101", "R102", "R103", "R104", "R105", "R106", "R107", "R108", "SA1", "SB1")])
    links = room_links(example)  # 24 door links (2 of them stairs) and 22 wall-only links, as measured
    assert sum(kind == "door" for a, near in links.items() for b, kind in near.items() if a < b) == 24
    assert sum(kind == "wall" for a, near in links.items() for b, kind in near.items() if a < b) == 22
    across = {frozenset((a[1], b[1])) for a, near in links.items() for b in near if a[0] != b[0]}
    assert across == {frozenset(("SA1", "SA2")), frozenset(("SB1", "SB2"))}, across  # only stairs link floors

    # Deterministic: equal calls, equal ignition per room in a copy with the floors reversed, plain JSON.
    wood = burn("wood")
    first = ignition_schedule(example, wood)
    assert first == ignition_schedule(example, wood)
    flipped = {**example, "floors": list(reversed(example["floors"]))}
    assert {(e["floor"], e["room"]): e["ignite"] for e in ignition_schedule(flipped, wood)} == {
        (e["floor"], e["room"]): e["ignite"] for e in first}
    json.dumps(first, allow_nan=False)
    one, other = FireModel(example, wood), FireModel(flipped, wood)
    assert one.material == "wood" and [one.hrr(t) for t in range(0, 401, 20)] == [other.hrr(t) for t in range(0, 401, 20)]
    assert one.hrr(100) > FireModel(example, wood, spread=False).hrr(100)

    # NoFire has the two methods and no material: the sim writes the new run keys only for a model that has one.
    none = NoFire(example, scenario)
    assert none.burning_rooms(10) == set() and none.ignition_times() == [] and not hasattr(none, "material")

    # The office, when its file is there. The pinned numbers belong to the demo's file; a rebuilt office gets the checks
    # that hold for any building.
    path = office_path()
    if not path.is_file():
        print(f"spread: {path.name} missing, skipped the office part", flush=True)
        return
    office = load_office(path)
    started = time.perf_counter()
    links = room_links(office)
    built = time.perf_counter() - started
    pairs = Counter(kind for a, near in links.items() for b, kind in near.items() if a < b)
    assert built < 2, built
    office_scenario = json.loads((ROOT / "data/buildings/office.scenario.json").read_text(encoding="utf-8"))
    rooms = [(f["id"], r["id"]) for f in office["floors"] for r in f["rooms"]]
    pinned = ("F1", "R143") in rooms and ("F1", "R143A") in rooms
    if not pinned:  # a rebuilt office has ids of its own
        office_scenario["fire"].update(floor=rooms[0][0], room=rooms[0][1])
    reached = {m: len(ignition_schedule(office, {**office_scenario, "maxTime": 400,
                                                 "fire": {**office_scenario["fire"], "material": m}}))
               for m in ("concrete", "drywall", "wood")}
    assert 1 <= reached["concrete"] <= reached["drywall"] <= reached["wood"], reached
    if pinned:
        assert (office_scenario["fire"]["floor"], office_scenario["fire"]["room"]) == ("F1", "R143")
        assert (pairs["door"], pairs["wall"]) == (91, 176), pairs
        assert [reached[m] for m in ("concrete", "drywall", "wood")] == [9, 21, 46], reached  # wood was 37 before D26
    print(f"spread: fixture and example (12 rooms by 400 s with drywall, 16 with wood, 2 with concrete) and "
          f"{'the office' if pinned else 'a rebuilt office'}: {pairs['door']} door and {pairs['wall']} wall-only links in "
          f"{built:.2f} s, rooms on fire by 400 s (concrete/drywall/wood) {reached['concrete']}/{reached['drywall']}/"
          f"{reached['wood']}", flush=True)


def check_floor_spread():
    """D26: fire climbs through the floor to the rooms right above, never down; stair links and the room graph stay as
    they were."""
    from copy import deepcopy
    from fire.model import FireModel
    from fire.spread import FLOOR_MIN_M2, MATERIALS, floor_links, ignition_schedule, room_hrr_kw, room_links

    # The material order holds for the floor delay too, and a floor is slower than a door.
    assert MATERIALS["wood"]["floor"] < MATERIALS["drywall"]["floor"] < MATERIALS["concrete"]["floor"]
    assert all(preset["floor"] > preset["door"] for preset in MATERIALS.values())
    assert FLOOR_MIN_M2 == 2.0

    # The two-floor fixture: F1 holds A and B (door D), F2 holds C right over B and E beside C (door DC). Fire in A.
    building = two_floor_fixture()
    base = {"fire": {"floor": "F1", "room": "A", "x": 8, "y": 5, "type": "kitchen", "start": 0},
            "sprinklers": False, "doors": {}, "maxTime": 1300}

    def schedule(material, room="A", floor="F1", b=None, start=0, **changes):
        fire = {**base["fire"], "floor": floor, "room": room, "material": material, "start": start}
        return ignition_schedule(b or building, {**base, "fire": fire, **changes})

    rises = floor_links(building)
    assert rises[("F1", "B")] == {("F2", "C"): "floor"}
    assert rises[("F1", "A")] == {} and rises[("F2", "C")] == {} and rises[("F2", "E")] == {}  # one way: nothing links down
    assert list(rises) == list(room_links(building))  # every room, in building order
    assert all(kind in ("door", "wall") for near in room_links(building).values() for kind in near.values())

    # Wood: B through door D at 90 s, C through the floor at B's own ignite time plus the floor delay, E through door DC.
    got = _rows(schedule("wood"))
    assert got == [("F1", "A", 0.0), ("F1", "B", 90.0), ("F2", "C", 390.0), ("F2", "E", 480.0)], got
    ignite = {room: t for _, room, t in got}
    assert ignite["C"] == ignite["B"] + MATERIALS["wood"]["floor"] and ignite["E"] == ignite["C"] + MATERIALS["wood"]["door"]
    assert _rows(schedule("wood", room="B")) == [("F1", "B", 0.0), ("F1", "A", 90.0), ("F2", "C", 300.0), ("F2", "E", 390.0)]
    assert _rows(schedule("wood", start=50)) == [("F1", "A", 50.0), ("F1", "B", 140.0), ("F2", "C", 440.0), ("F2", "E", 530.0)]
    assert _rows(schedule("wood", maxTime=389)) == [("F1", "A", 0.0), ("F1", "B", 90.0)]
    assert _rows(schedule("wood", maxTime=390)) == [("F1", "A", 0.0), ("F1", "B", 90.0), ("F2", "C", 390.0)]
    assert _rows(schedule("wood", sprinklers=True)) == [("F1", "A", 0.0)]  # sprinklers keep the fire in its room
    assert _rows(schedule("drywall")) == [("F1", "A", 0.0), ("F1", "B", 180.0), ("F2", "C", 1080.0), ("F2", "E", 1260.0)]
    # Concrete: the slab holds. No upward spread within 600 s, nor before B's 300 s plus the floor's 3600 s.
    assert _rows(schedule("concrete", maxTime=600)) == [("F1", "A", 0.0), ("F1", "B", 300.0)]
    assert _rows(schedule("concrete", maxTime=3899)) == [("F1", "A", 0.0), ("F1", "B", 300.0)]
    assert _rows(schedule("concrete", maxTime=3900)) == [("F1", "A", 0.0), ("F1", "B", 300.0), ("F2", "C", 3900.0)]
    # Upward only: a fire on F2 never reaches F1, whatever the material or the horizon.
    for material, door in (("wood", 90.0), ("drywall", 180.0), ("concrete", 300.0)):
        assert _rows(schedule(material, room="C", floor="F2", maxTime=20000)) == [("F2", "C", 0.0), ("F2", "E", door)], material
        assert {floor for floor, _, _ in _rows(schedule(material, room="E", floor="F2", maxTime=20000))} == {"F2"}, material
    # Deterministic: the same schedule per room with the floors listed in the other order.
    flipped = {**building, "floors": list(reversed(building["floors"]))}
    assert {(e["floor"], e["room"]): e["ignite"] for e in schedule("wood", b=flipped)} == {
        (f, r): t for f, r, t in got}

    # The model: C ignites at 390 s with wood and closes its door DC; with concrete nothing on F2 burns within 600 s.
    wood = {**base, "fire": {**base["fire"], "material": "wood"}}
    model, twin = FireModel(building, wood), FireModel(building, wood, spread=False)
    assert [(e["floor"], e["room"], e["ignite"]) for e in model.ignition_times()] == got and len(twin.ignition_times()) == 1
    model.step(389)
    assert model.burning_rooms(389) == {("F1", "A"), ("F1", "B")} and "DC" not in model.blocked_doors()
    model.step(390)
    assert model.burning_rooms(390) == {("F1", "A"), ("F1", "B"), ("F2", "C")} and "DC" in model.blocked_doors()
    twin.step(400)
    model.step(400)
    assert "DC" not in twin.blocked_doors()
    peak = model.params["peakKw"]
    assert abs(model.hrr(400) - twin.hrr(400) - (peak + room_hrr_kw(peak, MATERIALS["wood"]["flashover"], 10))) < 1e-6
    model = FireModel(building, {**base, "fire": {**base["fire"], "material": "concrete"}})
    model.step(600)
    assert model.burning_rooms(600) == {("F1", "A"), ("F1", "B")} and "DC" not in model.blocked_doors()
    assert not any(floor == "F2" for floor, _ in model.burning_rooms(600))

    # The rule: at least 2 m2 of overlap (measured, not the upper room's own area), the next level up, no stair rooms.
    def stack(floors, levels=(0, 1)):
        return {"version": "building/v0", "id": "stack", "floors": [
            {"id": f"F{n + 1}", "level": level, "stairs": [], "exits": [], "doors": [], "walkable": [],
             "rooms": [{"id": room, "polygon": _ring(polygon)} for room, polygon in rooms.items()]}
            for n, (rooms, level) in enumerate(zip(floors, levels))]}

    big = box(0, 0, 10, 6)

    def over(polygon, **more):
        return floor_links(stack([{"P": big}, {"Q": polygon}], **more))[("F1", "P")]

    assert over(box(0, 0, 2, 1)) == {("F2", "Q"): "floor"}  # exactly 2 m2
    assert over(box(0, 0, 1.9, 1)) == {} and over(box(9, 0, 13, 1.9)) == {}  # 1.9 m2, one of them in a 7.6 m2 room
    assert over(box(8, 0, 12, 1)) == {("F2", "Q"): "floor"}  # 2 m2 over the room, 2 m2 beyond its wall
    assert over(box(20, 0, 30, 6)) == {}  # beside it, not above it
    assert over(big, levels=(0, 0)) == {}  # two floors on one level are not one above the other
    assert over(big, levels=(0, 2)) == {("F2", "Q"): "floor"}  # the next level up, whatever the numbers
    upside = floor_links(stack([{"Q": big}, {"P": big}], levels=(1, 0)))  # F1 is the upper floor: levels decide, not order
    assert upside[("F2", "P")] == {("F1", "Q"): "floor"} and upside[("F1", "Q")] == {}
    tower = stack([{"P": big}, {"Q": big}, {"R": big}], levels=(0, 1, 2))
    assert floor_links(tower)[("F1", "P")] == {("F2", "Q"): "floor"} and floor_links(tower)[("F2", "Q")] == {("F3", "R"): "floor"}
    assert _rows(ignition_schedule(tower, {**base, "fire": {**base["fire"], "room": "P", "material": "wood"}})) == [
        ("F1", "P", 0.0), ("F2", "Q", 300.0), ("F3", "R", 600.0)]  # two floors up burns after the floor between
    typed = stack([{"P": big}, {"Q": big}])
    typed["floors"][0]["rooms"][0]["type"] = "stair"
    assert floor_links(typed)[("F1", "P")] == {}  # a room typed stair
    named = stack([{"P": big}, {"Q": big}])
    named["floors"][1]["stairs"] = [{"id": "S", "room": "Q", "group": "G"}]
    assert floor_links(named)[("F1", "P")] == {}  # a room a stair names
    odd = deepcopy(stack([{"P": big}, {"Q": big}]))  # a degenerate room links to nothing and breaks nothing
    odd["floors"][1]["rooms"].append({"id": "Z", "polygon": [[0, 0], [1, 1]]})
    assert floor_links(odd)[("F1", "P")] == {("F2", "Q"): "floor"} and floor_links(odd)[("F2", "Z")] == {}

    # The example: ten links, none of them a stair room's, and the stairs are the only room-graph links across floors.
    example = json.loads((ROOT / "contracts/building.example.json").read_text(encoding="utf-8"))
    pairs = sorted((a[1], b[1]) for a, near in floor_links(example).items() for b in near)
    assert pairs == [("C1", "C2"), ("L1", "R203"), ("R101", "R201"), ("R102", "R202"), ("R103", "R204"), ("R104", "R205"),
                     ("R105", "R206"), ("R106", "R207"), ("R107", "R208"), ("R108", "R209")], pairs
    across = {frozenset((a[1], b[1])) for a, near in room_links(example).items() for b in near if a[0] != b[0]}
    assert across == {frozenset(("SA1", "SA2")), frozenset(("SB1", "SB2"))}, across
    assert all(kind == "door" for a, near in room_links(example).items() for b, kind in near.items() if a[0] != b[0])

    # The office, when its file is there: the rule holds for every link, whatever the building.
    path = office_path()
    if not path.is_file():
        print(f"floor spread: {path.name} missing, skipped the office part", flush=True)
        return
    office = load_office(path)
    levels = {f["id"]: f["level"] for f in office["floors"]}
    polygons = {(f["id"], r["id"]): shapely.Polygon(r["polygon"]).buffer(0) for f in office["floors"] for r in f["rooms"]}
    stairs = {(f["id"], r["id"]) for f in office["floors"] for r in f["rooms"] if r.get("type") == "stair"}
    stairs |= {(f["id"], s["room"]) for f in office["floors"] for s in f.get("stairs", [])}
    ups = floor_links(office)
    count = sum(len(near) for near in ups.values())
    for low, near in ups.items():
        for high, kind in near.items():
            assert kind == "floor" and levels[high[0]] > levels[low[0]], (low, high)
            assert low not in stairs and high not in stairs, (low, high)
            assert polygons[low].intersection(polygons[high]).area >= FLOOR_MIN_M2, (low, high)
    rooms = [(f["id"], r["id"]) for f in office["floors"] for r in f["rooms"]]
    pinned = ("F1", "R143") in rooms and ("F1", "R143A") in rooms
    scenario = json.loads((ROOT / "data/buildings/office.scenario.json").read_text(encoding="utf-8"))
    scenario.update(maxTime=400, sprinklers=False)
    if pinned:
        assert count == 117, count  # 60 rooms with a room above them, 41 with a room below
        up = {m: ignition_schedule(office, {**scenario, "fire": {**scenario["fire"], "material": m}}) for m in MATERIALS}
        assert [len(up[m]) for m in ("concrete", "drywall", "wood")] == [9, 21, 46]
        assert {e["floor"] for e in up["drywall"]} == {"F1"}  # a drywall floor (900 s) holds past 400 s
        assert sum(e["floor"] == "F2" for e in up["wood"]) == 13 and {e["floor"] for e in up["concrete"]} == {"F1"}
    print(f"floor spread: fixture (wood C at 390 s, concrete holds 600 s, upward only), the rule and the example's 10 links, "
          f"{'the office' if pinned else 'a rebuilt office'}: {count} floor links", flush=True)


def check_spread_slow():
    """D25: the example's kitchen fire over 400 s with drywall, simulated: the corridor's doors close as it ignites."""
    from sim.run import run
    from fire.model import FireModel

    building = json.loads((ROOT / "contracts/building.example.json").read_text(encoding="utf-8"))
    scenario = json.loads((ROOT / "contracts/scenario.example.json").read_text(encoding="utf-8"))
    scenario.update(maxTime=400, sprinklers=False)
    scenario["fire"]["material"] = "drywall"
    # C28's social cue (people who see others leave start sooner) gets all 160 out by 129 s, before the corridor ignites at 180 s,
    # so the run ends with no door left to close. This check is about the spread, not the crowd's pace: it keeps the crowd as it
    # was (socialFollowing false: event for event as before C28, with its one person still inside at 180 s).
    scenario["socialFollowing"] = False
    assert scenario["occupants"]["total"] == 160
    result = run(building, scenario, FireModel(building, scenario))
    first = {}
    for event in result["events"]:
        if event["type"] == "door_blocked":
            first.setdefault(event["door"], event["t"])
    corridor = ("D101", "D102", "D103", "D104", "D105", "D106", "D107", "D108", "DL1", "DSA1", "DSB1")
    for door in corridor:
        assert door in first and first[door] <= 180.0, (door, first.get(door))
    for door in corridor[1:]:
        assert first[door] == 180.0, (door, first[door])  # the corridor ignites at 180 s: its other ten doors close then
    reasons = Counter(event["reason"] for event in result["events"] if event["type"] == "trapped")
    assert result["metrics"]["trapped"] == sum(reasons.values()), (result["metrics"]["trapped"], reasons)
    print(f"spread: the corridor's 11 doors closed by 180 s (D101 at {first['D101']:g} s, the other ten at 180); "
          f"trapped {result['metrics']['trapped']} of 160 by reason {dict(reasons)}; "
          f"t50={result['metrics']['t50']} t90={result['metrics']['t90']}", flush=True)


def check_office_slow():
    from fire.batch import run_many
    root = Path(__file__).resolve().parents[1]
    office = load_office()
    base = json.loads((root / "data/buildings/office.scenario.json").read_text())
    base["occupants"] = {"total": 250, "mix": base["occupants"]["mix"]}
    base["fire"]["type"] = "kitchen"
    base["fire"].pop("growth", None)
    base["maxTime"] = 300
    batch = run_many(office, base, [dict(floor="F1", room=r) for r in ("R110", "R143")],
                     seeds=(1,), workers=2, timeout_s=600)
    assert not batch["failed"], batch["failed"]
    assert batch["top"]
    assert all(item["why"].isascii() and "M_" not in item["why"] for item in batch["top"])
    print("office: 250 occupants, two kitchen fires, readable weak spots", flush=True)


def run_all(slow: bool = False):
    for name, check in sorted(globals().copy().items()):
        if name.startswith("check_") and callable(check) and (slow or not name.endswith("_slow")):
            check()
    print("fire checks OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slow", action="store_true")
    run_all(parser.parse_args().slow)
