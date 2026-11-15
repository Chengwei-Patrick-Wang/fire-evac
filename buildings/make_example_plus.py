"""Derive example-office-plus from the synthetic example office (contracts/plan.example.json).

    python -m buildings.make_example_plus

Writes data/buildings/example-office-plus.json and example-office-plus.scenario.json. The copy is the example office
with one more stairwell and one more exit, for side-by-side comparison; everything else keeps its coordinates:

- Stair C (group SC): SC1 on F1 and SC2 on F2 take the east 4 m of the lounge R106 / open office R207, x 18-22 and
  y 9.5-16: the 4 m x 6.5 m of the other stairs, on the corridor's mid-point (x = 20), the side away from the stairs
  SA and SB. R106 and R207 keep their ids and their west 6 m.
- DSC1 and DSC2: 1 m fire doors from the corridors C1 and C2 into the new stair, like DSA1 and DSB1.
- E3 "South stair exit": a 1 m door in SC1's south wall to the outside, like E2 at the foot of stair B (the
  normalizer adds its stub and exit zone). F2 has no exits, as before.
- The scenario is the example's, with each room's headcount pinned to what the example gets (still 160 people):
  R106 and R207 are smaller, so splitting the same 160 by area would move people between rooms.
"""
from __future__ import annotations

import copy
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shapely.geometry import Polygon, box  # noqa: E402
from shapely.ops import unary_union  # noqa: E402

from buildings.normalize import plan_to_building  # noqa: E402

BUILDING_ID = "example-office-plus"
NAME = "Example office + extra stair (synthetic, 2 floors)"
SC_X = (18.0, 22.0)          # the new stair block; the corridor's mid-point is x = 20
SC_Y = (9.5, 16.0)           # the south room row's depth
DOOR_X = (19.5, 20.5)        # a 1 m door centred on x = 20
DONORS = {"F1": "R106", "F2": "R207"}   # the rooms that give up their east 4 m
BAY = box(17.5, 9.0, 22.5, 18.5)        # everything that may differ from the example lies in here


def rect(x0: float, x1: float, y0: float, y1: float) -> list[list[float]]:
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def make_plan(example: dict) -> dict:
    plan = copy.deepcopy(example)
    plan["id"], plan["name"] = BUILDING_ID, NAME
    for floor in plan["floors"]:
        n = floor["id"][1:]
        donor = next(r for r in floor["rooms"] if r["id"] == DONORS[floor["id"]])
        donor["polygon"] = rect(12.0, SC_X[0], *SC_Y)
        floor["rooms"].append({"id": f"SC{n}", "name": "Stair C", "type": "stair",  # appended: the other rooms keep their order
                               "polygon": rect(*SC_X, *SC_Y), "group": "SC"})
        floor["doors"].append({"id": f"DSC{n}", "a": [DOOR_X[0], SC_Y[0]], "b": [DOOR_X[1], SC_Y[0]], "width": 1.0,
                               "fireDoor": True, "state": "closed"})
        if floor["id"] == "F1":
            floor["doors"].append({"id": "E3", "a": [DOOR_X[0], SC_Y[1]], "b": [DOOR_X[1], SC_Y[1]], "width": 1.0,
                                   "fireDoor": False, "state": "closed", "name": "South stair exit"})
    return plan


def walk_area(floor: dict):
    return unary_union([Polygon(p["outer"], p.get("holes", [])) for p in floor["walkable"]])


def check_same(example: dict, plus: dict) -> None:
    """Every room, door, stair and exit of the example is unchanged, bar the two rooms that gave up space."""
    for fe, fp in zip(example["floors"], plus["floors"]):
        head = lambda f: {k: v for k, v in f.items() if k not in ("walkable", "rooms", "doors", "stairs", "exits")}
        assert head(fe) == head(fp), fe["id"]
        for key, skip in (("rooms", {DONORS[fe["id"]]}), ("doors", set()), ("stairs", set()), ("exits", set())):
            now = {i["id"]: i for i in fp[key]}
            for item in fe[key]:
                assert item["id"] in skip or now[item["id"]] == item, f"{fe['id']} {key} {item['id']} changed"
        # outside the bay only the normalizer's simplify() may move the outline: slivers under 2 cm along the corridor wall
        outside = walk_area(fe).symmetric_difference(walk_area(fp)).difference(BAY)
        assert outside.buffer(-0.01).is_empty, f"{fe['id']}: walkable area differs outside the new bay ({outside.area:.4f} m2)"
    assert [r["id"] for r in plus["floors"][0]["rooms"][:12]] == [r["id"] for r in example["floors"][0]["rooms"]]


def make_scenario(example_building: dict, example_scenario: dict) -> dict:
    import numpy as np
    from sim.run import place_occupants  # the sim's own split of the people, so the counts are exactly the example's

    agents = place_occupants(example_building, example_scenario, np.random.default_rng(int(example_scenario["seed"])))
    counts = Counter(a["room"] for a in agents)
    scenario = copy.deepcopy(example_scenario)
    scenario["id"] = "example-plus-kitchen-fire"
    scenario["buildingId"] = BUILDING_ID
    scenario["occupants"]["perRoom"] = {r["id"]: counts[r["id"]] for f in example_building["floors"]
                                        for r in f["rooms"] if counts[r["id"]]}
    assert sum(scenario["occupants"]["perRoom"].values()) == scenario["occupants"]["total"]
    return scenario


def write(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def main() -> int:
    plan = json.loads((ROOT / "contracts/plan.example.json").read_text(encoding="utf-8"))
    example = json.loads((ROOT / "contracts/building.example.json").read_text(encoding="utf-8"))
    scenario = json.loads((ROOT / "contracts/scenario.example.json").read_text(encoding="utf-8"))
    plus = plan_to_building(make_plan(plan))
    check_same(example, plus)
    out = ROOT / "data/buildings"
    write(out / f"{BUILDING_ID}.json", json.dumps(plus, indent=1))  # as normalize writes public buildings
    write(out / f"{BUILDING_ID}.scenario.json", json.dumps(make_scenario(example, scenario), indent=1) + "\n")
    for f in plus["floors"]:
        print(f"{f['id']}: {len(f['rooms'])} rooms, {len(f['doors'])} doors, exits {[e['id'] for e in f['exits']]}, "
              f"stairs {[s['id'] for s in f['stairs']]}, walkable {walk_area(f).area:.1f} m2")
    print(f"wrote {out / (BUILDING_ID + '.json')} and its scenario; run python -m buildings.summary to refresh index.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
