"""Small executable checks: python -m fire.checks [--slow]."""
import argparse
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


def run_all(slow: bool = False):
    for name, check in sorted(globals().copy().items()):
        if name.startswith("check_") and callable(check) and (slow or not name.endswith("_slow")):
            check()
    print("fire checks OK")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slow", action="store_true")
    run_all(parser.parse_args().slow)
