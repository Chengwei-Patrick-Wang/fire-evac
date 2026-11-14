"""Extract IFC spaces into a plan/v0 with metre-scale room polygons."""
import argparse
from collections import Counter
import json
import logging
from pathlib import Path
import re

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.util.unit
import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import split, unary_union

from buildings.inspect_ifc import storey_of

LOG = logging.getLogger(__name__)
SETTINGS = ifcopenshell.geom.settings()
SETTINGS.set("use-world-coords", True)


def footprint(element):
    """Union the non-degenerate XY projections of an element's triangles."""
    try:
        shape = ifcopenshell.geom.create_shape(SETTINGS, element)
        verts = np.asarray(shape.geometry.verts).reshape(-1, 3)
        faces = np.asarray(shape.geometry.faces).reshape(-1, 3)
        triangles = []
        for face in faces:
            tri = Polygon(verts[face, :2])
            if tri.area >= 1e-9:
                tri = shapely.set_precision(tri, 0.001)
                if not tri.is_empty:
                    triangles.append(tri)
        result = unary_union(triangles)
        if result.is_empty:
            raise ValueError("empty footprint")
        return result
    except Exception as exc:
        LOG.warning("Could not extract footprint for %s: %s", element, exc)
        return None


def _parts(geometry):
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [p for g in getattr(geometry, "geoms", []) for p in _parts(g)]


def _simple_parts(geometry):
    pending = _parts(geometry)
    result = []
    while pending:
        poly = pending.pop()
        if not poly.interiors:
            result.append(poly)
            continue
        hole = Polygon(poly.interiors[0])
        minx, _, maxx, _ = poly.bounds
        line = LineString([(minx - 1, hole.centroid.y), (maxx + 1, hole.centroid.y)])
        pieces = _parts(split(poly, line))
        if len(pieces) < 2:
            raise ValueError("Could not split room footprint around hole")
        pending.extend(pieces)
    return sorted(result, key=lambda p: (p.bounds, p.area))


_TYPES = [
    ("stair", "stair"), ("restroom", "toilet restroom wc lavatory bath rr"),
    ("kitchen", "kitchen"), ("dining", "dining cafeteria cafe"),
    ("classroom", "classroom class lecture training"), ("lab", "lab"),
    ("bedroom", "bedroom sleep dorm"),
    ("storage", "storage store closet janitor mech electrical utility shaft riser jan sto stor elec mechanical comm trash soil lin"),
    ("lobby", "lobby vestibule entry foyer reception vest recept"),
    ("corridor", "corridor hallway hall circulation passage"),
    ("lounge", "lounge waiting wait break"), ("office", "office conference meeting exam conf ofcr"),
]


def _room_type(name):
    words = set(re.findall(r"[a-z]+", name.lower()))
    for kind, terms in _TYPES:
        if any(term in words or term + "s" in words for term in terms.split()):
            return kind
    return "other"


def _suffix(index):
    result = ""
    while True:
        result = chr(97 + index % 26) + result
        index = index // 26 - 1
        if index < 0:
            return result


def group_stairs(floors):
    """Greedily match overlapping stair rooms on adjacent floors."""
    stairs = [[r for r in floor["rooms"] if r["type"] == "stair"] for floor in floors]
    parents = {id(r): id(r) for rooms in stairs for r in rooms}

    def root(key):
        while parents[key] != key:
            key = parents[key]
        return key

    for lower, upper in zip(stairs, stairs[1:]):
        candidates = []
        for a in lower:
            pa = Polygon(a["polygon"])
            for b in upper:
                pb = Polygon(b["polygon"])
                overlap = pa.intersection(pb).area
                if overlap >= 0.3 * min(pa.area, pb.area) and overlap > 0:
                    candidates.append((overlap, a, b))
        used_a, used_b = set(), set()
        for _, a, b in sorted(candidates, key=lambda item: (-item[0], item[1]["id"], item[2]["id"])):
            if id(a) not in used_a and id(b) not in used_b:
                parents[root(id(b))] = root(id(a))
                used_a.add(id(a))
                used_b.add(id(b))
    groups = {}
    for level, rooms in enumerate(stairs):
        for room in rooms:
            key = root(id(room))
            centroid = Polygon(room["polygon"]).centroid
            groups.setdefault(key, []).append((level, centroid.x, centroid.y, room))
    ordered = sorted(groups.values(), key=lambda group: min((level, x, y) for level, x, y, _ in group))
    for i, group in enumerate(ordered, 1):
        for _, _, _, room in group:
            room["group"] = f"S{i}"


def _door(element, scale):
    geom = footprint(element)
    if geom is None:
        return None
    rect = geom.minimum_rotated_rectangle
    if rect.geom_type != "Polygon":
        LOG.warning("Degenerate door footprint for %s", element)
        return None
    coords = list(rect.exterior.coords)[:4]
    edges = [(np.array(coords[(i + 1) % 4]) - np.array(coords[i])) for i in range(4)]
    edge = max(edges, key=np.linalg.norm)
    length = float(np.linalg.norm(edge))
    depth = min(float(np.linalg.norm(e)) for e in edges) + 0.3
    u = edge / length
    n = np.array([-u[1], u[0]])
    center = np.array([rect.centroid.x, rect.centroid.y])
    given = getattr(element, "OverallWidth", None)
    width = given * scale if given is not None and 0.5 <= given * scale <= 4 else length
    a, b = center - u * width / 2, center + u * width / 2
    ring = [center + su * u * width / 2 + sn * n * depth / 2
            for su, sn in [(-1, -1), (1, -1), (1, 1), (-1, 1)]]
    rating = ifcopenshell.util.element.get_psets(element).get("Pset_DoorCommon", {}).get("FireRating")
    fire = bool(rating and str(rating).strip())
    return {"id": "D" + element.GlobalId[-6:], "name": element.Name or "",
            "a": a.tolist(), "b": b.tolist(), "width": round(width, 2),
            "rect": [p.tolist() for p in ring], "fireDoor": fire,
            "state": "closed" if fire else "open"}


def extract(path, *, id=None, name=None, credits=None):
    path = Path(path)
    model = ifcopenshell.open(str(path))
    scale = ifcopenshell.util.unit.calculate_unit_scale(model)
    storeys = model.by_type("IfcBuildingStorey")
    spaces = {s.id(): [] for s in storeys}
    for space in model.by_type("IfcSpace"):
        storey = storey_of(space)
        if storey is not None and storey.id() in spaces:
            spaces[storey.id()].append(space)
    # Cache shapes for missing elevations and reuse them when creating rooms.
    shapes = {}
    def shape(space):
        if space.id() not in shapes:
            shapes[space.id()] = footprint(space)
        return shapes[space.id()]
    def elevation(storey):
        if storey.Elevation is not None:
            return storey.Elevation * scale
        heights = []
        for space in spaces[storey.id()]:
            try:
                geometry = ifcopenshell.geom.create_shape(SETTINGS, space).geometry
                heights.append(float(np.asarray(geometry.verts).reshape(-1, 3)[:, 2].min()))
            except Exception as exc:
                LOG.warning("Could not determine elevation of %s: %s", space, exc)
        if not heights:
            raise ValueError(f"Cannot determine elevation of storey {storey.Name or storey.id()}")
        return min(heights)
    # Empty storeys with no elevation cannot affect the ordering of occupied storeys.
    ordered = sorted((s for s in storeys if s.Elevation is not None or spaces[s.id()]),
                     key=lambda s: (elevation(s), s.Name or "", s.id()))
    occupied = [i for i, s in enumerate(ordered) if spaces[s.id()]]
    if not occupied:
        raise ValueError("No storeys with spaces")
    for index in range(occupied[0], occupied[-1] + 1):
        if not spaces[ordered[index].id()]:
            raise ValueError(f"Storey {ordered[index].Name or ordered[index].id()} has no spaces between occupied storeys")
    kept = [ordered[i] for i in occupied]
    elevations = [elevation(s) for s in kept]
    all_spaces = [space for storey in kept for space in spaces[storey.id()]]
    sanitized = {s.id(): re.sub(r"[^A-Za-z0-9_-]", "", s.Name or "") for s in all_spaces}
    counts = Counter(sanitized.values())
    floors = []
    for i, storey in enumerate(kept):
        height = (elevations[i + 1] - elevations[i] if i + 1 < len(kept)
                  else elevations[i] - elevations[i - 1] if i else 3.5)
        floor = {"id": f"F{i + 1}", "level": i, "elevation": round(elevations[i] - elevations[0], 3),
                 "height": round(height, 3), "rooms": [], "doors": []}
        for space in sorted(spaces[storey.id()], key=lambda s: (s.Name or "", s.GlobalId)):
            if getattr(space, "PredefinedType", None) == "EXTERNAL":
                continue
            geom = shape(space)
            if geom is None or geom.area < 1:
                continue
            parts = _simple_parts(geom)
            base = sanitized[space.id()]
            base = "R" + (base if base and counts[base] == 1 else space.GlobalId[-6:])
            room_name = space.LongName or space.Name or f"Space {len(floor['rooms']) + 1}"
            for j, poly in enumerate(parts):
                ring = list(orient(poly, sign=1).exterior.coords)[:-1]
                floor["rooms"].append({"id": base + (_suffix(j) if len(parts) > 1 else ""),
                                       "name": room_name, "type": _room_type(room_name),
                                       "polygon": [[x, y] for x, y in ring]})
        floors.append(floor)
    floor_index = {storey.id(): i for i, storey in enumerate(kept)}
    for door in model.by_type("IfcDoor"):
        storey = storey_of(door)
        if storey is not None and storey.id() in floor_index:
            result = _door(door, scale)
            if result is not None:
                floors[floor_index[storey.id()]]["doors"].append(result)

    def has_stair_parent(element):
        parent = ifcopenshell.util.element.get_aggregate(element)
        while parent is not None:
            if parent.is_a("IfcStair"):
                return True
            parent = ifcopenshell.util.element.get_aggregate(parent)
        return False

    stairs = list(model.by_type("IfcStair")) + [flight for flight in model.by_type("IfcStairFlight")
                                                   if not has_stair_parent(flight)]
    for stair in stairs:
        storey = storey_of(stair)
        if storey is None or storey.id() not in floor_index:
            continue
        shapes = [footprint(part) for part in [stair, *ifcopenshell.util.element.get_decomposition(stair)]]
        geom = unary_union([part for part in shapes if part is not None])
        if geom.area < 2:
            continue
        for i in (floor_index[storey.id()], floor_index[storey.id()] + 1):
            if i >= len(floors):
                continue
            rooms = floors[i]["rooms"]
            if any(Polygon(r["polygon"]).intersection(geom).area >= 0.3 * geom.area
                   for r in rooms if r["type"] == "stair"):
                continue
            buffered = geom.buffer(0.3, join_style="mitre")
            poly = max(_parts(buffered), key=lambda p: p.area)
            rooms.append({"id": "S" + stair.GlobalId[-6:] + ("_upper" if i != floor_index[storey.id()] else ""),
                          "name": "Stair", "type": "stair",
                          "polygon": [list(p) for p in list(orient(poly, sign=1).exterior.coords)[:-1]]})
    points = [p for f in floors for room in f["rooms"] for p in room["polygon"]]
    if not points:
        raise ValueError("No usable room footprints")
    minx = min(p[0] for p in points)
    miny = min(p[1] for p in points)
    for p in points:
        p[0], p[1] = round(p[0] - minx, 3), round(p[1] - miny, 3)
    for floor in floors:
        for door in floor["doors"]:
            for p in [door["a"], door["b"], *door["rect"]]:
                p[0], p[1] = round(p[0] - minx, 3), round(p[1] - miny, 3)
            if any(Polygon(door["rect"]).intersects(Polygon(room["polygon"]))
                   for room in floor["rooms"] if room["type"] == "stair"):
                door["fireDoor"], door["state"] = True, "closed"
    group_stairs(floors)
    project = model.by_type("IfcProject")
    return {"version": "plan/v0", "id": id or re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-"),
            "name": name or (project[0].Name if project and project[0].Name else path.stem),
            "source": "ifc", "credits": credits or f"IFC model {path.name}; license: see buildings/README.md",
            "floors": floors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--id")
    parser.add_argument("--name")
    parser.add_argument("--credits")
    args = parser.parse_args()
    plan = extract(args.input, id=args.id, name=args.name, credits=args.credits)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    for floor in plan["floors"]:
        area = sum(Polygon(room["polygon"]).area for room in floor["rooms"])
        print(f"{floor['id']}: {len(floor['rooms'])} rooms, {area:.1f} m2")


if __name__ == "__main__":
    main()
