"""Apply optional, non-destructive plan corrections."""
from copy import deepcopy
import json
from pathlib import Path


def load_overrides(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def apply_overrides(plan: dict, overrides: dict) -> dict:
    plan = deepcopy(plan)
    removed = set(overrides.get("floors", {}).get("remove", []))
    known = {f["id"] for f in plan["floors"]}
    if removed - known:
        raise ValueError(f"unknown floor {sorted(removed - known)[0]}")
    ordered = sorted(plan["floors"], key=lambda f: (f.get("elevation", 0), f.get("level", 0)))
    for i, floor in enumerate(ordered):
        if floor["id"] in removed and any(f["id"] not in removed for f in ordered[i + 1:]):
            raise ValueError(f"cannot remove floor {floor['id']} below a kept floor")
    plan["floors"] = [f for f in plan["floors"] if f["id"] not in removed]
    floors = {f["id"]: f for f in plan["floors"]}
    def remove(kind, ids):
        for item_id in ids:
            found = False
            for floor in floors.values():
                items = floor.get(kind, [])
                filtered = [item for item in items if item["id"] != item_id]
                found |= len(filtered) != len(items)
                floor[kind] = filtered
            if not found:
                raise ValueError(f"unknown {kind[:-1]} {item_id}")
    remove("doors", overrides.get("doors", {}).get("remove", []))
    remove("rooms", overrides.get("rooms", {}).get("remove", []))
    for door in overrides.get("doors", {}).get("add", []):
        fid = door["floor"]
        if fid not in floors:
            raise ValueError(f"unknown floor {fid}")
        if any(d["id"] == door["id"] for f in floors.values() for d in f.get("doors", [])):
            raise ValueError(f"duplicate door {door['id']}")
        floors[fid].setdefault("doors", []).append({k: v for k, v in door.items() if k != "floor"})
    rooms = {r["id"]: r for f in floors.values() for r in f.get("rooms", [])}
    for group, ids in overrides.get("stairGroups", {}).items():
        for rid in ids:
            if rid not in rooms:
                raise ValueError(f"unknown room {rid}")
            rooms[rid].update(type="stair", group=group)
    return plan
