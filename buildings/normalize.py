"""Normalizer v0: plan/v0 -> building/v0 (spec §6, scaffold Task S2).

B owns this module and replaces or extends it. Usage (from the repo root):

    python -m buildings.normalize IN_PLAN OUT_BUILDING

How the walkable area is built (spec §6):
1. Shrink every room by wall/2 (mitre joins), so rooms drawn edge to edge get a wall.
2. Each door becomes a rectangle across the wall: the segment a-b extended
   perpendicular by wall/2 + 0.2 on each side (or the door's own `rect`).
3. A door is exterior when exactly one of `midpoint +- 0.5*normal` lies in a room.
   Exterior doors get a (width + 2) x 2 m stub outside the wall; the exit zone is
   the stub's outer 0.5 m strip (never against the wall itself).
4. walkable = union(shrunk rooms, door rects, stubs).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from shapely.geometry import Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

DOOR_REACH = 0.2   # door rect reaches this far past each wall face
STUB_EXTRA = 2.0   # stub length along the wall = door width + 2
STUB_DEPTH = 2.0   # stub depth away from the wall
EXIT_DEPTH = 0.5   # exit zone = outer strip of the stub
SIDE_PROBE = 0.5   # probe distance for the exterior-door test
NDIGITS = 3


def default_wall(source: str | None) -> float:
    """0.2 m for traced/synthetic plans, 0 for IFC (spaces already stop at walls)."""
    return 0.0 if source == "ifc" else 0.2


def shrink(poly: Polygon, wall: float):
    """Shrink a room polygon by half a wall (may return an empty or multi polygon)."""
    if wall <= 0:
        return poly
    return poly.buffer(-wall / 2, join_style="mitre")


def polygons_of(geom) -> list[Polygon]:
    """Flatten a (multi)polygon/collection into polygons with area, largest first."""
    if geom is None or geom.is_empty:
        return []
    parts = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
    polys = [p for p in parts if isinstance(p, Polygon) and p.area > 1e-9]
    return sorted(polys, key=lambda p: p.area, reverse=True)


def _num(v: float) -> float:
    return round(float(v), NDIGITS) + 0.0  # + 0.0 turns -0.0 into 0.0


def _ring(coords) -> list[list[float]]:
    pts = [[_num(x), _num(y)] for x, y in coords]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()  # rings are implicitly closed, like plan/v0 polygons
    return pts


def ring_of(poly: Polygon) -> list[list[float]]:
    """Outer ring of a polygon, counter-clockwise, rounded, not repeating the first point."""
    return _ring(orient(poly, sign=1.0).exterior.coords)


def rings_of(poly: Polygon) -> dict:
    """{outer, holes}: outer ring counter-clockwise, holes clockwise."""
    poly = orient(poly, sign=1.0)
    return {"outer": _ring(poly.exterior.coords), "holes": [_ring(h.coords) for h in poly.interiors]}


def _warn(msg: str) -> None:
    print(f"WARNING (normalize): {msg}", file=sys.stderr)


def _door_frame(door: dict):
    (ax, ay), (bx, by) = door["a"], door["b"]
    length = math.hypot(bx - ax, by - ay)
    if length < 1e-9:
        raise ValueError(f"door {door['id']}: a and b are the same point")
    u = ((bx - ax) / length, (by - ay) / length)   # along the wall
    n = (-u[1], u[0])                              # across the wall
    mid = ((ax + bx) / 2, (ay + by) / 2)
    return (ax, ay), (bx, by), u, n, mid, length


def _box_along(mid, u, o, half_len: float, d0: float, d1: float) -> Polygon:
    """Rectangle centered on `mid` along u (half length half_len), from d0 to d1 along o."""
    mx, my = mid
    pts = [
        (mx + s * half_len * u[0] + d * o[0], my + s * half_len * u[1] + d * o[1])
        for s, d in ((-1, d0), (1, d0), (1, d1), (-1, d1))
    ]
    return Polygon(pts)


def _room_at(rooms: list[tuple[str, Polygon]], x: float, y: float) -> str | None:
    p = Point(x, y)
    for rid, poly in rooms:
        if poly.covers(p):
            return rid
    return None


def _normalize_floor(floor: dict, wall: float) -> dict:
    fid = floor["id"]
    rooms_out, stairs_out, doors_out, exits_out = [], [], [], []
    room_polys: list[tuple[str, Polygon]] = []
    shrunk: dict[str, object] = {}
    pieces = []

    for room in floor["rooms"]:
        poly = Polygon(room["polygon"])
        if not poly.is_valid:
            _warn(f"{fid}/{room['id']}: invalid polygon, repairing with buffer(0)")
            poly = poly.buffer(0)
        room_polys.append((room["id"], poly))
        s = shrink(poly, wall)
        shrunk[room["id"]] = s
        if s.is_empty:
            _warn(f"{fid}/{room['id']}: room vanished after shrinking by {wall / 2} m")
        else:
            pieces.append(s)
        out = {"id": room["id"], "name": room.get("name", room["id"]), "type": room.get("type", "other"),
               "polygon": _ring(room["polygon"])}
        if room.get("group") is not None:
            out["group"] = room["group"]
        rooms_out.append(out)
        if room.get("type") == "stair":
            parts = polygons_of(s)
            if not parts:
                continue
            if room.get("group") is None:
                _warn(f"{fid}/{room['id']}: stair room without a group")
            stairs_out.append({"id": room["id"], "group": room.get("group"), "room": room["id"],
                               "polygon": ring_of(parts[0])})

    half = wall / 2
    for door in floor.get("doors", []):
        a, b, u, n, mid, length = _door_frame(door)
        h = half + DOOR_REACH
        if door.get("rect"):
            rect = Polygon(door["rect"])
        else:
            rect = Polygon([(a[0] - n[0] * h, a[1] - n[1] * h), (b[0] - n[0] * h, b[1] - n[1] * h),
                            (b[0] + n[0] * h, b[1] + n[1] * h), (a[0] + n[0] * h, a[1] + n[1] * h)])
        pieces.append(rect)

        side_neg = _room_at(room_polys, mid[0] - SIDE_PROBE * n[0], mid[1] - SIDE_PROBE * n[1])
        side_pos = _room_at(room_polys, mid[0] + SIDE_PROBE * n[0], mid[1] + SIDE_PROBE * n[1])
        out = dict(door)
        out["a"] = [_num(v) for v in door["a"]]
        out["b"] = [_num(v) for v in door["b"]]
        out["rect"] = ring_of(rect)

        if side_neg and side_pos:
            out["connects"] = [side_neg, side_pos]
        elif side_neg or side_pos:
            inside = side_neg or side_pos
            o = n if side_neg else (-n[0], -n[1])  # outward direction
            out["connects"] = [inside, "outside"]
            half_len = (door.get("width") or length) / 2 + STUB_EXTRA / 2
            stub = _box_along(mid, u, o, half_len, half, half + STUB_DEPTH)
            exit_zone = _box_along(mid, u, o, half_len, half + STUB_DEPTH - EXIT_DEPTH, half + STUB_DEPTH)
            pieces.append(stub)
            exits_out.append({"id": door["id"], "name": door.get("name") or door["id"], "door": door["id"],
                              "polygon": ring_of(exit_zone)})
        else:
            _warn(f"{fid}/{door['id']}: no room on either side of the door")
            out["connects"] = ["outside", "outside"]
        doors_out.append(out)

    walk_polys = polygons_of(unary_union(pieces))
    if not walk_polys:
        _warn(f"{fid}: empty walkable area")
    elif len(walk_polys) > 1:
        _warn(f"{fid}: walkable area has {len(walk_polys)} disconnected pieces "
              f"(areas {[round(p.area, 1) for p in walk_polys]})")
        main = walk_polys[0]
        for rid, s in shrunk.items():
            if not s.is_empty and main.intersection(s).area < 1e-6:
                _warn(f"{fid}/{rid}: room is not connected to the main walkable area")

    return {
        "id": fid,
        "level": floor.get("level", 0),
        "elevation": floor.get("elevation", 0.0),
        "height": floor.get("height", 3.0),
        "walkable": [rings_of(p) for p in walk_polys],
        "rooms": rooms_out,
        "doors": doors_out,
        "stairs": stairs_out,
        "exits": exits_out,
    }


def plan_to_building(plan: dict, wall: float | None = None) -> dict:
    """plan/v0 dict -> building/v0 dict."""
    if wall is None:
        wall = default_wall(plan.get("source"))
    return {
        "version": "building/v0",
        "id": plan["id"],
        "name": plan.get("name", plan["id"]),
        "source": plan.get("source", "synthetic"),
        "credits": plan.get("credits", ""),
        "floors": [_normalize_floor(f, wall) for f in plan["floors"]],
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m buildings.normalize IN_PLAN OUT_BUILDING", file=sys.stderr)
        return 2
    plan = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    building = plan_to_building(plan)
    out = Path(argv[1])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(building, indent=1), encoding="utf-8")
    for f in building["floors"]:
        area = sum(Polygon(w["outer"], w["holes"]).area for w in f["walkable"])
        print(f"{f['id']}: walkable {area:.1f} m2 in {len(f['walkable'])} piece(s), "
              f"{len(f['doors'])} doors, exits {[e['id'] for e in f['exits']]}, "
              f"stairs {[s['id'] for s in f['stairs']]}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
