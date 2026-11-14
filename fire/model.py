"""Illustrative smoke front; run as a module to write debug PNGs."""
import argparse
import base64
import json
import math
from pathlib import Path

import numpy as np
import shapely

from fire.grid import CLOSED_DOOR_M, get_graph
from fire.presets import fire_params, hrr_kw
from fire.spread import MATERIALS, ignition_schedule, material_name, room_hrr_kw

V_BASE_MS = 0.25
V_PER_MW = 0.5
V_MAX_MS = 1.0
DECAY_M = 40.0
RISE_S = 30.0
Q_REF_KW = 1000.0
VIS_MAX_M = 30.0
UNTENABLE_D = 90.0
UNTENABLE_HOLD_S = 30.0
FOOT_BASE_M = 0.5
FOOT_PER_SQRT_MW_M = 1.0
TABLE_S = 1800


class FireModel:
    def __init__(self, building: dict, scenario: dict, spread: bool = True):
        """`spread=False` keeps the fire in its ignition room (the smoke-only model); a bad `fire.material` still raises."""
        self.building = building
        self.scenario = scenario
        fire = scenario["fire"]
        self.start = float(fire.get("start", 0))
        self.params = fire_params(fire, scenario.get("sprinklers", False))
        self.material = material_name(fire)
        self.graph = get_graph(building)
        floor_index = self.graph.floor_index.get(fire["floor"])
        if floor_index is None:
            raise ValueError(f"Unknown floor {fire['floor']!r}")
        polygon = None
        if fire.get("room") is not None:
            room = next((r for r in building["floors"][floor_index]["rooms"]
                         if r["id"] == fire["room"]), None)
            if room is None:
                raise ValueError(f"Unknown fire room {fire['room']!r}")
            polygon = room["polygon"]
        source = self.graph.node_at(fire["floor"], fire["x"], fire["y"], polygon)
        self.source_xy = self.graph.floors[floor_index].xy[source - self.graph.offset[floor_index]].copy()
        # D25: the first entry is the ignition room, which keeps today's heat curve, doors and keep-out. Every other
        # room adds heat from its ignition time on and closes its doors (exterior doors too).
        schedule = ignition_schedule(building, scenario)
        self._schedule = schedule if spread else schedule[:1]
        spreading = self._schedule[1:]
        doors = {}
        for floor in building["floors"]:
            for door in floor.get("doors", []):
                for joined in door.get("connects") or []:
                    doors.setdefault((floor["id"], joined), []).append(door["id"])
        self._spread_doors = [(e["ignite"], doors.get((e["floor"], e["room"]), [])) for e in spreading]
        self._spread_ignites = [e["ignite"] for e in spreading]
        self._spread_flashover = MATERIALS[self.material]["flashover"]
        states = {door["id"]: door.get("state", "open")
                  for floor in building["floors"] for door in floor.get("doors", [])}
        states.update(scenario.get("doors", {}))
        penalties = {key: CLOSED_DOOR_M if state in ("closed", "blocked") else 0.0
                     for key, state in states.items()}
        self.dist = self.graph.path_distance(source, penalties)
        times = np.arange(0, TABLE_S + 0.25, 0.25)
        q = np.array([hrr_kw(self.params, t) for t in times])
        for ignite in sorted(self._spread_ignites):  # sorted, so the sum never depends on the building's room order
            ratio = np.clip((times - (ignite - self.start)) / self._spread_flashover, 0.0, 1.0)
            q = q + self.params["peakKw"] * (ratio * ratio)
        speed = np.clip(V_BASE_MS + V_PER_MW * q / Q_REF_KW, V_BASE_MS, V_MAX_MS)
        reach = np.r_[0.0, np.cumsum((speed[:-1] + speed[1:]) * 0.125)]
        self.arrival = np.interp(self.dist, reach, times, right=np.inf)
        self._attenuation = np.exp(-self.dist / DECAY_M)
        self._density = np.zeros(self.graph.n)
        self._hold = np.zeros(self.graph.n)
        self._untenable = np.zeros(self.graph.n, dtype=bool)
        self._blocked = set()
        self._time = 0.0
        self._update(0.0, 0.0)

    def hrr(self, t: float) -> float:
        """Heat release rate in kW: the ignition room's own curve plus every room that has since caught fire."""
        q = float(hrr_kw(self.params, t - self.start))
        if not self._spread_ignites:
            return q
        return math.fsum([q] + [room_hrr_kw(self.params["peakKw"], self._spread_flashover, t - ignite)
                                for ignite in self._spread_ignites if ignite <= t])

    def _update(self, t: float, dt: float) -> None:
        q = self.hrr(t)
        own = float(hrr_kw(self.params, t - self.start))  # the flame footprint is the ignition room's alone
        age = np.maximum(0.0, t - self.start - self.arrival)
        self._density = np.clip(100 * min(1.0, q / Q_REF_KW) * self.params["smokeFactor"]
                                * self._attenuation * (-np.expm1(-age / RISE_S)), 0, 100)
        self._hold = np.where(self._density >= UNTENABLE_D, self._hold + dt, 0.0)
        self._footprint = (own > 0) & (self.dist <= FOOT_BASE_M + FOOT_PER_SQRT_MW_M * math.sqrt(own / Q_REF_KW))
        self._smoke_untenable = self._hold >= UNTENABLE_HOLD_S
        self._untenable = self._smoke_untenable | self._footprint
        self._blocked = {key for offset, floor in zip(self.graph.offset, self.graph.floors)
                         for key, nodes in floor.door_nodes.items()
                         if self._untenable[offset + nodes].any()}
        for ignite, doors in self._spread_doors:
            if ignite <= t:
                self._blocked.update(doors)

    def step(self, t: float) -> None:
        t = float(t)
        if not math.isfinite(t) or t < self._time:
            raise ValueError("Fire time must be finite and must not decrease")
        while self._time < t:
            end = min(t, self._time + 1.0)
            self._update(end, end - self._time)
            self._time = end

    def _node(self, floor_id: str, x: float, y: float) -> int:
        index = self.graph.floor_index.get(floor_id)
        if index is None or not (math.isfinite(x) and math.isfinite(y)):
            return -1
        floor = self.graph.floors[index]
        spec = floor.spec
        col = math.floor((x - spec["origin"][0]) / spec["cell"])
        row = math.floor((y - spec["origin"][1]) / spec["cell"])
        if not (0 <= col < spec["cols"] and 0 <= row < spec["rows"]):
            return -1
        local = int(floor.snap[row, col])
        return self.graph.offset[index] + local if local >= 0 else -1

    def visibility(self, floor_id: str, x: float, y: float) -> float:
        node = self._node(floor_id, x, y)
        d = self._density[node] if node >= 0 else 0.0
        return float(min(VIS_MAX_M, 100.0 / d)) if d > 0 else VIS_MAX_M

    def untenable(self, floor_id: str, x: float, y: float) -> bool:
        node = self._node(floor_id, x, y)
        return bool(self._untenable[node]) if node >= 0 else False

    def blocked_doors(self) -> set[str]:
        """Doors an untenable cell sits in, plus every door of a room that has caught fire (not the ignition room's)."""
        return self._blocked.copy()

    def burning_rooms(self, t: float) -> set[tuple[str, str]]:
        """(floor id, room id) of every room on fire at time t, the ignition room included."""
        return {(e["floor"], e["room"]) for e in self._schedule if e["ignite"] <= t}

    def ignition_times(self) -> list[dict]:
        """[{"room", "floor", "ignite"}] for the rooms that ignite by maxTime, the ignition room first, then by time.
        Fresh copies: the caller may change them."""
        return [dict(e) for e in self._schedule]

    def snapshot(self, floor_id: str) -> dict | None:
        index = self.graph.floor_index.get(floor_id)
        if index is None:
            return None
        floor = self.graph.floors[index]
        offset = self.graph.offset[index]
        density = self._density[offset:offset + floor.n]
        if density.max() < 0.5:
            return None
        grid = np.zeros(floor.mask.shape, dtype=np.uint8)
        grid[floor.mask] = np.rint(density).clip(0, 100).astype(np.uint8)
        return {**floor.spec, "origin": list(floor.spec["origin"]),
                "d": base64.b64encode(grid.tobytes()).decode("ascii")}


def aset_by_room(building: dict, scenario: dict, t_max: float) -> dict[str, float | None]:
    """First smoke-untenable room cell, sampled each second of scenario time.

    Flame footprints still trap agents but do not define this smoke-only ASET.
    None means no threshold crossing observed within the supplied horizon.
    """
    if not math.isfinite(t_max) or t_max < 0:
        raise ValueError("ASET horizon must be finite and non-negative")
    model = FireModel(building, scenario)
    pending = {}
    for floor, grid, offset in zip(building["floors"], model.graph.floors, model.graph.offset):
        for room in floor.get("rooms", []):
            inside = shapely.contains_xy(shapely.Polygon(room["polygon"]), grid.xy[:, 0], grid.xy[:, 1])
            pending[room["id"]] = offset + np.flatnonzero(inside)
    result = dict.fromkeys(pending)
    for t in range(1, math.floor(t_max) + 1):
        model.step(t)
        reached = [key for key, nodes in pending.items() if model._smoke_untenable[nodes].any()]
        for key in reached:
            result[key] = float(t)
            del pending[key]
        if not pending:
            break
    return result


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("building", type=Path)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--doors", default="", help="Comma-separated ID=state overrides")
    parser.add_argument("--tag", default="")
    parser.add_argument("--times", default="30,60,120,180")
    args = parser.parse_args()
    scenario = json.loads(args.scenario.read_text())
    overrides = {}
    for entry in filter(None, args.doors.split(",")):
        key, separator, state = entry.partition("=")
        if not separator or not key.strip() or state.strip() not in ("open", "closed", "propped", "blocked"):
            parser.error("--doors requires ID=open|closed|propped|blocked entries")
        overrides[key.strip()] = state.strip()
    scenario["doors"] = {**scenario.get("doors", {}), **overrides}
    model = FireModel(json.loads(args.building.read_text()), scenario)
    Path("debug").mkdir(exist_ok=True)
    # Keep the tag a filename component even when invoked unattended.
    tag = "_" + Path(args.tag).name if args.tag else ""
    for t in sorted(float(v) for v in args.times.split(",")):
        model.step(t)
        for floor, graph_floor in zip(model.building["floors"], model.graph.floors):
            spec = graph_floor.spec
            snap = model.snapshot(floor["id"])
            grid = (np.frombuffer(base64.b64decode(snap["d"]), dtype=np.uint8)
                    .reshape(spec["rows"], spec["cols"]) if snap else np.zeros(graph_floor.mask.shape))
            index = model.graph.floor_index[floor["id"]]
            offset = model.graph.offset[index]
            maximum = float(model._density[offset:offset + graph_floor.n].max())
            print(f"t={t:g} Q={model.hrr(t):.0f} kW {floor['id']} max d={maximum:.1f}")
            x, y = spec["origin"]
            fig, ax = plt.subplots()
            image = ax.imshow(grid, origin="lower", extent=(x, x + spec["cols"] * spec["cell"],
                              y, y + spec["rows"] * spec["cell"]), vmin=0, vmax=100, cmap="Greys")
            for walkable in floor["walkable"]:
                for ring in [walkable["outer"], *walkable.get("holes", [])]:
                    points = np.asarray([*ring, ring[0]])
                    ax.plot(points[:, 0], points[:, 1], color="steelblue", linewidth=0.7)
            if floor["id"] == model.scenario["fire"]["floor"]:
                ax.plot(*model.source_xy, "r*")
            ax.set(title=f"{floor['id']} t={t:g} s Q={model.hrr(t):.0f} kW max d={maximum:.1f}",
                   xlabel="x (m)", ylabel="y (m)", aspect="equal")
            fig.colorbar(image, ax=ax, label="Illustrative smoke density")
            fig.savefig(Path("debug") / f"smoke_{floor['id']}_t{t:03.0f}{tag}.png")
            plt.close(fig)


if __name__ == "__main__":
    main()
