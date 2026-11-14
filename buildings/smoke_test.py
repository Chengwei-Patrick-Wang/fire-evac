"""Smoke test for the normalizer: python -m buildings.smoke_test

Normalizes contracts/plan.example.json, writes debug/building.example.json,
and checks the review-focus geometry (rooms separated by walls, exits, stairs).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from shapely.geometry import Polygon
from shapely.ops import unary_union

from buildings.normalize import plan_to_building

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "contracts" / "plan.example.json"
OUT = ROOT / "debug" / "building.example.json"
IFC_PATH = ROOT / "data" / "raw" / "team-downloads" / "Office_A_20110811.ifc"


def hard_plan():
    def room(id, points, kind="office", group=None):
        r = {"id": id, "name": id, "type": kind, "polygon": points}
        if group:
            r["group"] = group
        return r
    def door(id, a, b, **kwargs):
        return {"id": id, "a": a, "b": b, "width": 1.0, "fireDoor": False, "state": "open", **kwargs}
    return {"version": "plan/v0", "id": "hard", "source": "ifc", "floors": [
        {"id": "F1", "level": 0, "elevation": 0, "height": 3.5, "rooms": [
            room("L1", [[0,0],[8,0],[8,3],[3,3],[3,6],[0,6]], "lobby"),
            room("R2", [[8.4,0],[14,0],[17,3],[14,6],[8.4,6]]),
            room("SL", [[0,6.4],[3,6.4],[3,9.4],[0,9.4]], "stair", "SA"),
            room("R9", [[8.4,6.6],[14,6.6],[14,8.6],[8.4,8.6]])], "doors": [
            door("D1", [8.2,1], [8.2,2], rect=[[8.1,1],[8.3,1],[8.3,2],[8.1,2]]),
            door("DS", [1,6.2], [2,6.2], fireDoor=True, state="closed"),
            door("DX", [15.146,1.146], [15.854,1.854])]},
        {"id": "F2", "level": 1, "elevation": 3.5, "height": 3.5, "rooms": [
            room("U1", [[0,0],[8,0],[8,6],[0,6]]),
            room("SU", [[0,6.4],[3,6.4],[3,9.4],[0,9.4]], "stair", "SB")], "doors": [
            door("DSU", [1,6.2], [2,6.2], fireDoor=True, state="closed"),
            door("DU", [0,2], [0,3])]}]}


def check_hard():
    import copy
    plan = hard_plan()
    b = plan_to_building(plan)
    f1, f2 = b["floors"]
    assert len(f1["walkable"]) == 2 and len(f2["walkable"]) == 1
    main = Polygon(f1["walkable"][0]["outer"], f1["walkable"][0]["holes"])
    assert Polygon(plan["floors"][0]["rooms"][0]["polygon"]).difference(main).area < 0.05
    for door in f1["doors"]:
        if door["id"] in {"D1", "DS"}:
            for rid in door["connects"]:
                room = next(r for r in f1["rooms"] if r["id"] == rid)
                assert Polygon(door["rect"]).intersection(Polygon(room["polygon"])).area >= 0.01
    assert {e["id"] for e in f1["exits"]} == {"DX"}
    assert {e["id"] for e in f2["exits"]} == {"DU"}
    exit_poly = Polygon(f1["exits"][0]["polygon"])
    assert all(exit_poly.intersection(Polygon(r["polygon"])).area < 1e-8 for r in f1["rooms"])
    c = exit_poly.centroid
    dx, dy = c.x - 15.5, c.y - 1.5
    assert (dx - dy) * 0.7071 / (dx*dx + dy*dy)**0.5 >= 0.95
    gap = copy.deepcopy(plan)
    gap["floors"] = [{"id": "F1", "rooms": [
        {"id": "A", "polygon": [[0,0],[6,0],[6,4],[0,4]]},
        {"id": "B", "polygon": [[0,6.6],[6,6.6],[6,10.6],[0,10.6]]}],
        "doors": [{"id": "D", "a": [2.5,4], "b": [3.5,4], "width": 1}]}]
    assert not plan_to_building(gap)["floors"][0]["exits"]


def check_overrides():
    from buildings.validate import validate
    plan = hard_plan()
    report = validate(plan_to_building(plan))
    assert len(report["disconnected"]) == 1
    assert report["disconnected"][0]["rooms"] == ["R9"]
    assert abs(report["disconnected"][0]["gap"] - 0.6) < 0.03
    assert [r["id"] for r in report["roomsNoDoor"]] == ["R9"]
    assert {(s["group"], s["floor"]) for s in report["stairSingle"]} == {("SA", "F1"), ("SB", "F2")}
    assert report["upperExits"] == [{"floor": "F2", "door": "DU"}]
    assert not report["ok"]
    overrides = {"doors": {"add": [{"floor": "F1", "id": "DFIX1", "a": [10.9, 6.3],
                                     "b": [11.9, 6.3], "width": 1.0}]},
                 "stairGroups": {"SA": ["SL", "SU"]}, "exits": {"remove": ["DU"]}}
    building = plan_to_building(plan, overrides=overrides)
    report = validate(building)
    assert report["ok"] and not report["exits"]["F2"]
    assert all(f["stairs"][0]["group"] == "SA" for f in building["floors"])
    assert plan["floors"][1]["rooms"][1]["group"] == "SB"
    gap_plan = {"id": "gap", "source": "ifc", "floors": [{"id": "F1", "rooms": [
        {"id": "A", "polygon": [[0, 0], [6, 0], [6, 4], [0, 4]]},
        {"id": "B", "polygon": [[0, 6.6], [6, 6.6], [6, 10.6], [0, 10.6]]}],
        "doors": [{"id": "D", "a": [2.5, 4], "b": [3.5, 4], "width": 1}]}]}
    forced = plan_to_building(gap_plan, overrides={"exits": {"add": ["D"]}})
    assert "D" in {e["id"] for e in forced["floors"][0]["exits"]}
    for bad in ({"doors": {"remove": ["missing"]}}, {"exits": {"add": ["missing"]}},
                {"stairGroups": {"S": ["missing"]}},
                {"doors": {"add": [{"floor": "missing", "id": "D"}]}}):
        try:
            plan_to_building(plan, overrides=bad)
        except ValueError as exc:
            assert "missing" in str(exc)
        else:
            raise AssertionError(f"accepted unknown id: {bad}")


def check_ifc():
    from buildings.ifc import group_stairs
    def stair(id, x):
        return {"id": id, "type": "stair", "polygon": [[x, 0], [x+3, 0], [x+3, 5], [x, 5]]}
    sample = [{"rooms": [stair("a", 0)]}, {"rooms": [stair("b", 0.5), stair("c", 10)]}]
    group_stairs(sample)
    assert sample[0]["rooms"][0]["group"] == sample[1]["rooms"][0]["group"]
    assert sample[1]["rooms"][0]["group"] != sample[1]["rooms"][1]["group"]

def check_building(name="office"):
    from buildings.validate import validate
    building = json.loads((ROOT / f"data/buildings/{name}.json").read_text(encoding="utf-8"))
    assert validate(building)["ok"]
    assert "license" in building["credits"].lower()
    assert any(f["exits"] for f in building["floors"] if f["level"] == 0)
    groups = {}
    for floor in building["floors"]:
        rooms = {r["id"]: Polygon(r["polygon"]) for r in floor["rooms"]}
        for stair in floor["stairs"]:
            groups.setdefault(stair["group"], set()).add(floor["id"])
        for door in floor["doors"]:
            assert 0.6 <= door["width"] <= 3.0
            if "outside" not in door["connects"]:
                for rid in door["connects"]:
                    assert Polygon(door["rect"]).intersection(rooms[rid]).area >= 0.01, (door["id"], rid)
    assert groups and all(len(floors) >= 2 for floors in groups.values())


def check_clinic():
    from buildings.fixups import apply_overrides
    from buildings.ifc import _room_type
    from buildings.normalize import largest_inner_rect
    from buildings.validate import validate
    b = json.loads((ROOT / "data/buildings/clinic.json").read_text(encoding="utf-8"))
    assert len(b["floors"]) == 2 and not validate(b)["nonConvex"]
    assert all({s["group"] for s in f["stairs"]} == {"S1", "S2", "S3"} for f in b["floors"])
    assert all(r["name"].upper() not in {"ROOF", "OPEN TO BELOW", "ELEVATOR"} for f in b["floors"] for r in f["rooms"])
    assert all(":" not in e["name"] for f in b["floors"] for e in f["exits"])
    assert "CC BY 4.0" in b["credits"] and "buildingSMART" in b["credits"]
    for name, kind in [("JAN. CL.", "storage"), ("TELE/COMM RM", "storage"), ("MENS RR", "restroom"), ("SEC. WAIT", "lounge"), ("VEST.", "lobby"), ("CONF. ROOM", "office"), ("INTERACTION STATION", "other")]:
        assert _room_type(name) == kind
    assert len(apply_overrides(hard_plan(), {"floors": {"remove": ["F2"]}})["floors"]) == 1
    for fid in ("F1", "F9"):
        try:
            apply_overrides(hard_plan(), {"floors": {"remove": [fid]}})
        except ValueError as exc:
            assert fid in str(exc)
        else:
            raise AssertionError(fid)
    office = json.loads((ROOT / "data/buildings/office.json").read_text(encoding="utf-8"))
    stair = next(s for f in office["floors"] for s in f["stairs"] if s["id"] == "RS101")
    poly = Polygon(stair["polygon"])
    rect = largest_inner_rect(poly)
    assert len(rect.exterior.coords) == 5 and poly.buffer(0.005).covers(rect)
    assert 0.95 <= rect.area / poly.area <= 0.97


def check_traced():
    from shapely import make_valid
    from buildings.validate import validate

    def room(rid, polygon):
        return {"id": rid, "type": "office", "polygon": polygon}

    def door(did, x, y):
        return {"id": did, "a": [x, y], "b": [x, y + 1], "width": 1}

    plan = {"id": "sloppy-trace", "source": "trace", "floors": [{
        "id": "F1", "rooms": [
            room("A", [[0, 0], [4, 0], [4, 4], [4, 4], [0, 4]]),
            room("B", [[4.15, 0], [8.15, 0], [8.15, 4], [4.15, 4]]),
            room("C", [[8.05, 0], [12.15, 0], [12.15, 4], [8.05, 4]]),
            room("bow", [[12, 0], [16, 4], [12, 4], [16, 0]]),
        ], "doors": [door("AB", 3.7, 1), door("BC", 8.1, 1),
                     door("bottom", 12.05, 0.2), door("top", 12.05, 2.8)]}]}
    floor = plan_to_building(plan)["floors"][0]
    assert validate({"floors": [floor]})["disconnected"] == []
    rooms = {r["id"]: make_valid(Polygon(r["polygon"])) for r in floor["rooms"]}
    interior = [d for d in floor["doors"] if "outside" not in d["connects"]]
    assert {d["id"] for d in interior} == {"AB", "BC", "bottom", "top"}
    for d in interior:
        for rid in d["connects"]:
            assert Polygon(d["rect"]).intersection(rooms[rid]).area >= 0.01, (d["id"], rid)
    walkable = unary_union([Polygon(p["outer"], p["holes"]) for p in floor["walkable"]])
    assert walkable.intersection(rooms["bow"]).area > 1


def check_one_door():
    fixture = ROOT / "buildings/fixtures/one_door.plan.json"
    plan = json.loads(fixture.read_text(encoding="utf-8-sig"))
    building = plan_to_building(plan)
    assert len(building["floors"]) == 1
    floor = building["floors"][0]
    assert {e["id"] for e in floor["exits"]} == {"D1"}
    exit_poly = Polygon(floor["exits"][0]["polygon"])
    assert all(exit_poly.intersection(Polygon(r["polygon"])).area < 1e-8 for r in floor["rooms"])


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    b = plan_to_building(plan)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(b, indent=1), encoding="utf-8")

    assert b["version"] == "building/v0"
    assert len(b["floors"]) == 2, f"expected 2 floors, got {len(b['floors'])}"

    groups_by_floor = {}
    for f in b["floors"]:
        assert len(f["walkable"]) == 1, f"{f['id']}: {len(f['walkable'])} walkable polygons"
        walk = Polygon(f["walkable"][0]["outer"], f["walkable"][0]["holes"])
        assert walk.is_valid and walk.area > 0, f"{f['id']}: bad walkable polygon"
        groups_by_floor[f["id"]] = {s["group"] for s in f["stairs"]}
        print(f"{f['id']}: walkable area {walk.area:.1f} m2, exits {sorted(e['id'] for e in f['exits'])}, "
              f"stairs {sorted(s['id'] for s in f['stairs'])}")

        # Each room's share of the walkable area (= the shrunk room plus door bits).
        room_walk = {r["id"]: Polygon(r["polygon"]).intersection(walk) for r in f["rooms"]}

        # Every interior door's rect must reach into the walkable part of both rooms.
        for d in f["doors"]:
            if "outside" in d["connects"]:
                continue
            rect = Polygon(d["rect"])
            for rid in d["connects"]:
                assert rect.intersection(room_walk[rid]).area > 1e-3, \
                    f"{f['id']}/{d['id']}: rect does not reach into {rid}"

        # Exits sit inside the walkable area (at the far end of a stub).
        for e in f["exits"]:
            ez = Polygon(e["polygon"])
            assert walk.buffer(1e-6).contains(ez), f"{f['id']}/{e['id']}: exit zone outside walkable"

        if f["id"] == "F1":
            assert {e["id"] for e in f["exits"]} == {"E1", "E2"}, f"F1 exits: {[e['id'] for e in f['exits']]}"
            gap = room_walk["R101"].distance(room_walk["R102"])
            assert gap >= 0.15, f"R101 and R102 are only {gap:.3f} m apart (walls merged?)"
            print(f"F1: R101-R102 wall gap {gap:.3f} m")

    for g in ("SA", "SB"):
        for fid, groups in groups_by_floor.items():
            assert g in groups, f"stair group {g} missing on {fid}"

    reference = json.loads((ROOT / "contracts" / "building.example.json").read_text(encoding="utf-8"))
    for floor, expected in zip(b["floors"], reference["floors"]):
        for key in ("rooms", "doors", "exits"):
            assert {v["id"] for v in floor[key]} == {v["id"] for v in expected[key]}
        area = sum(Polygon(p["outer"], p["holes"]).area for p in floor["walkable"])
        expected_area = sum(Polygon(p["outer"], p["holes"]).area for p in expected["walkable"])
        assert abs(area - expected_area) / expected_area < 0.01

    check_budget()
    check_summary()
    check_tidy()
    check_traced()
    check_one_door()
    check_hard()
    check_overrides()
    check_building()
    check_building("clinic")
    check_clinic()
    pick = ROOT / "data" / "raw" / "pick.plan.json"
    if pick.exists():
        for floor in plan_to_building(json.loads(pick.read_text(encoding="utf-8")))["floors"]:
            rooms = {r["id"]: Polygon(r["polygon"]) for r in floor["rooms"]}
            for door in floor["doors"]:
                if "outside" not in door["connects"]:
                    for rid in door["connects"]:
                        assert Polygon(door["rect"]).intersection(rooms[rid]).area >= 0.01, (floor["id"], door["id"], rid)

    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")
    check_ifc()
    print("OK")
    return 0





def check_budget():
    from buildings.normalize import door_openings
    from buildings.summary import vertex_count
    from buildings.validate import validate
    base = plan_to_building(hard_plan())
    budget = plan_to_building(hard_plan(), max_vertices=1)
    assert validate(base) == validate(budget)
    for a, b in zip(base["floors"], budget["floors"]):
        before, after = door_openings(a), door_openings(b)
        assert all(abs(value - after[key]) <= 0.02 for key, value in before.items())
    plan = {"id": "notch", "source": "ifc", "floors": [{"id": "F1", "rooms": [
        {"id": "R", "polygon": [[0,0],[6,0],[6,4],[3.3,4],[3.3,3.7],[3,3.7],[3,4],[0,4]]}],
        "doors": [{"id": "D", "a": [1,0], "b": [2,0], "width": 1}]}]}
    original = plan_to_building(plan)["floors"][0]
    reduced = plan_to_building(plan, max_vertices=1)["floors"][0]
    assert vertex_count(original) - vertex_count(reduced) == 4


def check_summary():
    from buildings.summary import build_index, summarize
    folder = ROOT / "data/buildings"
    office_path = folder / "office.json"
    office = summarize(json.loads(office_path.read_text(encoding="utf-8")), str(office_path))
    expected = {"floors": 2, "rooms": 109, "doors": 104, "exits": 6,
                "stairGroups": ["S1", "S2"], "walkableArea": 3479.5,
                "vertices": 1173, "size": [54.2, 38.4],
                "shortCredit": "NIBS Common BIM File, US Army ERDC/CERL, free download"}
    for key, value in expected.items():
        assert office[key] == value, (key, office[key], value)
    index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
    assert index == build_index(folder), "index.json is stale: run python -m buildings.summary"
    assert "id" not in index and "floors" not in index
    assert "umass" not in json.dumps(index).lower()
    expected_files = {p.name for p in folder.glob("*.json")
                      if json.loads(p.read_text(encoding="utf-8")).get("version") == "building/v0"
                      and not json.loads(p.read_text(encoding="utf-8")).get("private", False)}
    assert {b["file"] for b in index["buildings"]} == expected_files


def check_tidy():
    import copy
    from buildings.tidy import tidy_floor
    floor = json.loads((ROOT / "buildings/fixtures/ai_floor.json").read_text(encoding="utf-8-sig"))
    original = copy.deepcopy(floor)
    cleaned, notes = tidy_floor(floor)
    expected = {
        "AI1": [[0,0],[6,0],[6,4],[0,4]],
        "AI2": [[6,0],[14,0],[14,2],[8,2],[8,6],[6,6]],
        "AI3": [[0,7],[4,7],[4,10],[0,10]],
        "AI5": [[8,2],[12,2],[12,5],[8,5]],
        "AI8": [[20,0],[23,3],[20,6],[17,3]],
    }
    assert {r["id"]: r["polygon"] for r in cleaned["rooms"]} == expected
    assert any("AI4: merged into AI1" in n for n in notes)
    assert any("AI5: trimmed" in n for n in notes)
    assert all(any(f"{rid}: dropped" in n for n in notes) for rid in ("AI6", "AI7", "AI9"))
    polygons = [Polygon(r["polygon"]) for r in cleaned["rooms"]]
    assert all(abs(c * 4 - round(c * 4)) < 1e-8 for r in cleaned["rooms"] for point in r["polygon"] for c in point)
    assert all(a.intersection(b).area <= 0.01 for i, a in enumerate(polygons) for b in polygons[i+1:])
    assert tidy_floor(cleaned) == (cleaned, [])
    assert floor == original
    plan_to_building({"version": "plan/v0", "id": "ai", "source": "trace", "floors": [cleaned]})


if __name__ == "__main__":
    sys.exit(main())

