"""Summarize connectivity and exit issues in a normalized building."""
from collections import defaultdict

from shapely import make_valid
from shapely.geometry import Polygon
from shapely.ops import nearest_points


def validate(building: dict) -> dict:
    report = {"disconnected": [], "roomsNoDoor": [], "stairSingle": [],
              "exits": {}, "upperExits": []}
    groups = defaultdict(set)
    for floor in building["floors"]:
        fid = floor["id"]
        rooms = {r["id"]: make_valid(Polygon(r["polygon"])) for r in floor["rooms"]}
        pieces = sorted((Polygon(p["outer"], p.get("holes", []))
                         for p in floor["walkable"]), key=lambda p: p.area, reverse=True)
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
            if rid not in connected and not any(rid != other and poly.intersection(rooms[rid]).area > 1
                                                  for other, poly in rooms.items()):
                report["roomsNoDoor"].append({"floor": fid, "id": rid, "name": room.get("name", rid)})
        for stair in floor["stairs"]:
            groups[stair.get("group")].add(fid)
        report["exits"][fid] = [e["id"] for e in floor["exits"]]
        if floor.get("level", 0) > 0:
            report["upperExits"].extend({"floor": fid, "door": e["id"]} for e in floor["exits"])
    for group, floors in groups.items():
        if len(floors) == 1:
            report["stairSingle"].append({"group": group, "floor": next(iter(floors))})
    report["ok"] = not (report["disconnected"] or report["roomsNoDoor"] or report["stairSingle"]) and any(report["exits"].values())
    return report


def print_report(report: dict) -> None:
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
