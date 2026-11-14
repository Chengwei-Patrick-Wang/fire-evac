"""Summarize connectivity and exit issues in a normalized building."""
from collections import defaultdict

from shapely import make_valid
from shapely.geometry import Point, Polygon
from shapely.ops import nearest_points, unary_union


def validate(building: dict) -> dict:
    report = {"disconnected": [], "roomsNoDoor": [], "stairSingle": [],
              "exits": {}, "upperExits": [], "nonConvex": []}
    groups = defaultdict(set)
    lowest = min((f.get("level", 0) for f in building["floors"]), default=0)
    for floor in building["floors"]:
        fid = floor["id"]
        rooms = {r["id"]: make_valid(Polygon(r["polygon"])) for r in floor["rooms"]}
        pieces = sorted((Polygon(p["outer"], p.get("holes", []))
                         for p in floor["walkable"]), key=lambda p: p.area, reverse=True)
        walkable = unary_union(pieces)
        if pieces:
            main = pieces[0]
            for piece in pieces[1:]:
                a, b = nearest_points(main, piece)
                report["disconnected"].append({"floor": fid, "area": round(piece.area, 3),
                    "rooms": [rid for rid, poly in rooms.items() if poly.intersection(piece).area > 0.5],
                    "gap": round(a.distance(b), 3), "near": [round((a.x+b.x)/2, 3), round((a.y+b.y)/2, 3)]})
        connected = {rid for door in floor["doors"] for rid in door.get("connects", [])}
        for room in floor["rooms"]:
            rid = room["id"]
            if rid not in connected and not any(rid != other and (poly.intersection(rooms[rid]).area > 1
                                                  or poly.boundary.intersection(rooms[rid].boundary).intersection(walkable).length > 0.5)
                                                  for other, poly in rooms.items()):
                report["roomsNoDoor"].append({"floor": fid, "id": rid, "name": room.get("name", rid)})
        for stair in floor["stairs"]:
            groups[stair.get("group")].add(fid)
        for kind, zones in (("exit", floor["exits"]), ("stair", floor["stairs"] if floor.get("level", 0) > lowest else [])):
            for zone in zones:
                poly = Polygon(zone["polygon"])
                if poly.convex_hull.area - poly.area > 1e-6:
                    report["nonConvex"].append({"floor": fid, "kind": kind, "id": zone["id"]})
        report["exits"][fid] = [e["id"] for e in floor["exits"]]
        if floor.get("level", 0) > 0:
            report["upperExits"].extend({"floor": fid, "door": e["id"]} for e in floor["exits"])
    for group, floors in groups.items():
        if len(floors) == 1:
            report["stairSingle"].append({"group": group, "floor": next(iter(floors))})
    report["ok"] = not (report["disconnected"] or report["roomsNoDoor"] or report["stairSingle"] or report["nonConvex"]) and any(report["exits"].values())
    return report


def print_report(report: dict) -> None:
    for item in report["nonConvex"]:
        print(f"WARN non-convex {item['kind']} {item['id']} on {item['floor']}: JuPedSim needs convex exit and stair zones")
    for item in report["disconnected"]:
        print(f"WARN disconnected on {item['floor']}: rooms {item['rooms']}, area {item['area']} m2, gap {item['gap']} m near {item['near']}; consider doors.add")
    for item in report["roomsNoDoor"]:
        print(f"WARN room without door {item['id']} ({item['name']}) on {item['floor']}")
    for item in report["stairSingle"]:
        print(f"WARN stair group {item['group']} only on {item['floor']}")
    for floor, exits in report["exits"].items():
        print(f"exits {floor}: {exits}")
    for item in report["upperExits"]:
        print(f"WARN upper-level exit {item['door']} on {item['floor']}: remove it with exits.remove if it is a balcony or roof door")
    if not any(report["exits"].values()):
        print("WARN no exits")
    print(f"ok: {report['ok']}")


def problems(building: dict, scenario: dict | None = None) -> list[str]:
    """List geometry, connectivity and scenario issues affecting a building."""
    import json

    found = []
    report = validate(building)
    for item in report['disconnected']:
        found.append(f"{item['floor']}: rooms {item['rooms']} cut off ({item['area']} m2, gap {item['gap']} m near {item['near']})")
    for item in report['roomsNoDoor']:
        found.append(f"{item['floor']}: room {item['id']} has no door")
    for item in report['stairSingle']:
        found.append(f"stair group {item['group']} only on {item['floor']}")
    if not any(report['exits'].values()):
        found.append('no exits')
    for key in ('name', 'credits'):
        if not str(building.get(key) or '').strip():
            found.append(f'{key} is blank')
    if 'license' not in str(building.get('credits') or '').lower():
        found.append('credits must mention a license')
    if 'umass' in json.dumps(building).lower():
        found.append('building JSON mentions umass')

    floors = building['floors']
    by_id = {f['id']: f for f in floors}
    all_rooms = {r['id'] for f in floors for r in f['rooms']}
    all_doors = {d['id'] for f in floors for d in f['doors']}
    neighbors = {f['id']: set() for f in floors}
    for i, floor in enumerate(floors):
        fid = floor['id']
        rooms = {r['id']: make_valid(Polygon(r['polygon'])) for r in floor['rooms']}
        doors = {d['id']: d for d in floor['doors']}
        walk = unary_union([Polygon(p['outer'], p.get('holes', [])) for p in floor['walkable']])
        for kind, zones in (('exit', floor['exits']), ('stair', floor['stairs'])):
            for zone in zones:
                poly = Polygon(zone['polygon'])
                label = f"{fid}: {kind} {zone['id']}"
                if poly.convex_hull.area - poly.area > 1e-6:
                    found.append(f'{label} polygon is not convex')
                if not walk.buffer(0.01).covers(poly):
                    found.append(f'{label} polygon is outside walkable')
                if kind == 'exit':
                    if any(poly.intersection(room).area > 1e-8 for room in rooms.values()):
                        found.append(f'{label} polygon overlaps a room')
                    door = doors.get(zone.get('door'))
                    if not door or 'outside' not in door.get('connects', []):
                        found.append(f"{label} has no exterior door {zone.get('door')}")
        for door in floor['doors']:
            label = f"{fid}: door {door['id']}"
            if not 0.6 <= door['width'] <= 6.0:
                found.append(f'{label} width outside 0.6-6.0 m')
            if 'outside' not in door['connects']:
                rect = Polygon(door['rect'])
                for rid in door['connects']:
                    if rid not in rooms or rect.intersection(rooms[rid]).area < 0.01:
                        found.append(f'{label} rect does not overlap room {rid} by 0.01 m2')
        for other in floors[i + 1:]:
            groups = {s.get('group') for s in floor['stairs']} - {None}
            other_groups = {s.get('group') for s in other['stairs']} - {None}
            if abs(floor.get('level', 0) - other.get('level', 0)) == 1 and groups & other_groups:
                neighbors[fid].add(other['id'])
                neighbors[other['id']].add(fid)
    reachable = {f['id'] for f in floors if f['exits']}
    pending = list(reachable)
    while pending:
        for neighbor in neighbors[pending.pop()] - reachable:
            reachable.add(neighbor)
            pending.append(neighbor)
    for floor in floors:
        if floor['id'] not in reachable:
            found.append(f"{floor['id']}: no route to an exit through consecutive stair groups")

    if scenario is not None:
        if scenario.get('buildingId') != building.get('id'):
            found.append('scenario buildingId does not match building id')
        fire = scenario.get('fire', {})
        floor = by_id.get(fire.get('floor'))
        if floor is None:
            found.append(f"scenario fire floor {fire.get('floor')} does not exist")
        else:
            room = next((r for r in floor['rooms'] if r['id'] == fire.get('room')), None)
            if room is None:
                found.append(f"{floor['id']}: scenario fire room {fire.get('room')} does not exist")
            elif not Polygon(room['polygon']).buffer(0.01).covers(Point(fire['x'], fire['y'])):
                found.append(f"{floor['id']}: scenario fire point outside room {room['id']}")
        for did in scenario.get('doors', {}):
            if did not in all_doors:
                found.append(f'scenario door {did} does not exist')
        occupants = scenario.get('occupants', {})
        per_room = occupants.get('perRoom', {})
        if not (occupants.get('total', 0) > 0 or per_room):
            found.append('scenario occupants need a positive total or perRoom rooms')
        for rid in per_room:
            if rid not in all_rooms:
                found.append(f'scenario occupants room {rid} does not exist')
    return found


def main() -> int:
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='+')
    args = parser.parse_args()
    failed = False
    for filename in args.files:
        path = Path(filename)
        building = json.loads(path.read_text(encoding='utf-8'))
        scenario_path = path.with_name(path.stem + '.scenario.json')
        scenario = json.loads(scenario_path.read_text(encoding='utf-8')) if scenario_path.exists() else None
        for issue in problems(building, scenario):
            print(f'{filename}: {issue}')
            failed = True
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
