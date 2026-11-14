"""Sim v0 (spec §7.2, scaffold Task S3): one JuPedSim simulation per floor; stairs are sinks.

C owns this module and replaces it (stair transfer, brain, reroutes, blocked doors).

    python -m sim.run BUILDING SCENARIO OUT

v0 behavior:
- Occupants are split over rooms (not corridor/stair/restroom/storage) by area, or
  scenario.occupants.perRoom; profile, v0 and startDelay come from sim.profiles.
- One CollisionFreeSpeedModel sim per floor. Stages: every exit on the floor, plus
  every stair zone on floors above the lowest (sinks: a "stair" event, never "exit").
- Each agent heads for the nearest stage (straight line) and stands still
  (desired_speed 0) until alarmTime + startDelay.
- Every 1 s: fire.step(t), smoke slows agents, untenable cells trap them.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import jupedsim as jps
import numpy as np
import shapely
from shapely.geometry import Point, Polygon

from fire.stub import NoFire
from sim.profiles import PROFILES

DT = 0.01
FRAME_EVERY = 50     # steps (0.5 s)
FIRE_EVERY = 100     # steps (1 s)
SMOKE_EVERY = 200    # steps (2 s)
FRAME_INTERVAL = 0.5
SMOKE_INTERVAL = 2
NO_OCCUPANTS = {"corridor", "stair", "restroom", "storage"}
WALL_CLEARANCE = 0.3   # spawn inside (room ∩ walkable).buffer(-0.3)
MIN_SPACING = 0.5      # spawn points at least this far apart
STOPPED = 0.0          # desired_speed before the start delay is over (1.4.2 accepts 0)
MIN_SMOKE_SPEED = 0.2


def _warn(msg: str) -> None:
    print(f"WARNING (sim): {msg}", file=sys.stderr)


def floor_walkable(floor: dict) -> Polygon:
    """The floor's walkable polygon (the largest piece if the normalizer left several)."""
    polys = sorted((Polygon(w["outer"], w["holes"]) for w in floor["walkable"]), key=lambda p: p.area, reverse=True)
    if not polys:
        raise ValueError(f"floor {floor['id']} has no walkable area")
    if len(polys) > 1:
        _warn(f"{floor['id']}: {len(polys)} walkable pieces; simulating the largest only")
    return polys[0]


def _largest_remainder(total: int, weights: list[float]) -> list[int]:
    w = np.asarray(weights, dtype=float)
    if total <= 0 or w.sum() <= 0:
        return [0] * len(w)
    quota = total * w / w.sum()
    counts = np.floor(quota).astype(int)
    rest = int(total - counts.sum())
    order = np.argsort(-(quota - counts), kind="stable")
    counts[order[:rest]] += 1
    return counts.tolist()


def _sample_points(region, n: int, rng: np.random.Generator, taken: list, label: str) -> list[tuple]:
    """Rejection-sample n points (rounded to 0.01) inside region, >= MIN_SPACING from taken and each other."""
    out: list[tuple] = []
    if n <= 0:
        return out
    minx, miny, maxx, maxy = region.bounds
    min_d, tries, max_tries = MIN_SPACING, 0, 2000 + 400 * n
    while len(out) < n:
        cand = np.round(rng.uniform((minx, miny), (maxx, maxy), size=(64, 2)), 2)
        inside = shapely.contains_xy(region, cand[:, 0], cand[:, 1])
        for (x, y), ok in zip(cand.tolist(), inside):
            if not ok:
                continue
            if taken and min((x - px) ** 2 + (y - py) ** 2 for px, py in taken) < min_d ** 2:
                continue
            taken.append((x, y))
            out.append((x, y))
            if len(out) == n:
                break
        tries += 64
        if len(out) < n and tries > max_tries:
            if min_d > 0.42:
                _warn(f"room {label}: crowded, spacing spawn points at 0.42 m instead of {MIN_SPACING} m")
                min_d, tries = 0.42, 0
            else:
                raise ValueError(f"cannot fit {n} agents in room {label}")
    return out


def place_occupants(building: dict, scenario: dict, rng: np.random.Generator) -> list[dict]:
    """Agents with idx 0..N-1, profile, floor, room, v0, startDelay, radius, x, y."""
    occ = scenario.get("occupants") or {}
    rooms = []  # (floor id, room, spawn region)
    for floor in building["floors"]:
        walk = floor_walkable(floor)
        for room in floor["rooms"]:
            region = Polygon(room["polygon"]).intersection(walk).buffer(-WALL_CLEARANCE)
            rooms.append((floor["id"], room, region))

    if occ.get("perRoom"):
        per_room = occ["perRoom"]
        counts = [int(per_room.get(room["id"], 0)) for _, room, _ in rooms]
    else:
        weights = [Polygon(room["polygon"]).area if room.get("type") not in NO_OCCUPANTS and not region.is_empty
                   else 0.0 for _, room, region in rooms]
        counts = _largest_remainder(int(occ.get("total", 0)), weights)
    for (fid, room, region), n in zip(rooms, counts):
        if n and region.is_empty:
            raise ValueError(f"room {fid}/{room['id']} has no room to place {n} agents")

    agents = [{"idx": 0, "floor": fid, "room": room["id"]} for (fid, room, _), n in zip(rooms, counts) for _ in range(n)]
    mix = occ.get("mix") or {"typical": 1.0}
    names = list(mix)
    p = np.array([float(mix[k]) for k in names])
    p = p / p.sum()
    unknown = set()
    for i, a in enumerate(agents):
        a["idx"] = i
        prof = names[int(rng.choice(len(names), p=p))]
        spec = PROFILES.get(prof)
        if spec is None:
            unknown.add(prof)
            spec = PROFILES["typical"]
        a["profile"] = prof
        a["v0"] = round(float(rng.uniform(*spec["v0"])), 2)
        a["startDelay"] = round(float(rng.uniform(*spec["startDelay"])), 1)
        a["radius"] = spec["radius"]
    if unknown:
        _warn(f"unknown profiles {sorted(unknown)}: using 'typical' parameters")

    taken = {f["id"]: [] for f in building["floors"]}
    i = 0
    for (fid, room, region), n in zip(rooms, counts):
        for x, y in _sample_points(region, n, rng, taken[fid], f"{fid}/{room['id']}"):
            agents[i]["x"], agents[i]["y"] = x, y
            i += 1
    return agents


class _FloorSim:
    """One JuPedSim simulation for one floor, plus our jps-id -> idx map."""

    def __init__(self, floor: dict, index: int, has_stair_sinks: bool):
        self.id = floor["id"]
        self.index = index
        self.walk = floor_walkable(floor)
        self.sim = jps.Simulation(model=jps.CollisionFreeSpeedModel(), geometry=self.walk, dt=DT)
        self.stages: list[dict] = []
        self.jid2idx: dict[int, int] = {}
        zones = [("exit", e["id"], None, e["polygon"]) for e in floor["exits"]]
        if has_stair_sinks:
            zones += [("stair", s["id"], s["group"], s["polygon"]) for s in floor["stairs"]]
        for kind, zid, group, ring in zones:
            poly = Polygon(ring)
            stage = self.sim.add_exit_stage(poly)
            journey = self.sim.add_journey(jps.JourneyDescription([stage]))
            self.stages.append({"kind": kind, "id": zid, "group": group, "poly": poly,
                                "stage": stage, "journey": journey})
        # Agents who have not started yet "park" on a direct-steering stage aimed at their own
        # position: they still stand as obstacles, but skip JuPedSim's per-step routing, which
        # is ~5x the cost of everything else on this geometry.
        self.park_stage = self.sim.add_direct_steering_stage()
        self.park_journey = self.sim.add_journey(jps.JourneyDescription([self.park_stage]))


def _frame(sims: list[_FloorSim], trapped: set, status: list[int]) -> list[list]:
    rows = []
    for fs in sims:
        for ag in fs.sim.agents():
            i = fs.jid2idx.get(ag.id)
            if i is None or i in trapped:
                continue
            x, y = ag.position
            rows.append([i, round(x, 2) + 0.0, round(y, 2) + 0.0, fs.index, status[i]])
    rows.sort(key=lambda r: r[0])
    return rows


def _t_share(exit_times: list[float], n_agents: int, share: float):
    if n_agents == 0:
        return None
    need = max(1, math.ceil(share * n_agents - 1e-9))
    return exit_times[need - 1] if len(exit_times) >= need else None


def run(building: dict, scenario: dict, fire=None) -> dict:
    """building/v0 + scenario/v0 (+ fire model) -> run/v0."""
    if fire is None:
        fire = NoFire(building, scenario)
    seed = int(scenario.get("seed", 0))
    rng = np.random.default_rng(seed)
    agents = place_occupants(building, scenario, rng)
    n = len(agents)

    floors = building["floors"]
    lowest = min(f.get("level", 0) for f in floors)
    sims = [_FloorSim(f, i, f.get("level", 0) > lowest) for i, f in enumerate(floors)]
    by_id = {fs.id: fs for fs in sims}

    status = [0] * n
    target: list[dict | None] = [None] * n
    where: list[tuple | None] = [None] * n
    for a in agents:
        fs = by_id[a["floor"]]
        if not fs.stages:
            raise ValueError(f"floor {fs.id} has occupants but no exits or stairs to go to")
        pt = Point(a["x"], a["y"])
        st = min(fs.stages, key=lambda s: s["poly"].distance(pt))
        jid = fs.sim.add_agent(jps.CollisionFreeSpeedModelAgentParameters(
            position=(a["x"], a["y"]), desired_speed=STOPPED, radius=a["radius"],
            journey_id=fs.park_journey, stage_id=fs.park_stage))
        fs.sim.agent(jid).target = (a["x"], a["y"])
        fs.jid2idx[jid] = a["idx"]
        target[a["idx"]] = st
        where[a["idx"]] = (fs, jid)

    alarm = float(scenario.get("alarmTime", 0))
    max_time = float(scenario.get("maxTime", 600))
    start_order = sorted(range(n), key=lambda i: (agents[i]["startDelay"], i))
    next_start = 0

    events: list[dict] = []
    frames: list[dict] = []
    smoke: dict[str, dict] = {}
    hrr: list[list] = []
    trapped: set[int] = set()
    active = n  # agents still inside a floor sim
    k, t = 0, 0.0
    while True:
        t = round(k * DT, 2)
        while next_start < n and alarm + agents[start_order[next_start]]["startDelay"] <= t + 1e-9:
            i = start_order[next_start]
            next_start += 1
            if status[i] == 0 and i not in trapped:
                fs, jid = where[i]
                fs.sim.switch_agent_journey(jid, target[i]["journey"], target[i]["stage"])
                fs.sim.agent(jid).model.desired_speed = agents[i]["v0"]
                status[i] = 1

        if k % FIRE_EVERY == 0:
            fire.step(t)
            for fs in sims:
                for ag in list(fs.sim.agents()):
                    i = fs.jid2idx.get(ag.id)
                    if i is None or i in trapped:
                        continue
                    x, y = ag.position
                    if fire.untenable(fs.id, x, y):
                        fs.sim.mark_agent_for_removal(ag.id)
                        trapped.add(i)
                        active -= 1
                        events.append({"t": t, "type": "trapped", "idx": i, "floor": fs.id,
                                       "x": round(x, 2), "y": round(y, 2)})
                    elif status[i] == 1:
                        v0 = agents[i]["v0"]
                        vis = fire.visibility(fs.id, x, y)
                        ag.model.desired_speed = min(v0, max(MIN_SMOKE_SPEED, v0 - 0.34 * (3.0 - vis)))

        if k % FRAME_EVERY == 0:
            frames.append({"t": t, "a": _frame(sims, trapped, status)})

        if k % SMOKE_EVERY == 0:
            for fs in sims:
                snap = fire.snapshot(fs.id)
                if snap is None:
                    continue
                entry = smoke.get(fs.id)
                if entry is None:
                    entry = smoke[fs.id] = {"floor": fs.id, "origin": list(snap["origin"]), "cell": snap["cell"],
                                            "cols": snap["cols"], "rows": snap["rows"],
                                            "interval": SMOKE_INTERVAL, "frames": []}
                entry["frames"].append({"t": t, "d": snap["d"]})
            hrr.append([t, round(float(fire.hrr(t)), 1)])

        if active <= 0 or t >= max_time - 1e-9:
            break

        for fs in sims:
            fs.sim.iterate()
        k += 1
        t_now = round(k * DT, 2)
        for fs in sims:
            for jid in fs.sim.removed_agents():  # last iteration only: check every step
                i = fs.jid2idx.get(jid)
                if i is None or i in trapped:
                    continue
                active -= 1
                status[i] = -1
                st = target[i]
                if st["kind"] == "exit":
                    events.append({"t": t_now, "type": "exit", "idx": i, "exit": st["id"]})
                else:
                    events.append({"t": t_now, "type": "stair", "idx": i, "floor": fs.id, "group": st["group"]})

    if active <= 0 and frames and frames[-1]["t"] < t:
        # Close the replay with an empty frame on the 0.5 s grid.
        frames.append({"t": math.ceil(t / FRAME_INTERVAL - 1e-9) * FRAME_INTERVAL, "a": []})

    exit_events = [e for e in events if e["type"] == "exit"]
    exit_times = sorted(e["t"] for e in exit_events)
    exit_counts = {e["id"]: 0 for f in floors for e in f["exits"]}
    for e in exit_events:
        exit_counts[e["exit"]] = exit_counts.get(e["exit"], 0) + 1
    metrics = {
        "agents": n,
        "evacuated": len(exit_events),
        "trapped": len(trapped),
        "inStairs": sum(1 for e in events if e["type"] == "stair"),
        "remaining": active,
        "t50": _t_share(exit_times, n, 0.5),
        "t90": _t_share(exit_times, n, 0.9),
        "t100": _t_share(exit_times, n, 1.0),
        "exitCounts": exit_counts,
    }

    fire_cfg = scenario.get("fire") or {}
    return {
        "version": "run/v0",
        "id": f"{scenario.get('id', 'scenario')}-s{seed}",
        "buildingId": building.get("id"),
        "scenarioId": scenario.get("id"),
        "seed": seed,
        "frameInterval": FRAME_INTERVAL,
        "floors": [f["id"] for f in floors],
        "agents": [{key: a[key] for key in ("idx", "profile", "floor", "room", "v0", "startDelay")} for a in agents],
        "frames": frames,
        "smoke": list(smoke.values()),
        "fire": {"floor": fire_cfg.get("floor"), "x": fire_cfg.get("x"), "y": fire_cfg.get("y"), "hrr": hrr},
        "events": events,
        "metrics": metrics,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python -m sim.run BUILDING SCENARIO OUT", file=sys.stderr)
        return 2
    building = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    scenario = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    t0 = time.perf_counter()
    result = run(building, scenario)
    elapsed = time.perf_counter() - t0
    out = Path(argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, separators=(",", ":")), encoding="utf-8")
    print(json.dumps(result["metrics"]))
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB, {len(result['frames'])} frames) in {elapsed:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
