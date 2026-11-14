"""Create a reproducible fire scenario for a normalized building."""
import argparse
import json
from pathlib import Path

from shapely.geometry import Polygon


def make_scenario(building: dict, total: int = 120) -> dict:
    floor = min(building["floors"], key=lambda f: (f["level"], f["elevation"]))
    rooms = [r for r in floor["rooms"] if r["type"] not in ("corridor", "stair")]
    if not rooms:
        raise ValueError(f"no suitable fire room on {floor['id']}")
    room = max(rooms, key=lambda r: Polygon(r["polygon"]).area)
    point = Polygon(room["polygon"]).representative_point()
    kind = room["type"] if room["type"] in ("kitchen", "bedroom") else "trash"
    return {"version": "scenario/v0", "id": building["id"] + "-fire", "buildingId": building["id"],
            "seed": 1, "occupants": {"total": total, "mix": {"typical": 0.85, "older": 0.1, "visitor": 0.05}},
            "sprinklers": False, "doors": {}, "alarmTime": 30, "maxTime": 400,
            "fire": {"floor": floor["id"], "room": room["id"], "x": point.x, "y": point.y, "type": kind, "start": 0}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("building")
    parser.add_argument("output")
    parser.add_argument("--total", type=int, default=120)
    args = parser.parse_args()
    building = json.loads(Path(args.building).read_text(encoding="utf-8"))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(make_scenario(building, args.total), indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
