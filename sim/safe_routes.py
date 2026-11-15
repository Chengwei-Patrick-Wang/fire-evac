"""Conservative fire clearance and complete routes between connected floor regions.

The clearance is an illustrative scenario assumption, not a certified distance.
Hazard geometry is reserved for the run (including delayed ignition); this is
conservative global hazard knowledge, not a model of individual perception.
"""
import heapq
import itertools
import math

from sim.floors import STAIR_UP_FACTOR
import jupedsim as jps
from shapely.geometry import Point, LineString
from shapely.ops import unary_union


def pieces(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == 'Polygon':
        return [geometry]
    return sorted((p for g in geometry.geoms for p in pieces(g)),
                  key=lambda p: (-p.area, p.bounds))


def body_clear_regions(safe, clearance):
    """Restore each body-clear component without reconnecting narrow necks.

    Unioning restored components directly can reopen a slit that their eroded
    cores could not traverse. Remove overlapping restoration areas from both
    sides, leaving separate physical regions for JuPedSim.
    """
    cores = pieces(safe.buffer(-clearance, join_style=2))
    restored = [core.buffer(clearance, join_style=2).intersection(safe) for core in cores]
    overlaps = []
    for i, first in enumerate(restored):
        for second in restored[i + 1:]:
            overlap = first.intersection(second)
            if not overlap.is_empty:
                overlaps.append(overlap.buffer(1e-5))
    cuts = unary_union(overlaps)
    # Remove sub-micron duplicate vertices produced by buffer/intersection.
    # JuPedSim's triangulation cannot reliably handle those degenerate edges.
    return unary_union([region.difference(cuts).simplify(1e-6, preserve_topology=True)
                        for region in restored])


def hazard_cut(walk, x, y, radius, clearance=0.35):
    """Exclude flame plus required clearance, preserving body-clear regions."""
    if radius <= 0:
        return walk
    # Circumscribe the circle: polygon chords must not reduce the exclusion.
    extent = (radius + clearance) / math.cos(math.pi / 32)
    exclusion = Point(x, y).buffer(extent, quad_segs=8)
    safe = walk.difference(exclusion)
    return body_clear_regions(safe, clearance)


def proximity_cost(points, zone, speed):
    """Prefer more distance from flame without forbidding a clear retreat.

    Time inside the preferred zone carries twice its walking-time cost. This
    is a modeling preference, not a new physical boundary or safety standard.
    """
    if zone is None or len(points) < 2:
        return 0.0
    return 2 * LineString(points).intersection(zone).length / max(speed, 0.2)


def path_length(walk, start, end, router=None):
    """A failed geometric route is unavailable, never a straight line through fire."""
    try:
        points = (router or jps.RoutingEngine(walk)).compute_waypoints(start, end)
        if not points or (len(points) == 1 and math.dist(start, end) > 1e-6):
            return math.inf
        return sum(math.dist(a, b) for a, b in zip(points, points[1:]))
    except Exception:
        return math.inf


class BuildingRoutes:
    """Search complete exit routes, excluding regions already left by this agent."""
    def __init__(self, sims):
        self.sims = sims
        self.by_floor = {}
        for fs in sims:
            self.by_floor.setdefault(fs.id, []).append(fs)
        self.cache = {}
        self.distances = {}
        self.routers = {fs.key: jps.RoutingEngine(fs.walk) for fs in sims}

    def destination(self, stage):
        choices = [(stage['arrival'].intersection(fs.walk).area, fs)
                   for fs in self.by_floor.get(stage['to'], [])]
        return max(choices, key=lambda item: item[0])[1] if choices and max(a for a, _ in choices) > 0 else None

    def distance(self, fs, pos, stage):
        key = (fs.key, round(pos[0] * 2), round(pos[1] * 2), stage['id'])
        if key not in self.distances:
            goal = stage['poly'].representative_point()
            self.distances[key] = path_length(fs.walk, pos, (goal.x, goal.y), self.routers[fs.key])
        return self.distances[key]

    def tail(self, stage, forbidden, blocked, speed, stair_speed, radius=0.2):
        if stage['kind'] == 'exit':
            return 0.0
        key = (stage['origin'], stage['id'], frozenset(forbidden), frozenset(blocked), speed, stair_speed, radius)
        if key in self.cache:
            return self.cache[key]
        serial = itertools.count()
        queue, best = [], {}

        def transfer(st, cost):
            fs = self.destination(st)
            if fs is None or fs.key in forbidden:
                return
            landing = st['arrival'].intersection(fs.walk).buffer(-(radius + 0.25))
            if landing.is_empty:
                return
            point = landing.representative_point()
            state = (fs.key, st['group'])
            total = cost + st['length'] / (stair_speed * (STAIR_UP_FACTOR if st['direction'] == 'up' else 1.0))
            if total < best.get(state, math.inf):
                best[state] = total
                heapq.heappush(queue, (total, next(serial), fs, (point.x, point.y), state))

        transfer(stage, 0.0)
        answer = math.inf
        while queue:
            cost, _, fs, pos, state = heapq.heappop(queue)
            if cost != best[state]:
                continue
            for st in fs.stages:
                if (fs.key, st['id']) in blocked:
                    continue
                value = cost + self.distance(fs, pos, st) / max(speed, 0.2)
                if st['kind'] == 'exit':
                    answer = min(answer, value)
                elif value < answer:
                    transfer(st, value)
        self.cache[key] = answer
        return answer
