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


def check_ifc():
    if not IFC_PATH.exists():
        print("SKIP ifc: file missing")
        return
    from buildings.ifc import extract
    plan = extract(IFC_PATH)
    floors = plan["floors"]
    assert floors and all(f["rooms"] for f in floors)
    assert all(a["elevation"] < b["elevation"] for a, b in zip(floors, floors[1:]))
    polygons = [Polygon(r["polygon"]) for f in floors for r in f["rooms"]]
    assert all(p.is_valid and not p.interiors and 1 <= p.area <= 2000 for p in polygons)
    minx, miny, maxx, maxy = unary_union(polygons).bounds
    assert minx == 0 and miny == 0
    assert 10 <= maxx <= 500 and 10 <= maxy <= 500
    print(f"IFC: {len(floors)} floors, {len(polygons)} rooms, {maxx:.1f} x {maxy:.1f} m")


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

    # Rooms connect only through doors: cutting out the door rects leaves one piece per room
    # plus one per exit stub. Missing walls would merge neighboring rooms into one piece.
    for f in b["floors"]:
        walk = Polygon(f["walkable"][0]["outer"], f["walkable"][0]["holes"])
        cut = walk.difference(unary_union([Polygon(d["rect"]) for d in f["doors"]]))
        n_parts = len(cut.geoms) if hasattr(cut, "geoms") else 1
        expected = len(f["rooms"]) + len(f["exits"])
        assert n_parts == expected, f"{f['id']}: {n_parts} pieces without doors, expected {expected}"

    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")
    check_ifc()
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
