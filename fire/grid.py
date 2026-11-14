"""Wall-respecting walkable grids and deterministic smoke path distances."""
from collections import OrderedDict
from dataclasses import dataclass
import heapq
import math

import numpy as np
import shapely
from shapely.geometry import Polygon

CELL = 0.5
MAX_CELLS = 40_000
CLOSED_DOOR_M = 15.0
STAIR_UP_M = 3.0
STAIR_DOWN_M = 30.0


def _walkable(floor: dict):
    return shapely.union_all([Polygon(w["outer"], w.get("holes", [])) for w in floor["walkable"]])


def grid_specs(building: dict, cell: float = CELL) -> list[dict]:
    if not math.isfinite(cell) or cell <= 0:
        raise ValueError("cell must be positive and finite")
    bounds = [shapely.bounds(_walkable(f)) for f in building["floors"]]
    if any(not np.all(np.isfinite(b)) for b in bounds):
        raise ValueError("Each floor needs non-empty walkable geometry")
    while True:
        specs = [{"origin": [float(b[0]), float(b[1])], "cell": float(cell),
                  "cols": math.ceil((b[2] - b[0]) / cell),
                  "rows": math.ceil((b[3] - b[1]) / cell)} for b in bounds]
        if all(s["cols"] * s["rows"] <= MAX_CELLS for s in specs):
            return specs
        cell *= 2


@dataclass
class FloorGraph:
    spec: dict
    mask: np.ndarray
    xy: np.ndarray
    n: int
    door_nodes: dict
    stair_nodes: dict
    snap: np.ndarray


class BuildingGraph:
    def __init__(self, building: dict, cell: float = CELL):
        self.building = building
        self.floor_index = {f["id"]: i for i, f in enumerate(building["floors"])}
        self.floors = []
        self.offset = []
        sources, targets, lengths = [], [], []
        total = 0
        for floor, spec in zip(building["floors"], grid_specs(building, cell)):
            self.offset.append(total)
            spacing = spec["cell"]
            passages = {d["id"]: Polygon(d["rect"]).buffer(spacing / 2)
                        for d in floor.get("doors", [])}
            polygon = shapely.union_all([_walkable(floor), *passages.values()])
            shapely.prepare(polygon)
            yy, xx = np.indices((spec["rows"], spec["cols"]))
            centers = np.stack((spec["origin"][0] + (xx + 0.5) * spacing,
                                spec["origin"][1] + (yy + 0.5) * spacing), axis=-1)
            mask = shapely.contains_xy(polygon, centers[..., 0], centers[..., 1])
            xy = centers[mask]
            n = len(xy)
            if not n:
                raise ValueError(f"Floor {floor['id']} has no walkable grid nodes")
            nodes = np.full(mask.shape, -1, dtype=np.int64)
            nodes[mask] = np.arange(n)
            door_nodes = {key: np.flatnonzero(shapely.contains_xy(p.buffer(1e-3), xy[:, 0], xy[:, 1]))
                          for key, p in passages.items()}
            stair_nodes = {}
            in_door = np.zeros(n, dtype=bool)
            for members in door_nodes.values():
                in_door[members] = True
            for stair in floor.get("stairs", []):
                inside = shapely.contains_xy(Polygon(stair["polygon"]), xy[:, 0], xy[:, 1])
                members = np.flatnonzero(inside & ~in_door)
                group = stair["group"]
                stair_nodes[group] = np.union1d(stair_nodes.get(group, []), members).astype(np.int64)
            # Build four forward directions, then mirror them for eight neighbors.
            for dx, dy in ((1, 0), (0, 1), (1, 1), (-1, 1)):
                r, c = np.nonzero(mask)
                rr, cc = r + dy, c + dx
                inside = (rr >= 0) & (rr < mask.shape[0]) & (cc >= 0) & (cc < mask.shape[1])
                r, c, rr, cc = r[inside], c[inside], rr[inside], cc[inside]
                a, b = nodes[r, c], nodes[rr, cc]
                valid = b >= 0
                a, b = a[valid], b[valid]
                covered = shapely.covers(polygon, shapely.linestrings(np.stack((xy[a], xy[b]), axis=1)))
                a, b = a[covered] + total, b[covered] + total
                sources.extend((a, b))
                targets.extend((b, a))
                lengths.extend((np.full(len(a), spacing * math.hypot(dx, dy)),) * 2)
            snap = nodes.copy()
            missing = np.flatnonzero(~mask)
            if len(missing):
                tree = shapely.STRtree(shapely.points(xy))
                pairs = tree.query_nearest(shapely.points(centers.reshape(-1, 2)[missing]),
                                          max_distance=max(1.0, spacing), all_matches=False)
                snap.flat[missing[pairs[0]]] = pairs[1]
            self.floors.append(FloorGraph(spec, mask, xy, n, door_nodes, stair_nodes, snap))
            total += n
        # Link consecutive levels without starting or ending inside door passages.
        levels = sorted(range(len(self.floors)), key=lambda i: building["floors"][i]["level"])
        for lower, upper in zip(levels, levels[1:]):
            lo, hi = self.floors[lower], self.floors[upper]
            for group in lo.stair_nodes.keys() & hi.stair_nodes.keys():
                low_nodes, high_nodes = lo.stair_nodes[group], hi.stair_nodes[group]
                if not len(low_nodes) or not len(high_nodes):
                    continue
                for start_floor, end_floor, start_nodes, end_nodes, weight in (
                    (lower, upper, low_nodes, high_nodes, STAIR_UP_M),
                    (upper, lower, high_nodes, low_nodes, STAIR_DOWN_M),
                ):
                    a, b = self.floors[start_floor], self.floors[end_floor]
                    nearest = [int(np.argmin(np.sum((b.xy[end_nodes] - point) ** 2, axis=1)))
                               for point in a.xy[start_nodes]]
                    sources.append(start_nodes + self.offset[start_floor])
                    targets.append(end_nodes[nearest] + self.offset[end_floor])
                    lengths.append(np.full(len(start_nodes), weight))
        # CSR lists keep the Dijkstra inner loop free of NumPy scalar overhead.
        src = np.concatenate(sources) if sources else np.array([], dtype=np.int64)
        dst = np.concatenate(targets) if targets else np.array([], dtype=np.int64)
        weight = np.concatenate(lengths) if lengths else np.array([], dtype=float)
        order = np.argsort(src, kind="stable")
        self._indptr = np.r_[0, np.cumsum(np.bincount(src, minlength=total))].tolist()
        self._neighbors = dst[order].tolist()
        self._weights = weight[order].tolist()
        self._members = [set() for _ in range(total)]
        for offset, floor in zip(self.offset, self.floors):
            for key, nodes in floor.door_nodes.items():
                for node in nodes:
                    self._members[offset + int(node)].add(key)
        self.n = total

    def node_at(self, floor_id: str, x: float, y: float, room_polygon: list | None = None) -> int:
        if floor_id not in self.floor_index:
            raise ValueError(f"Unknown floor {floor_id!r}")
        index = self.floor_index[floor_id]
        floor = self.floors[index]
        candidates = np.arange(floor.n)
        if room_polygon is not None:
            candidates = candidates[shapely.contains_xy(Polygon(room_polygon), floor.xy[:, 0], floor.xy[:, 1])]
        if not len(candidates):
            raise ValueError(f"No grid nodes inside the requested room on {floor_id}")
        nearest = np.argmin(np.sum((floor.xy[candidates] - [x, y]) ** 2, axis=1))
        return self.offset[index] + int(candidates[nearest])

    def path_distance(self, source: int, door_penalty: dict[str, float]) -> np.ndarray:
        if not 0 <= source < self.n:
            raise ValueError("source must be a graph node")
        if any(not math.isfinite(v) or v < 0 for v in door_penalty.values()):
            raise ValueError("door penalties must be finite and non-negative")
        dist = [math.inf] * self.n
        dist[source] = 0.0
        queue = [(0.0, source)]
        while queue:
            distance, node = heapq.heappop(queue)
            if distance > dist[node]:
                continue
            for edge in range(self._indptr[node], self._indptr[node + 1]):
                other = self._neighbors[edge]
                penalty = sum(door_penalty.get(key, 0.0)
                              for key in self._members[other] - self._members[node])
                new = distance + self._weights[edge] + penalty
                if new < dist[other]:
                    dist[other] = new
                    heapq.heappush(queue, (new, other))
        return np.asarray(dist, dtype=np.float64)


_CACHE = OrderedDict()


def get_graph(building: dict) -> BuildingGraph:
    """Cache by object identity; graphs retain buildings, preventing id reuse.

    Treat a building as immutable after its first lookup.
    """
    key = id(building)
    if key not in _CACHE:
        _CACHE[key] = BuildingGraph(building)
        if len(_CACHE) > 4:
            _CACHE.popitem(last=False)
    _CACHE.move_to_end(key)
    return _CACHE[key]
