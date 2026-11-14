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

def check_public_buildings():
    from buildings.validate import problems
    found, ids = [], set()
    for path in sorted((ROOT / 'data/buildings').glob('*.json')):
        building = json.loads(path.read_text(encoding='utf-8'))
        if building.get('version') != 'building/v0':
            continue
        if building['id'] != path.stem:
            found.append(f'{path.name} id does not match file stem')
        if building['id'] in ids:
            found.append(f"{path.name} duplicate id {building['id']}")
        ids.add(building['id'])
        scenario_path = path.with_name(path.stem + '.scenario.json')
        scenario = json.loads(scenario_path.read_text(encoding='utf-8')) if scenario_path.exists() else None
        issues = problems(building, scenario)
        found.extend(f'{path.name} {issue}' for issue in issues)
        if not issues:
            exits = sum(len(f['exits']) for f in building['floors'])
            print(f"public {path.name}: {len(building['floors'])} floors, {exits} exits, clean")
    assert not found, 'public buildings:\n  ' + '\n  '.join(found)


def check_problems():
    import copy
    from buildings.validate import problems
    plan = hard_plan()
    plan['name'] = 'Synthetic test'
    plan['credits'] = 'Synthetic test plan; license: CC0'
    issues = problems(plan_to_building(plan))
    assert any('R9' in s and 'cut off' in s for s in issues)
    assert any('R9' in s and 'no door' in s for s in issues)
    assert all(any(f'group {group}' in s for s in issues) for group in ('SA', 'SB'))
    overrides = {'doors': {'add': [{'floor': 'F1', 'id': 'DFIX1', 'a': [10.9, 6.3],
                                   'b': [11.9, 6.3], 'width': 1.0}]},
                 'stairGroups': {'SA': ['SL', 'SU']}, 'exits': {'remove': ['DU']}}
    fixed = plan_to_building(plan, overrides=overrides)
    assert not problems(fixed), problems(fixed)
    for width, flagged in ((4.0, False), (7.0, True)):
        bad = copy.deepcopy(fixed)
        bad['floors'][0]['doors'][0]['width'] = width
        assert any('width outside 0.6-6.0 m' in issue for issue in problems(bad)) == flagged
    bad = copy.deepcopy(fixed)
    bad['credits'] = ''
    assert any('credits' in s for s in problems(bad))
    bad = copy.deepcopy(fixed)
    zone = bad['floors'][0]['exits'][0]
    poly = Polygon(zone['polygon'])
    x, y = poly.exterior.coords[0]
    # Remove a small triangle from a corner, yielding a concave polygon.
    coords = list(poly.exterior.coords)[:-1]
    a, b = coords[1], coords[-1]
    def toward(p):
        length = ((p[0]-x)**2 + (p[1]-y)**2)**0.5
        return [x + (p[0]-x)*0.1/length, y + (p[1]-y)*0.1/length]
    zone['polygon'] = [toward(b), [x + (toward(a)[0]-x) + (toward(b)[0]-x), y + (toward(a)[1]-y) + (toward(b)[1]-y)], toward(a)] + coords[1:]
    assert any('DX' in s and 'not convex' in s for s in problems(bad))
    bad = copy.deepcopy(fixed)
    zone = bad['floors'][0]['exits'][0]
    zone['polygon'] = [[x + 50, y + 50] for x, y in zone['polygon']]
    assert any('DX' in s and 'outside walkable' in s for s in problems(bad))
    scenario = {'buildingId': fixed['id'], 'fire': {'floor': 'F1', 'room': 'R999', 'x': 0, 'y': 0}, 'occupants': {'total': 1}}
    assert any('R999' in s for s in problems(fixed, scenario))


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
    stair = next(s for f in office["floors"] for s in f["rooms"] if s["id"] == "RS101")
    poly = Polygon(stair["polygon"])
    rect = largest_inner_rect(poly)
    assert len(rect.exterior.coords) == 5 and poly.buffer(0.005).covers(rect)
    assert 0.95 <= rect.area / poly.area <= 0.97



def check_office():
    from buildings.ifc import _door_name
    office = json.loads((ROOT / "data/buildings/office.json").read_text(encoding="utf-8"))
    scenario = json.loads((ROOT / "data/buildings/office.scenario.json").read_text(encoding="utf-8"))
    exits = {e["id"]: e["name"] for f in office["floors"] for e in f["exits"]}
    assert exits == {"DMO2yd9": "Elec Rm (east)", "D$77x5b": "Open Office (west)",
                     "DrRS91$": "Entry (south)", "DMO2yaj": "Mech Rm (east)",
                     "D$77wwb": "Stair S1 (west)", "DMO2yZ0": "Stair S2 (east)"}
    assert all(":" not in item.get("name", "") and "M_" not in item.get("name", "")
               for f in office["floors"] for key in ("doors", "exits") for item in f[key])
    f1 = office["floors"][0]
    assert {"R101", "R106", "R110", "R125", "R143", "RS101"} <= {r["id"] for r in f1["rooms"]}
    doors = {d["id"]: d for d in f1["doors"]}
    assert {"D$77wwb", "D$77xsW", "D$77xVs", "DrRS91$", "DMO2yZ0"} <= doors.keys()
    assert doors["DrRS91$"]["name"] == "Double door" and doors["DrRS91$"]["ifcName"].startswith("M_Double-Flush")
    assert _door_name("M_Single-Flush:0915 x 2134mm Rated") == "Single door, rated"
    assert scenario["id"] == "office-fire" and scenario["occupants"]["total"] == 250
    assert scenario["fire"]["type"] == "kitchen" and scenario["fire"]["room"] == "R143"
    assert scenario["seed"] == 1 and scenario["maxTime"] == 400


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
    check_public_buildings()
    check_problems()
    check_clinic()
    check_office()
    check_door_widths()
    check_plan_images()
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





def check_plan_images():
    import contextlib
    import io
    import math
    from PIL import Image
    from buildings.plan_images import OUT as images_dir, build
    from buildings.validate import problems, validate

    generated = build()
    for name, value in generated.items():
        path = images_dir / name
        assert path.exists() and json.loads(path.read_text(encoding="utf-8")) == value, "run python -m buildings.plan_images"
    index = generated['index.json']
    for rec in index['images']:
        with Image.open(images_dir / rec['file']) as image:
            assert image.size == (rec['width'], rec['height'])
        assert math.dist(rec['scaleBar']['p1'], rec['scaleBar']['p2']) == 10 * rec['pxPerM']
    rec = next(r for r in index['images'] if r['file'] == 'example-F1.png')
    with Image.open(images_dir / rec['file']) as image:
        def pixel(x, y):
            return image.getpixel((round(rec['origin'][0] + x * rec['pxPerM']),
                                   round(rec['origin'][1] - y * rec['pxPerM'])))
        assert pixel(8, 3) == (255, 255, 255)
        assert pixel(12, 3) == (0, 0, 0)
    example = json.loads((ROOT / 'contracts/building.example.json').read_text(encoding='utf-8'))
    trace = generated['example.trace.json']
    for floor, source in zip(trace['floors'], example['floors']):
        scale = floor['scale']['meters'] / math.dist(floor['scale']['p1'], floor['scale']['p2'])
        def original(point):
            return [(point[0] - floor['ref'][0]) * scale, (floor['ref'][1] - point[1]) * scale]
        for room, expected in zip(floor['rooms'], source['rooms']):
            assert room['id'] == expected['id']
            assert len(room['polygon']) == len(expected['polygon'])
            assert all(math.dist(original(p), q) <= 0.001 for p, q in zip(room['polygon'], expected['polygon']))
        for door, expected in zip(floor['doors'], source['doors']):
            assert door['id'] == expected['id']
            assert all(math.dist(original(door[k]), expected[k]) <= 0.001 for k in ('a', 'b'))
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        building = plan_to_building(generated['example.plan.json'])
    assert 'WARNING (normalize)' not in stderr.getvalue(), stderr.getvalue()
    assert validate(building)['ok']
    assert {e['name'] for f in building['floors'] for e in f['exits']} == {'Main entrance', 'East stair exit'}
    assert all({s['group'] for s in f['stairs']} == {'SA', 'SB'} for f in building['floors'])
    assert not problems(building), problems(building)


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
                "stairGroups": ["S1", "S2"], "walkableArea": 3478.0,
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


def check_door_widths():
    from statistics import median
    from buildings.door_widths import clear_width, cut_width, leaves
    assert [leaves(s) for s in ('DOUBLE_DOOR_SINGLE_SWING', 'SINGLE_SWING_LEFT',
                                 'DOUBLE_SWING_RIGHT', 'NOTDEFINED')] == [2, 1, 1, 0]
    assert abs(clear_width(0.915, 'SINGLE_SWING_RIGHT', 0.051) - 0.864) < 1e-9
    assert abs(clear_width(1.83, 'DOUBLE_DOOR_SINGLE_SWING', None) - 1.73) < 1e-9
    for name in ('office', 'clinic'):
        building = json.loads((ROOT / f'data/buildings/{name}.json').read_text(encoding='utf-8'))
        doors = {d['id']: d for f in building['floors'] for d in f['doors']}
        if name == 'office':
            assert (doors['DrRS91$']['width'], doors['DrRS91$']['overallWidth'], doors['DrRS91$']['leaves']) == (1.73, 1.83, 2)
            assert doors['D$77wwb']['width'] == 0.86
        assert all(d['width'] <= d['overallWidth'] for d in doors.values() if 'overallWidth' in d)
        diffs = [cut_width(f, d) - d['width'] for f in building['floors'] for d in f['doors']
                 if 'outside' not in d['connects']]
        assert 0 <= median(diffs) <= 0.05


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


