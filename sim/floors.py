"""Seeded stair transfers; optional bidirectional routes share flight capacity."""
from __future__ import annotations

from bisect import bisect_right
import math
import sys

import numpy as np
from shapely.geometry import Point, Polygon

STAIR_SPEED = 0.55
STAIR_UP_FACTOR = 0.8  # Illustrative ascent assumption; not a measured calibration.
STAIR_FLOW = 1.1
WALK_SPEED = 1.2


def reachable_zone(poly, walk, label):
    """Reject zones detached from the retained floor geometry."""
    if poly.is_empty or poly.distance(walk) > 0.1:
        print(f"WARNING (sim): dropping {label}: outside walkable area (> 0.1 m)", file=sys.stderr)
        return False
    return True


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


def stair_doors(floor, stair):
    return {d["id"] for d in floor["doors"] if stair["room"] in d["connects"]}


def stair_blocked(floor, stair, blocked):
    doors = stair_doors(floor, stair)
    return bool(doors) and doors <= blocked


class StairNet:
    def __init__(self, building, walkable=None, blocked=frozenset(), bidirectional=False):
        floors = sorted(building["floors"], key=lambda f: f["level"])
        exits = {f["id"]: [e for e in f["exits"] if e["door"] not in blocked and (walkable is None or
                 reachable_zone(Polygon(e["polygon"]), walkable[f["id"]],
                                f"{f['id']} exit {e['id']}"))] for f in floors}
        self._links = {f["id"]: [] for f in floors}
        self._reachable = {}
        self._admissions = {}
        levels = {f['id']: f['level'] for f in floors}
        for floor in floors:
            lower = [f for f in floors if f["level"] < floor["level"]]
            below = lower[-1] if lower else None
            if below is not None:
                arrivals = {s["group"]: s for s in below["stairs"]}
                for stair in floor["stairs"]:
                    if stair["group"] not in arrivals:
                        continue
                    if (stair_blocked(floor, stair, blocked) or
                        stair_blocked(below, arrivals[stair["group"]], blocked)):
                        continue
                    arrival = Polygon(arrivals[stair["group"]]["polygon"])
                    polygon = Polygon(stair["polygon"])
                    if walkable is not None and not (
                        reachable_zone(polygon, walkable[floor["id"]], f"{floor['id']} stair {stair['id']}")
                        and reachable_zone(arrival, walkable[below["id"]], f"{below['id']} arrival {stair['group']}")
                    ):
                        continue
                    widths = [d["width"] for d in floor["doors"]
                              if stair["room"] in d["connects"] and "outside" not in d["connects"]]
                    width = sum(widths) if widths else 1.0
                    if width <= 0:
                        raise ValueError(f"floor {floor['id']} stair {stair['id']} has nonpositive width")
                    length = 2 * floor["height"]
                    if exits[below["id"]]:
                        onward = min(arrival.distance(Polygon(e["polygon"])) / WALK_SPEED
                                     for e in exits[below["id"]])
                    else:
                        onward = min((arrival.distance(link["polygon"]) / WALK_SPEED + link["tail"]
                                      for link in self.links(below["id"])), default=math.inf)
                    self._links[floor["id"]].append({
                        "stair": stair["id"], "group": stair["group"], "to": below["id"],
                        "width": width, "length": length, "tail": length / STAIR_SPEED + onward,
                        "polygon": Polygon(stair["polygon"]), "arrival": arrival,
                    })
            self._reachable[floor["id"]] = bool(exits[floor["id"]]) or any(
                self._reachable[link["to"]] for link in self.links(floor["id"]))

        # Reverse links retain the original stair id for downward travel.
        # Keep the legacy downward-only API for standalone callers.
        if bidirectional:
            by_id = {f['id']: f for f in floors}
            downward = [(fid, link) for fid in self._links for link in list(self._links[fid])]
            for fid, link in downward:
                source = next(s for s in by_id[link['to']]['stairs'] if s['group'] == link['group'])
                self._links[link['to']].append({**link, 'stair': source['id'] + '@' + fid,
                    'to': fid, 'polygon': link['arrival'], 'arrival': link['polygon']})
        self._flights = {}
        for fid, links in self._links.items():
            for link in links:
                link['direction'] = 'up' if levels[link['to']] > levels[fid] else 'down'

    def links(self, floor_id):
        return self._links[floor_id]

    def check(self, occupied: set[str]) -> None:
        for floor_id in sorted(occupied):
            if not self._reachable.get(floor_id, False):
                raise ValueError(f"floor {floor_id} has no stair route to an exit")

    def enter(self, idx, t, floor_id, group, rng, speed=STAIR_SPEED, hold_until=None, to=None):
        if speed <= 0:
            raise ValueError("stair speed must be positive")
        link = next(link for link in self.links(floor_id) if link["group"] == group and (to is None or link["to"] == to))
        if link["direction"] == "up":
            speed *= STAIR_UP_FACTOR
        pos = find_spot(link["arrival"], [], rng)
        if pos is None:
            raise ValueError(f"floor {floor_id} stair {group}: cannot sample arrival polygon")
        admissions = self._admissions.setdefault((floor_id, group), [])
        ready = t if hold_until is None else max(t, hold_until)
        gap = 1 / (STAIR_FLOW * link["width"])
        flight = (tuple(sorted((floor_id, link['to']))), group)
        reservations = self._flights.setdefault(flight, [])
        duration = link['length'] / speed
        # Opposing flows share one flight: do not overlap directions in transit.
        while True:
            conflicts = [end for start, end, origin in reservations
                         if origin != floor_id and ready < end and ready + duration > start]
            if not conflicts:
                break
            ready = max(conflicts)
        slot = bisect_right(admissions, ready)
        enter = max(ready, admissions[slot - 1] + gap) if slot else ready
        # Reserve the earliest free slot; a future assistance reservation must
        # not hold people who can use the stair now.
        while slot < len(admissions) and admissions[slot] - enter < gap:
            enter = admissions[slot] + gap
            slot += 1
        while True:
            conflicts = [end for start, end, origin in reservations
                         if origin != floor_id and enter < end and enter + duration > start]
            if not conflicts:
                break
            enter = max(conflicts)
            slot = bisect_right(admissions, enter)
            while slot < len(admissions) and admissions[slot] - enter < gap:
                enter = admissions[slot] + gap
                slot += 1
        admissions.insert(slot, enter)
        reservations.append((enter, enter + duration, floor_id))
        entry = {"enter": enter, "arrive": enter + link["length"] / speed,
                 "to": link["to"], "pos": pos}
        if hold_until is not None:
            wait_pos = find_spot(link["polygon"], [], rng)
            if wait_pos is None:
                raise ValueError(f"floor {floor_id} stair {group}: cannot sample wait polygon")
            entry.update(hold_until=hold_until, wait_pos=wait_pos, floor=floor_id)
        return entry

    def backlog(self, floor_id, group, t):
        admissions = self._admissions.get((floor_id, group), [])
        return len(admissions) - bisect_right(admissions, t)
