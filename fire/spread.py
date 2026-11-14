"""Room-to-room fire spread: an illustrative ignition schedule (D25).

`FireModel` turns the schedule into closed doors and extra heat. The presets below are round numbers picked for a legible
demo: not engineering values, not validated, not for compliance.

Run `python -m fire.spread BUILDING SCENARIO [--material NAME]` to print one schedule.
"""
import argparse
from collections import OrderedDict
import heapq
import json
import math
from pathlib import Path

import shapely
from shapely.geometry import Polygon

# Seconds. flashover: a room is fully involved this long after it ignites. door / wall: the delay before a burning
# room ignites a neighbor across a door (or a stair link) / across a shared wall.
MATERIALS = {"concrete": {"flashover": 600.0, "door": 300.0, "wall": 1200.0},
             "drywall": {"flashover": 300.0, "door": 180.0, "wall": 600.0},
             "wood": {"flashover": 150.0, "door": 90.0, "wall": 240.0}}
DEFAULT_MATERIAL = "drywall"
WALL_GAP_M = 0.25   # two rooms whose polygons are at most this far apart can share a wall (an IFC wall is 0.12 m)
WALL_MIN_M = 1.0    # ... when each room's boundary runs along the other at least this far
CACHE_SIZE = 4

_CACHE = OrderedDict()


def material_name(fire: dict) -> str:
    """`fire.material`, or drywall when the key is missing. Anything but the exact names raises ValueError."""
    name = fire.get("material", DEFAULT_MATERIAL)
    if not isinstance(name, str) or name not in MATERIALS:
        raise ValueError(f"Unknown fire material {name!r}; valid names: {', '.join(MATERIALS)}")
    return name


def room_hrr_kw(peak_kw: float, flashover_s: float, tau: float) -> float:
    """Heat release of a room that ignited `tau` s ago: zero before, then peak * (tau / flashover)^2, capped at the peak."""
    if tau < 0:
        return 0.0
    ratio = min(1.0, tau / flashover_s)
    return float(peak_kw * (ratio * ratio))


def _shape(room: dict) -> Polygon:
    """The room's polygon, repaired by buffer(0); a degenerate polygon is an empty one, which links to nothing."""
    try:
        return Polygon(room["polygon"]).buffer(0)
    except (ValueError, TypeError, KeyError, shapely.errors.ShapelyError):
        return Polygon()


def _stair_rooms(floor: dict) -> dict:
    groups = {}
    for stair in floor.get("stairs", []):
        groups.setdefault(stair.get("group"), []).append(stair.get("room"))
    return groups


def _build_links(building: dict) -> dict:
    floors = building["floors"]
    links = {(floor["id"], room["id"]): {} for floor in floors for room in floor.get("rooms", [])}

    def add(a, b, kind):
        if a == b or a not in links or b not in links:
            return
        if kind == "wall" and links[a].get(b) == "door":  # a pair with both keeps the door
            return
        links[a][b] = links[b][a] = kind

    for floor in floors:
        fid = floor["id"]
        for door in floor.get("doors", []):
            connects = door.get("connects") or []
            if len(connects) == 2:  # an exterior door joins a room to "outside", which is no room
                add((fid, connects[0]), (fid, connects[1]), "door")
        rooms = floor.get("rooms", [])
        shapes = [_shape(room) for room in rooms]
        if len(shapes) < 2:
            continue
        near = shapely.STRtree(shapes).query(shapes, predicate="dwithin", distance=WALL_GAP_M)
        grown = {}

        def around(n):
            if n not in grown:
                grown[n] = shapes[n].buffer(WALL_GAP_M)
            return grown[n]

        for i, j in sorted({(int(i), int(j)) for i, j in zip(*near) if i < j}):
            along_i = shapes[i].boundary.intersection(around(j)).length
            along_j = shapes[j].boundary.intersection(around(i)).length
            if min(along_i, along_j) >= WALL_MIN_M:
                add((fid, rooms[i]["id"]), (fid, rooms[j]["id"]), "wall")
    # Stairs join each stair room of a group to the rooms of the same group one level up: the only links across floors.
    order = sorted(range(len(floors)), key=lambda i: floors[i]["level"])
    for low, high in zip(order, order[1:]):
        above = _stair_rooms(floors[high])
        for group, rooms in _stair_rooms(floors[low]).items():
            for a in rooms:
                for b in above.get(group, ()):
                    add((floors[low]["id"], a), (floors[high]["id"], b), "door")
    return links


def room_links(building: dict) -> dict:
    """{(floor id, room id): {(floor id, room id): "door" | "wall"}} for every room, symmetric, in building order.

    A door link joins the two rooms of a door that connects two rooms of its floor, and, as stair links, the stair
    rooms of one group on consecutive floors. A wall link joins two rooms of one floor that stand within WALL_GAP_M
    of each other along at least WALL_MIN_M. A pair with both keeps "door". Read-only: cached by object identity like
    fire.grid.get_graph, which retains buildings so ids are not reused; treat a building as immutable after its first lookup.
    """
    key = id(building)
    if key not in _CACHE:
        _CACHE[key] = (building, _build_links(building))
        if len(_CACHE) > CACHE_SIZE:
            _CACHE.popitem(last=False)
    _CACHE.move_to_end(key)
    return _CACHE[key][1]


def origin_room(building: dict, fire: dict) -> tuple[str, str] | None:
    """(floor id, room id) of the ignition room: `fire.room` when that room exists on `fire.floor`, else the first room
    whose polygon covers (x, y), else None."""
    floor = next((f for f in building["floors"] if f["id"] == fire.get("floor")), None)
    if floor is None:
        return None
    rooms = floor.get("rooms", [])
    named = fire.get("room")
    if named is not None and any(room["id"] == named for room in rooms):
        return floor["id"], named
    x, y = fire.get("x"), fire.get("y")
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or not (math.isfinite(x) and math.isfinite(y)):
        return None
    point = shapely.Point(x, y)
    for room in rooms:
        if _shape(room).covers(point):
            return floor["id"], room["id"]
    return None


def ignition_schedule(building: dict, scenario: dict) -> list[dict]:
    """Rooms on fire by maxTime: [{"room", "floor", "ignite"}], origin first, then by (ignite, floor, room) in building order.

    Dijkstra over `room_links` from the ignition room at `fire.start`: ignite(n) = ignite(r) + the material's delay
    for the link. Only rooms with ignite <= scenario maxTime (default 600, the sim's) are listed, except the ignition
    room, which is always first. Sprinklers keep the fire in the ignition room. No ignition room gives [].
    """
    fire = scenario["fire"]
    material = material_name(fire)
    origin = origin_room(building, fire)
    if origin is None:
        return []
    start = float(fire.get("start", 0))
    limit = scenario.get("maxTime")
    limit = 600.0 if limit is None else float(limit)

    def entry(key, delay):  # +0.0 turns a negative zero into 0.0
        return {"room": key[1], "floor": key[0], "ignite": round(start + delay, 2) + 0.0}

    if scenario.get("sprinklers"):
        return [entry(origin, 0.0)]
    links = room_links(building)
    nodes = list(links)  # building order: the heap key is (time, floor index, room index)
    rank = {key: n for n, key in enumerate(nodes)}
    delays = MATERIALS[material]
    best = {origin: 0.0}  # seconds after the start, so ties do not depend on float noise from the start time
    heap = [(0.0, rank[origin])]
    settled = []
    while heap:
        delay, n = heapq.heappop(heap)
        key = nodes[n]
        if delay > best[key]:
            continue
        settled.append((delay, n))
        for other, kind in links[key].items():
            later = delay + delays[kind]
            if later < best.get(other, math.inf) and round(start + later, 2) <= limit:
                best[other] = later
                heapq.heappush(heap, (later, rank[other]))
    settled.sort()
    return [entry(nodes[n], delay) for delay, n in settled]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("building", type=Path)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--material", help="concrete, drywall or wood (default: the scenario's fire.material, else drywall)")
    args = parser.parse_args(argv)
    building = json.loads(args.building.read_text(encoding="utf-8"))
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    if args.material is not None:
        scenario = {**scenario, "fire": {**scenario["fire"], "material": args.material}}
    try:
        material = material_name(scenario["fire"])
        entries = ignition_schedule(building, scenario)
    except ValueError as error:
        parser.error(str(error))
    names = {(f["id"], r["id"]): r.get("name") or "unnamed" for f in building["floors"] for r in f.get("rooms", [])}
    for item in entries:
        name = str(names[item["floor"], item["room"]]).encode("ascii", "replace").decode("ascii")
        print(f"{item['ignite']} s  {item['floor']} {item['room']} ({name})")
    limit = scenario.get("maxTime")
    print(f"{len(entries)} rooms by {600 if limit is None else limit:g} s ({material})")


if __name__ == "__main__":
    main()
