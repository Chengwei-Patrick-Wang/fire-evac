"""Downward stair routes and seeded, width-limited FIFO admission."""
from __future__ import annotations

from bisect import bisect_right
import math

import numpy as np
from shapely.geometry import Point, Polygon

STAIR_SPEED = 0.55
STAIR_FLOW = 1.1
WALK_SPEED = 1.2


def find_spot(region, others, rng, gap=0.5, tries=64):
    """Return a rounded interior point with clearance, or None after tries draws."""
    if region.is_empty:
        return None
    others = np.asarray(others, dtype=float).reshape(-1, 2)
    minx, miny, maxx, maxy = region.bounds
    for _ in range(tries):
        pos = np.round(rng.uniform((minx, miny), (maxx, maxy)), 2)
        if region.contains(Point(pos)) and np.all(np.sum((others - pos) ** 2, axis=1) >= gap ** 2):
            return float(pos[0]), float(pos[1])
    return None


class StairNet:
    def __init__(self, building):
        floors = sorted(building["floors"], key=lambda f: f["level"])
        self._links = {f["id"]: [] for f in floors}
        self._reachable = {}
        self._admissions = {}
        for floor in floors:
            lower = [f for f in floors if f["level"] < floor["level"]]
            below = lower[-1] if lower else None
            if below is not None:
                arrivals = {s["group"]: s for s in below["stairs"]}
                for stair in floor["stairs"]:
                    if stair["group"] not in arrivals:
                        continue
                    arrival = Polygon(arrivals[stair["group"]]["polygon"])
                    widths = [d["width"] for d in floor["doors"]
                              if stair["room"] in d["connects"] and "outside" not in d["connects"]]
                    width = sum(widths) if widths else 1.0
                    if width <= 0:
                        raise ValueError(f"floor {floor['id']} stair {stair['id']} has nonpositive width")
                    length = 2 * floor["height"]
                    if below["exits"]:
                        onward = min(arrival.distance(Polygon(e["polygon"])) / WALK_SPEED
                                     for e in below["exits"])
                    else:
                        onward = min((arrival.distance(link["polygon"]) / WALK_SPEED + link["tail"]
                                      for link in self.links(below["id"])), default=math.inf)
                    self._links[floor["id"]].append({
                        "stair": stair["id"], "group": stair["group"], "to": below["id"],
                        "width": width, "length": length, "tail": length / STAIR_SPEED + onward,
                        "polygon": Polygon(stair["polygon"]), "arrival": arrival,
                    })
            self._reachable[floor["id"]] = bool(floor["exits"]) or any(
                self._reachable[link["to"]] for link in self.links(floor["id"]))

    def links(self, floor_id):
        return self._links[floor_id]

    def check(self, occupied: set[str]) -> None:
        for floor_id in sorted(occupied):
            if not self._reachable.get(floor_id, False):
                raise ValueError(f"floor {floor_id} has no stair route to an exit")

    def enter(self, idx, t, floor_id, group, rng, speed=STAIR_SPEED):
        if speed <= 0:
            raise ValueError("stair speed must be positive")
        link = next(link for link in self.links(floor_id) if link["group"] == group)
        pos = find_spot(link["arrival"], [], rng)
        if pos is None:
            raise ValueError(f"floor {floor_id} stair {group}: cannot sample arrival polygon")
        admissions = self._admissions.setdefault((floor_id, group), [])
        enter = max(t, admissions[-1] + 1 / (STAIR_FLOW * link["width"])) if admissions else t
        admissions.append(enter)
        return {"enter": enter, "arrive": enter + link["length"] / speed,
                "to": link["to"], "pos": pos}

    def backlog(self, floor_id, group, t):
        admissions = self._admissions.get((floor_id, group), [])
        return len(admissions) - bisect_right(admissions, t)
