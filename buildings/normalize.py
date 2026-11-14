"""Normalizer v0: plan/v0 -> building/v0 (spec §6, scaffold Task S2).

B owns this module and replaces or extends it. Usage (from the repo root):

    python -m buildings.normalize IN_PLAN OUT_BUILDING

How the walkable area is built (spec §6):
1. Shrink every room by wall/2 (mitre joins), so rooms drawn edge to edge get a wall.
2. Each door becomes a rectangle across the wall: the segment a-b extended
   perpendicular by wall/2 + 0.2 on each side (or the door's own `rect`).
3. Rays normal to each door identify its adjacent rooms. A door with one
   adjacent room may be exterior; IFC doors also pass an envelope check.
   Exterior doors get a (width + 2) x 2 m stub outside the wall; the exit zone is
   the stub's outer 0.5 m strip (never against the wall itself).
4. walkable = union(shrunk rooms, door rects, stubs).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from shapely import make_valid
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

DOOR_REACH = 0.2   # door rect reaches this far past each wall face
STUB_EXTRA = 2.0   # stub length along the wall = door width + 2
STUB_DEPTH = 2.0   # stub depth away from the wall
EXIT_DEPTH = 0.5   # exit zone = outer strip of the stub
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


def largest_inner_rect(poly: Polygon) -> Polygon | None:
    corners = list(poly.minimum_rotated_rectangle.exterior.coords)
    a, b = max(zip(corners, corners[1:]), key=lambda pair: math.dist(*pair))
    angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    rotated = affinity.rotate(poly, -angle, origin=poly.centroid)
    xs = sorted({round(x, 3) for x, _ in rotated.exterior.coords})
    ys = sorted({round(y, 3) for _, y in rotated.exterior.coords})
    covered = rotated.buffer(0.005)
    best = None
    for i, x0 in enumerate(xs):
        for x1 in xs[i + 1:]:
            for j, y0 in enumerate(ys):
                for y1 in ys[j + 1:]:
                    if best is not None and (x1-x0)*(y1-y0) <= best.area:
                        continue
                    candidate = box(x0, y0, x1, y1)
                    if covered.covers(candidate):
                        best = candidate
    return affinity.rotate(best, angle, origin=poly.centroid) if best is not None else None


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


def _side_rooms(rooms, mid, normal, sign):
    start = Point(mid[0] + sign * 0.05 * normal[0], mid[1] + sign * 0.05 * normal[1])
    end = (mid[0] + sign * 2 * normal[0], mid[1] + sign * 2 * normal[1])
    ray = LineString([start, end])
    return [rid for _, rid in sorted((start.distance(poly.intersection(ray)), rid)
                                      for rid, poly in rooms if poly.intersects(ray))]


def door_openings(floor: dict) -> dict:
    """Measure walkable length along each door's centre line."""
    walk = unary_union([Polygon(p["outer"], p.get("holes", [])) for p in floor["walkable"]])
    result = {}
    for door in floor["doors"]:
        _, _, u, _, _, _ = _door_frame(door)
        rect = Polygon(door["rect"])
        center = rect.centroid
        projections = [x*u[0] + y*u[1] for x, y in rect.exterior.coords]
        half = (max(projections) - min(projections))/2 + 0.5
        line = LineString([(center.x - half*u[0], center.y - half*u[1]),
                           (center.x + half*u[0], center.y + half*u[1])])
        result[door["id"]] = walk.intersection(line).length
    return result


def _normalize_floor(floor: dict, wall: float, source: str, exit_add: set, exit_remove: set,
                     max_vertices: int | None = None) -> dict:
    fid = floor["id"]
    rooms_out, stairs_out, doors_out, exits_out = [], [], [], []
    room_polys: list[tuple[str, Polygon]] = []
    shrunk: dict[str, object] = {}
    pieces = []

    for room in floor["rooms"]:
        poly = Polygon(room["polygon"])
        if not poly.is_valid:
            _warn(f"{fid}/{room['id']}: invalid polygon, repairing")
            poly = make_valid(poly)
        room_polys.append((room["id"], poly))
        s = shrink(poly, wall)
        shrunk[room["id"]] = s
        if s.is_empty:
            _warn(f"{fid}/{room['id']}: room vanished after shrinking by {wall / 2} m")
            s = poly
            shrunk[room["id"]] = s
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
            zone = parts[0]
            if zone.convex_hull.area - zone.area > 1e-6:
                zone = largest_inner_rect(zone)
                if zone is None:
                    _warn(f"{fid}/{room['id']}: no inner stair rectangle")
                    continue
                if zone.area < 0.7 * parts[0].area:
                    _warn(f"{fid}/{room['id']}: stair zone keeps under 70% of room")
            stairs_out.append({"id": room["id"], "group": room.get("group"), "room": room["id"],
                               "polygon": ring_of(zone)})

    half = wall / 2
    room_union = unary_union([p for _, p in room_polys])
    envelope = room_union.buffer(1.5).buffer(-1.5)
    for door in floor.get("doors", []):
        a, b, u, n, mid, length = _door_frame(door)
        h = half + DOOR_REACH
        if door.get("rect"):
            rect = Polygon(door["rect"])
        else:
            rect = Polygon([(a[0] - n[0] * h, a[1] - n[1] * h), (b[0] - n[0] * h, b[1] - n[1] * h),
                            (b[0] + n[0] * h, b[1] + n[1] * h), (a[0] + n[0] * h, a[1] + n[1] * h)])
        neg = _side_rooms(room_polys, mid, n, -1)
        pos = _side_rooms(room_polys, mid, n, 1)
        side_neg = neg[0] if neg else None
        side_pos = pos[0] if pos else None
        if side_neg and side_neg == side_pos:
            other_pos = next((rid for rid in pos if rid != side_neg), None)
            other_neg = next((rid for rid in neg if rid != side_pos), None)
            if other_pos:
                side_pos = other_pos
            elif other_neg:
                side_neg = other_neg
            else:
                side_pos = None
        if not side_neg and not side_pos:
            _warn(f"{fid}/{door['id']}: no room on either side of the door")
            continue
        forced = door["id"] in exit_add
        if forced and side_neg and side_pos:
            centroid = room_union.centroid
            dot = (centroid.x - mid[0]) * n[0] + (centroid.y - mid[1]) * n[1]
            if dot >= 0:
                side_neg = None
            else:
                side_pos = None
        # Preserve the supplied rectangle's centre and width, growing only its depth.
        coords = list(rect.exterior.coords)[:-1]
        along = [x*u[0] + y*u[1] for x, y in coords]
        across = [x*n[0] + y*n[1] for x, y in coords]
        center = rect.centroid
        rect_mid = (center.x, center.y)
        rect_length = max(along) - min(along)
        depth = max(across) - min(across)
        connected = [rid for rid in (side_neg, side_pos) if rid]
        grown = 0.0
        for step in range(11):
            grown = step * 0.1
            candidate = _box_along(rect_mid, u, n, rect_length / 2, -(depth + grown)/2, (depth + grown)/2)
            if all(candidate.intersection(shrunk[rid]).area >= 0.010001 for rid in connected):
                break
        rect = candidate
        missed = next ( (rid for rid in connected if rect.intersection(shrunk[rid]).area < 0.010001), None)
        if missed:
            _warn(f"{fid}/{door['id']}: rect does not reach {missed}; dropped")
            continue
        if grown > 0.3 + 1e-8:
            _warn(f"{fid}/{door['id']}: door rect grew {grown:.1f} m")
        pieces.append(rect)
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
            if door["id"] in exit_remove:
                doors_out.append(out)
                continue
            if not forced and source == "ifc" and envelope.covers(Point(mid[0] + o[0], mid[1] + o[1])):
                _warn(f"door {door['id']} faces an unmodeled space")
                doors_out.append(out)
                continue
            half_len = (door.get("width") or length) / 2 + STUB_EXTRA / 2
            stub = _box_along(mid, u, o, half_len, half, half + STUB_DEPTH)
            exit_zone = _box_along(mid, u, o, half_len, half + STUB_DEPTH - EXIT_DEPTH, half + STUB_DEPTH)
            clipped_stub = stub.difference(room_union)
            exit_zone = exit_zone.difference(room_union)
            if clipped_stub.area < 0.6 * stub.area:
                _warn(f"{fid}/{door['id']}: less than 60% of exit stub remains")
            pieces.append(clipped_stub)
            for part in polygons_of(exit_zone):
                exits_out.append({"id": door["id"], "name": door.get("name") or door["id"], "door": door["id"],
                                  "polygon": ring_of(part)})
        doors_out.append(out)

    cleaned = unary_union(pieces).buffer(0.02).buffer(-0.02).simplify(0.02, preserve_topology=True)
    walk_polys = []
    for p in polygons_of(cleaned):
        if p.area < 1.0:
            _warn(f"{fid}: dropped walkable piece under 1 m2")
            continue
        holes = [h for h in p.interiors if Polygon(h).area >= 0.3]
        if len(holes) != len(p.interiors):
            _warn(f"{fid}: dropped walkable holes under 0.3 m2")
        walk_polys.append(Polygon(p.exterior, holes))
    if not walk_polys:
        _warn(f"{fid}: empty walkable area")
    elif len(walk_polys) > 1:
        _warn(f"{fid}: walkable area has {len(walk_polys)} disconnected pieces "
              f"(areas {[round(p.area, 1) for p in walk_polys]})")
        main = walk_polys[0]
        for rid, s in shrunk.items():
            if not s.is_empty and main.intersection(s).area < 1e-6:
                _warn(f"{fid}/{rid}: room is not connected to the main walkable area")

    if source == "ifc" and walk_polys:
        center = unary_union(walk_polys).centroid
        names = {}
        rooms_by_id = {r["id"]: r for r in rooms_out}
        doors_by_id = {d["id"]: d for d in doors_out}
        for exit in exits_out:
            centroid = Polygon(exit["polygon"]).centroid
            dx, dy = centroid.x-center.x, centroid.y-center.y
            side = ("east" if dx > 0 else "west") if abs(dx) > abs(dy) else ("north" if dy > 0 else "south")
            inside = next(r for r in doors_by_id[exit["door"]]["connects"] if r != "outside")
            room = rooms_by_id[inside]
            label = f"Stair {room['group']}" if room.get("type") == "stair" and room.get("group") else room["name"].title()
            base = f"{label} ({side})"
            names[base] = names.get(base, 0) + 1
            exit["name"] = base + (f" {names[base]}" if names[base] > 1 else "")

    result = {
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
    if max_vertices is not None:
        from buildings.summary import vertex_count
        initial = vertex_count(result)
        if initial > max_vertices:
            base_walk = unary_union(walk_polys)
            base_openings = door_openings(result)
            base_shape = (len(walk_polys), sum(len(p.interiors) for p in walk_polys))
            guards = [Polygon(d["rect"]) if d.get("rect") else
                      LineString([d["a"], d["b"]]).buffer(0.5) for d in floor.get("doors", [])]
            door_guard = unary_union(guards).buffer(0.2) if guards else Polygon()
            originals = list(shrunk.values())
            other_pieces = pieces[len(originals):]
            best_count = initial
            accepted_closing = 0.0
            accepted_simplify = 0.02
            closed_pieces = originals
            for closing, tolerance in ((0.1, 0.02), (0.25, 0.02), (0.25, 0.03), (0.25, 0.05)):
                if tolerance == 0.02:
                    closed_pieces = []
                    for i, room in enumerate(originals):
                        closed = room.buffer(closing, join_style="mitre").buffer(-closing, join_style="mitre")
                        added = closed.difference(room)
                        others = originals[:i] + originals[i+1:]
                        if (added.area <= 0.03 * room.area and
                            (added.is_empty or (not added.intersects(door_guard) and
                             all(added.distance(other) >= 0.05 for other in others)))):
                            closed_pieces.append(closed)
                        else:
                            closed_pieces.append(room)
                geom = unary_union(closed_pieces + other_pieces).buffer(0.02).buffer(-0.02).simplify(tolerance, preserve_topology=True)
                candidates = [Polygon(p.exterior, [h for h in p.interiors if Polygon(h).area >= 0.3])
                              for p in polygons_of(geom) if p.area >= 1.0]
                candidate = dict(result, walkable=[rings_of(p) for p in candidates])
                walk = unary_union([Polygon(p["outer"], p["holes"]) for p in candidate["walkable"]])
                shape = (len(candidates), sum(len(p.interiors) for p in candidates))
                openings = door_openings(candidate)
                safe = (shape == base_shape and base_walk.area > 0 and
                        abs(walk.area - base_walk.area) / base_walk.area < 0.01 and
                        all(abs(openings[k] - v) <= 0.02 for k, v in base_openings.items()) and
                        all(Polygon(z["polygon"]).difference(walk.buffer(0.01)).area < 1e-8
                            for z in result["exits"] + result["stairs"]))
                count = vertex_count(candidate)
                if safe and count < best_count:
                    result = candidate
                    best_count = count
                    accepted_closing, accepted_simplify = closing, tolerance
                if best_count <= max_vertices:
                    break
            print(f"vertices {fid}: {initial} -> {best_count} (budget {max_vertices}, closing {accepted_closing:.2f} m, simplify {accepted_simplify:.2f} m)", file=sys.stderr)
            if best_count > max_vertices:
                _warn(f"{fid}: budget not met (door jambs and room corners)")
    return result


def plan_to_building(plan: dict, wall: float | None = None, overrides: dict | None = None,
                     max_vertices: int | None = None) -> dict:
    """plan/v0 dict -> building/v0 dict."""
    from buildings.fixups import apply_overrides
    overrides = overrides or {}
    plan = apply_overrides(plan, overrides)
    exit_add = set(overrides.get("exits", {}).get("add", []))
    exit_remove = set(overrides.get("exits", {}).get("remove", []))
    door_ids = {d["id"] for f in plan["floors"] for d in f.get("doors", [])}
    for door_id in exit_add | exit_remove:
        if door_id not in door_ids:
            raise ValueError(f"unknown door {door_id}")
    if exit_add & exit_remove:
        raise ValueError(f"door in both exits.add and exits.remove: {sorted(exit_add & exit_remove)}")
    if wall is None:
        wall = default_wall(plan.get("source"))
    return {
        "version": "building/v0",
        "id": plan["id"],
        "name": plan.get("name", plan["id"]),
        "source": plan.get("source", "synthetic"),
        "credits": plan.get("credits", ""),
        "floors": [_normalize_floor(f, wall, plan.get("source", "synthetic"), exit_add, exit_remove, max_vertices) for f in plan["floors"]],
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Normalize a plan into a building")
    parser.add_argument("plan")
    parser.add_argument("output")
    parser.add_argument("--wall", type=float)
    parser.add_argument("--overrides")
    parser.add_argument("--max-vertices", type=int)
    args = parser.parse_args(argv)
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    from buildings.fixups import load_overrides
    from buildings.validate import validate, print_report
    override_path = Path(args.overrides) if args.overrides else Path("buildings/overrides") / (plan["id"] + ".json")
    overrides = load_overrides(override_path) if args.overrides or override_path.exists() else None
    building = plan_to_building(plan, wall=args.wall, overrides=overrides, max_vertices=args.max_vertices)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(building, indent=1), encoding="utf-8")
    for f in building["floors"]:
        area = sum(Polygon(w["outer"], w["holes"]).area for w in f["walkable"])
        print(f"{f['id']}: walkable {area:.1f} m2 in {len(f['walkable'])} piece(s), "
              f"{len(f['doors'])} doors, exits {[e['id'] for e in f['exits']]}, "
              f"stairs {[s['id'] for s in f['stairs']]}")
    print(f"wrote {out}")
    print_report(validate(building))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
