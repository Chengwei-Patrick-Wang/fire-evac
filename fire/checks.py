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
    assert base == original
    # Kill a spawned batch before any simulation can finish; don't hang shutdown.
    started = time.perf_counter()
    expired = run_many(building, base, ignitions, seeds=(1,), workers=2, timeout_s=0.001, progress=False)
    assert expired["runs"] == [] and len(expired["failed"]) == 2
    assert time.perf_counter() - started < 10
    print("batch: 2 spawned runs match inline runs; timeout records both failures", flush=True)


def run_all(slow: bool = False):
    for name, check in sorted(globals().copy().items()):
        if name.startswith("check_") and callable(check) and (slow or not name.endswith("_slow")):
            check()
    print("fire checks OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slow", action="store_true")
    run_all(parser.parse_args().slow)
