"""Clean AI-proposed room polygons on a floor-meter grid."""
from __future__ import annotations
import argparse
import copy
import json
import math
from pathlib import Path
import shapely
from shapely.affinity import rotate
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient


def _largest(geometry):
    if geometry.is_empty:
        return None
    if geometry.geom_type == "Polygon":
        return geometry
    parts = [p for g in getattr(geometry, "geoms", []) if (p := _largest(g)) is not None]
    return max(parts, key=lambda p: p.area, default=None)


def _snap(poly, grid):
    poly = _largest(shapely.set_precision(poly, grid))
    return None if poly is None else shapely.set_precision(poly, 0.0).simplify(0)


def _usable(poly, min_area, min_width):
    return poly is not None and poly.area >= min_area and not poly.buffer(-min_width / 2, join_style="mitre").is_empty


def _ring(poly):
    coords = list(orient(poly, sign=1).exterior.coords)[:-1]
    start = min(range(len(coords)), key=lambda i: (coords[i][1], coords[i][0]))
    return [[float(x), float(y)] for x, y in coords[start:] + coords[:start]]


def tidy_floor(floor: dict, grid: float = 0.25, min_area: float = 1.0,
               min_width: float = 0.6) -> tuple[dict, list[str]]:
    result = copy.deepcopy(floor)
    notes = []
    rooms = []
    for room in sorted(result.get("rooms", []), key=lambda r: str(r.get("id", ""))):
        rid = room.get("id", "?")
        try:
            points = room["polygon"]
            if len(points) < 3:
                raise ValueError("fewer than three points")
            poly = _largest(shapely.make_valid(Polygon(points)))
            if poly is None or poly.area <= 0:
                raise ValueError("empty polygon")
            rect = poly.minimum_rotated_rectangle
            if rect.area and poly.area / rect.area >= 0.9:
                coords = list(rect.exterior.coords)
                dx, dy = coords[1][0] - coords[0][0], coords[1][1] - coords[0][1]
                angle = math.degrees(math.atan2(dy, dx))
                offset = (angle + 45) % 90 - 45
                if abs(offset) <= 10:
                    rect = rotate(rect, -offset, origin="centroid")
                if poly.symmetric_difference(rect).area > 0.01:
                    notes.append(f"{rid}: squared")
                poly = rect
            poly = _snap(poly, grid)
            if not _usable(poly, min_area, min_width):
                notes.append(f"{rid}: dropped (too small or narrow)")
                continue
            rooms.append([room, poly])
        except (ValueError, TypeError, KeyError, IndexError, shapely.errors.GEOSException, OverflowError):
            notes.append(f"{rid}: dropped (invalid polygon)")

    for _ in range(3):
        changed = False
        rooms.sort(key=lambda item: (-item[1].area, str(item[0].get("id", ""))))
        i = 0
        while i < len(rooms):
            j = i + 1
            while j < len(rooms):
                big, small = rooms[i], rooms[j]
                overlap = big[1].intersection(small[1]).area
                if overlap <= 0.01:
                    j += 1
                    continue
                changed = True
                if overlap >= small[1].area / 2:
                    percent = round(100 * overlap / small[1].area)
                    big[1] = _snap(big[1].union(small[1]), grid)
                    notes.append(f"{small[0].get('id', '?')}: merged into {big[0].get('id', '?')} ({percent}% overlap)")
                    rooms.pop(j)
                else:
                    trimmed = _snap(small[1].difference(big[1]), grid)
                    if _usable(trimmed, min_area, min_width):
                        small[1] = trimmed
                        notes.append(f"{small[0].get('id', '?')}: trimmed against {big[0].get('id', '?')}")
                        j += 1
                    else:
                        notes.append(f"{small[0].get('id', '?')}: dropped after trimming")
                        rooms.pop(j)
            i += 1
        if not changed:
            break
    result["rooms"] = []
    for room, poly in sorted(rooms, key=lambda item: str(item[0].get("id", ""))):
        room["polygon"] = _ring(poly)
        result["rooms"].append(room)
    return result, notes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    if "floors" in data:
        floors = []
        for floor in data["floors"]:
            cleaned, notes = tidy_floor(floor)
            floors.append(cleaned)
            for note in notes:
                print(f"{floor.get('id', '?')}/{note}")
        data["floors"] = floors
    else:
        data, notes = tidy_floor(data)
        for note in notes:
            print(note)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
