"""Small executable checks: python -m fire.checks [--slow]."""
import argparse
import base64
import json
from pathlib import Path
import time

import numpy as np
import shapely
from shapely.geometry import box

from fire.grid import BuildingGraph, CLOSED_DOOR_M, MAX_CELLS, get_graph, grid_specs
from fire.presets import fire_params, hrr_kw


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
    model = FireModel(building, scenario)
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
    jump = FireModel(building, scenario)
    jump.step(200)
    seconds = FireModel(building, scenario)
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
        snapped = FireModel(building, sc)
        assert shapely.contains_xy(shapely.Polygon(building["floors"][0]["rooms"][0]["polygon"]),
                                   *snapped.source_xy)
    delayed = FireModel(building, {**scenario, "fire": {**scenario["fire"], "start": 50}})
    delayed.step(49)
    assert delayed.hrr(49) == 0 and delayed.snapshot("F1") is None
    assert not delayed.untenable("F1", *delayed.source_xy)
    delayed.step(110)
    reference = FireModel(building, scenario)
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
        model = FireModel(building, {**scenario, "fire": {**scenario["fire"], "type": preset}})
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
    from fire.whatif import stair_doors, default_variants, compare, add_whatif

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
    for path in (root / "contracts/building.example.json", root / "data/buildings/office.json"):
        source = json.loads(path.read_text())
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
    assert all(f["helps"] and np.isclose(f["smokePct"], -20) for f in result["fixes"])
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
    json.dumps(result, allow_nan=False)
    json.dumps(inverses, allow_nan=False)


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


def check_labels():
    from contextlib import redirect_stdout, redirect_stderr
    from copy import deepcopy
    from io import StringIO
    from unittest.mock import patch
    from shapely.geometry import Polygon
    from fire.batch import door_label, main
    from fire.fixes import planned_fix_runs, widen_door
    from fire.whatif import default_variants

    root = Path(__file__).resolve().parents[1]
    office = json.loads((root / "data/buildings/office.json").read_text())
    base = json.loads((root / "data/buildings/office.scenario.json").read_text())
    example = json.loads((root / "contracts/building.example.json").read_text())
    expected = {"DrRS91$": "Exit from ENTRY (R101)", "D$77wwb": "Stair S1 exit",
                "D$77xsW": "Stair S1 door", "D$77xVs": "Door D$77xVs (OPEN OFFICE to CORRIDOR)"}
    for did, label in expected.items():
        assert door_label(office, "F1", did)[1] == label, door_label(office, "F1", did)
    for did, label in {"E1": "Exit Main entrance", "DSB1": "Stair SB door",
                       "D101": "Door D101 (Kitchen to Corridor 1)"}.items():
        assert door_label(example, "F1", did)[1] == label
    trash = deepcopy(base)
    trash["fire"]["type"] = "trash"
    kitchen = deepcopy(base)
    kitchen["fire"].update(type="kitchen", growth="slow")
    assert "sprinklers" not in {v["id"] for v in default_variants(office, trash, [])}
    assert "sprinklers" in {v["id"] for v in default_variants(office, kitchen, [])}
    assert planned_fix_runs(office, trash) == 2
    assert planned_fix_runs(office, kitchen) == 3
    changed = deepcopy(kitchen)
    changed["doors"] = {"D$77xsW": "propped", "DrRS91$": "blocked"}
    assert planned_fix_runs(office, changed) == 5
    widened = widen_door(office, "D$77wwb")
    floor = widened["floors"][0]
    assert next(d for d in floor["doors"] if d["id"] == "D$77wwb")["width"] == 1.41
    zone = next(e for e in floor["exits"] if e["door"] == "D$77wwb")
    assert abs(Polygon(zone["polygon"]).area - 1.70) < .02
    argv = ["fire.batch", str(root / "data/buildings/office.json"),
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
    print("labels: office labels, widening, overrides and fix budgeting checked", flush=True)


def check_office_slow():
    from fire.batch import run_many
    root = Path(__file__).resolve().parents[1]
    office = json.loads((root / "data/buildings/office.json").read_text())
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
